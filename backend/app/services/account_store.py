"""Local SQLite account and session store.

This is deliberately independent from the shared DuckDB market repository:
account identity and session state are small transactional records, while
market data remains read-only and shared between users.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from app.services.user_context import UserIdentity

_PBKDF2_ITERATIONS = 200_000
_SALT_BYTES = 16
_TOKEN_BYTES = 32
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
MAX_LOGIN_FAILURES = 5
LOGIN_LOCK_SECONDS = 300
REGISTRATION_WINDOW_SECONDS = 60 * 60
MAX_REGISTRATIONS_PER_WINDOW = 5


class RegistrationRateLimitError(Exception):
    """Raised before creating a new account when one client exceeds its window."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(1, int(retry_after))
        super().__init__(f"registration rate limited for {self.retry_after} seconds")


@dataclass(frozen=True)
class AccountResult:
    user: UserIdentity
    token: str
    created: bool


@dataclass(frozen=True)
class AccountRecord:
    """Non-secret account metadata for the protected operator view."""

    id: str
    name: str
    phone: str
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class UserAiProfileRecord:
    """Encrypted, account-owned AI override metadata.

    ``encrypted_api_key`` is opaque ciphertext. Decryption belongs to the
    request-scoped AI profile service and never to API response handlers.
    """

    user_id: str
    provider: str
    base_url: str
    model: str
    encrypted_api_key: bytes | None
    user_agent: str
    codex_command: str
    codex_reasoning_effort: str
    updated_at: float


class AccountStore:
    """Thread-safe account database with idempotent versioned migrations."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "accounts.sqlite3"
        self._lock = threading.RLock()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    @contextmanager
    def _connection(self):
        """Yield a SQLite connection and always release its file handle."""
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _migrate(self) -> None:
        migration_root = Path(__file__).resolve().parents[1] / "db" / "migrations"
        migrations = (
            (1, migration_root / "001_accounts.sql"),
            (2, migration_root / "002_account_security.sql"),
            (3, migration_root / "003_registration_rate_limit.sql"),
            (4, migration_root / "004_user_ai_profiles.sql"),
            (5, migration_root / "005_user_preferences.sql"),
        )
        with self._lock, self._connection() as conn:
            # Lock before reading user_version. Multiple server workers may
            # start against a fresh database at the same time; reading first
            # lets every worker observe the same stale version and repeat an
            # ALTER TABLE after the first worker commits.
            conn.execute("BEGIN IMMEDIATE")
            try:
                version = int(conn.execute("PRAGMA user_version").fetchone()[0])
                for target_version, migration_path in migrations:
                    if version >= target_version:
                        continue
                    sql = migration_path.read_text(encoding="utf-8")
                    # Execute statements individually so the explicit
                    # BEGIN/COMMIT remains atomic (sqlite3.executescript()
                    # implicitly commits any active transaction).
                    for statement in sql.split(";"):
                        statement = statement.strip()
                        if statement:
                            conn.execute(statement)
                    conn.execute(f"PRAGMA user_version = {target_version}")
                    version = target_version
                conn.execute("COMMIT")
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    @staticmethod
    def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
        salt = salt or secrets.token_bytes(_SALT_BYTES)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS,
        )
        return salt.hex(), digest.hex()

    @staticmethod
    def _verify_password(password: str, salt_hex: str, digest_hex: str) -> bool:
        try:
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(digest_hex)
        except ValueError:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS,
        )
        return hmac.compare_digest(actual, expected)

    @staticmethod
    def _identity(row: sqlite3.Row) -> UserIdentity:
        return UserIdentity(id=str(row["id"]), name=str(row["name"]), phone=str(row["phone"]))

    def _create_session(self, conn: sqlite3.Connection, user_id: str) -> str:
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = time.time()
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        conn.execute(
            "INSERT INTO sessions(token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (token_hash, user_id, now + SESSION_TTL_SECONDS, now),
        )
        return token

    @staticmethod
    def _consume_registration_slot(
        conn: sqlite3.Connection,
        attempt_key: str,
        now: float,
    ) -> None:
        row = conn.execute(
            "SELECT window_started_at, success_count FROM registration_attempts "
            "WHERE attempt_key = ?",
            (attempt_key,),
        ).fetchone()
        if row is None or now - float(row["window_started_at"]) >= REGISTRATION_WINDOW_SECONDS:
            conn.execute(
                "INSERT INTO registration_attempts("
                "attempt_key, window_started_at, success_count, updated_at) "
                "VALUES (?, ?, 1, ?) ON CONFLICT(attempt_key) DO UPDATE SET "
                "window_started_at=excluded.window_started_at, success_count=1, "
                "updated_at=excluded.updated_at",
                (attempt_key, now, now),
            )
            return

        count = int(row["success_count"])
        if count >= MAX_REGISTRATIONS_PER_WINDOW:
            elapsed = max(0.0, now - float(row["window_started_at"]))
            raise RegistrationRateLimitError(REGISTRATION_WINDOW_SECONDS - int(elapsed))
        conn.execute(
            "UPDATE registration_attempts SET success_count = ?, updated_at = ? "
            "WHERE attempt_key = ?",
            (count + 1, now, attempt_key),
        )

    def enter(
        self,
        name: str,
        phone: str,
        password: str,
        *,
        registration_key: str | None = None,
    ) -> AccountResult | None:
        """Create a new account or log in an existing phone number.

        Input is intentionally not normalized: names/phones/passwords may use
        arbitrary Unicode and punctuation. Empty strings are rejected by the
        API because they cannot identify or authenticate an account.
        """
        if not phone or not password:
            raise ValueError("电话和密码不能为空")
        now = time.time()
        migrate_legacy = False
        with self._lock, self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone()
                created = row is None
                if row is not None:
                    if not self._verify_password(password, row["password_salt"], row["password_hash"]):
                        conn.execute("ROLLBACK")
                        return None
                    user = self._identity(row)
                else:
                    if not name:
                        raise ValueError("注册账户时姓名不能为空")
                    if registration_key:
                        self._consume_registration_slot(conn, registration_key, now)
                    user_id = str(uuid.uuid4())
                    salt, digest = self._hash_password(password)
                    conn.execute(
                        "INSERT INTO users(id, name, phone, password_salt, password_hash, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (user_id, name, phone, salt, digest, now, now),
                    )
                    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
                    assert row is not None
                    user = self._identity(row)
                    migrate_legacy = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
                conn.execute(
                    "UPDATE users SET status = 'active', last_login_at = ?, updated_at = ? WHERE id = ?",
                    (now, now, user.id),
                )
                token = self._create_session(conn, user.id)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        self.ensure_workspace(user.id, migrate_legacy=migrate_legacy)
        return AccountResult(user=user, token=token, created=created)

    def user_for_token(self, token: str | None) -> UserIdentity | None:
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = time.time()
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token_hash = ? AND s.expires_at > ? AND u.status = 'active'",
                (token_hash, now),
            ).fetchone()
            conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            return self._identity(row) if row else None

    def has_users(self) -> bool:
        with self._lock, self._connection() as conn:
            return conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    def list_users(self, *, offset: int = 0, limit: int = 100) -> tuple[int, list[AccountRecord]]:
        """Return bounded, non-secret account metadata for an operator cache/API."""
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if limit <= 0 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        with self._lock, self._connection() as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
            rows = conn.execute(
                "SELECT id, name, phone, created_at, updated_at FROM users "
                "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return total, [
            AccountRecord(
                id=str(row["id"]),
                name=str(row["name"]),
                phone=str(row["phone"]),
                created_at=float(row["created_at"]),
                updated_at=float(row["updated_at"]),
            )
            for row in rows
        ]

    def list_active_identities(self) -> list[UserIdentity]:
        """Return only active accounts for owner-scoped background work."""
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                "SELECT id, name, phone FROM users WHERE status = 'active' ORDER BY created_at, id"
            ).fetchall()
        return [self._identity(row) for row in rows]

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._lock, self._connection() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def revoke_user_sessions(self, user_id: str) -> None:
        """Revoke every session belonging to one account only."""
        with self._lock, self._connection() as conn:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def check_login_lock(self, attempt_key: str, *, now: float | None = None) -> int:
        """Return remaining lock seconds for an opaque client key."""
        if not attempt_key:
            raise ValueError("attempt_key must not be empty")
        current = time.time() if now is None else float(now)
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT locked_until FROM auth_attempts WHERE attempt_key = ?",
                (attempt_key,),
            ).fetchone()
            if row is None:
                return 0
            return max(0, int(float(row[0]) - current))

    def record_login_failure(self, attempt_key: str, *, now: float | None = None) -> int:
        """Record a failed attempt and return the current failure count."""
        if not attempt_key:
            raise ValueError("attempt_key must not be empty")
        current = time.time() if now is None else float(now)
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT failure_count, locked_until FROM auth_attempts WHERE attempt_key = ?",
                (attempt_key,),
            ).fetchone()
            if row is not None and float(row[1]) > current:
                return int(row[0])
            count = int(row[0]) + 1 if row is not None else 1
            locked_until = (
                current + LOGIN_LOCK_SECONDS
                if count >= MAX_LOGIN_FAILURES
                else 0.0
            )
            conn.execute(
                "INSERT INTO auth_attempts(attempt_key, failure_count, locked_until, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(attempt_key) DO UPDATE SET failure_count=excluded.failure_count, "
                "locked_until=excluded.locked_until, updated_at=excluded.updated_at",
                (attempt_key, count, locked_until, current),
            )
            return count

    def clear_login_failures(self, attempt_key: str) -> None:
        """Clear failed attempts after successful authentication."""
        if not attempt_key:
            return
        with self._lock, self._connection() as conn:
            conn.execute("DELETE FROM auth_attempts WHERE attempt_key = ?", (attempt_key,))

    def workspace(self, user_id: str) -> Path:
        """Resolve a validated UUID workspace without accepting path fragments."""
        try:
            normalized = str(uuid.UUID(user_id))
        except ValueError as exc:
            raise ValueError("invalid user id") from exc
        return self.data_dir / "users" / normalized

    def ensure_workspace(self, user_id: str, *, migrate_legacy: bool = False) -> Path:
        target = self.workspace(user_id)
        target.mkdir(parents=True, exist_ok=True)
        target_user_data = target / "user_data"
        target_user_data.mkdir(parents=True, exist_ok=True)
        # Preserve an actual pre-account single-user installation for the first
        # account. auth.json is the durable legacy-install marker. Without it,
        # files at the shared root are server seeds/caches and a newly
        # registered C-end account must start empty.
        # Copy, never move/delete: this gives a safe rollback path and avoids
        # silently destroying data if account creation is interrupted.
        legacy = self.data_dir / "user_data"
        legacy_install = legacy.exists() and (legacy / "auth.json").is_file()
        if migrate_legacy and legacy_install:
            for source in legacy.iterdir():
                if source.name in {"auth.json", "accounts.sqlite3"}:
                    continue
                destination = target_user_data / source.name
                if destination.exists():
                    continue
                try:
                    if source.is_dir():
                        shutil.copytree(source, destination)
                    else:
                        shutil.copy2(source, destination)
                except OSError:
                    # A single optional legacy artifact must not prevent login.
                    continue
        # A few older releases kept user-managed extension/strategy trees at
        # the data root. Copy them once as well; shared parquet market tables
        # are intentionally not copied because they remain public read-only
        # data for every account.
        for dirname in ("ext_data", "analysis_menus", "strategies", "backtest_results"):
            source = self.data_dir / dirname
            destination = target / dirname
            if not migrate_legacy or not legacy_install or not source.exists() or destination.exists():
                continue
            try:
                if source.is_dir():
                    shutil.copytree(source, destination)
            except OSError:
                continue
        return target

    def get_user_ai_profile(self, user_id: str) -> UserAiProfileRecord | None:
        """Return one user's encrypted override without exposing it to others."""
        self.workspace(user_id)
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT user_id, provider, base_url, model, encrypted_api_key, user_agent, "
                "codex_command, codex_reasoning_effort, updated_at "
                "FROM user_ai_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        raw_key = row["encrypted_api_key"]
        return UserAiProfileRecord(
            user_id=str(row["user_id"]),
            provider=str(row["provider"]),
            base_url=str(row["base_url"]),
            model=str(row["model"]),
            encrypted_api_key=bytes(raw_key) if raw_key is not None else None,
            user_agent=str(row["user_agent"]),
            codex_command=str(row["codex_command"]),
            codex_reasoning_effort=str(row["codex_reasoning_effort"]),
            updated_at=float(row["updated_at"]),
        )

    def save_user_ai_profile(
        self,
        user_id: str,
        *,
        provider: str,
        base_url: str,
        model: str,
        encrypted_api_key: bytes | None,
        user_agent: str,
        codex_command: str = "",
        codex_reasoning_effort: str = "",
    ) -> UserAiProfileRecord:
        """Atomically upsert an encrypted profile for the owning account only."""
        self.workspace(user_id)
        now = time.time()
        with self._lock, self._connection() as conn:
            conn.execute(
                "INSERT INTO user_ai_profiles("
                "user_id, provider, base_url, model, encrypted_api_key, user_agent, "
                "codex_command, codex_reasoning_effort, updated_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "provider=excluded.provider, base_url=excluded.base_url, model=excluded.model, "
                "encrypted_api_key=excluded.encrypted_api_key, user_agent=excluded.user_agent, "
                "codex_command=excluded.codex_command, "
                "codex_reasoning_effort=excluded.codex_reasoning_effort, "
                "updated_at=excluded.updated_at",
                (
                    user_id,
                    provider,
                    base_url,
                    model,
                    encrypted_api_key,
                    user_agent,
                    codex_command,
                    codex_reasoning_effort,
                    now,
                ),
            )
        record = self.get_user_ai_profile(user_id)
        assert record is not None
        return record

    def clear_user_ai_profile(self, user_id: str) -> bool:
        """Delete only the authenticated owner's optional override."""
        self.workspace(user_id)
        with self._lock, self._connection() as conn:
            cursor = conn.execute("DELETE FROM user_ai_profiles WHERE user_id = ?", (user_id,))
        return cursor.rowcount > 0

    def get_user_preferences_json(self, user_id: str) -> str | None:
        """Load one account's private preference document."""
        self.workspace(user_id)
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT value_json FROM user_preferences WHERE user_id = ?", (user_id,)
            ).fetchone()
        return str(row["value_json"]) if row is not None else None

    def save_user_preferences_json(self, user_id: str, value_json: str) -> None:
        """Atomically upsert one complete, validated preference document."""
        self.workspace(user_id)
        with self._lock, self._connection() as conn:
            conn.execute(
                "INSERT INTO user_preferences(user_id, value_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET value_json=excluded.value_json, "
                "updated_at=excluded.updated_at",
                (user_id, value_json, time.time()),
            )


_stores: dict[Path, AccountStore] = {}
_stores_lock = threading.Lock()


def get_account_store(data_dir: Path) -> AccountStore:
    key = Path(data_dir).resolve()
    with _stores_lock:
        store = _stores.get(key)
        if store is None:
            store = AccountStore(key)
            _stores[key] = store
        return store
