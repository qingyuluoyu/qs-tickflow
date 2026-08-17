import shutil
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.services.account_store import AccountStore


class _CursorAfterReadBarrier:
    def __init__(self, cursor, barrier: threading.Barrier) -> None:
        self._cursor = cursor
        self._barrier = barrier

    def fetchone(self):
        row = self._cursor.fetchone()
        self._barrier.wait(timeout=5)
        return row


class _ConnectionAfterReadBarrier:
    def __init__(self, connection: sqlite3.Connection, barrier: threading.Barrier) -> None:
        self._connection = connection
        self._barrier = barrier

    def execute(self, sql, parameters=()):
        cursor = self._connection.execute(sql, parameters)
        if sql.strip().upper() == "PRAGMA USER_VERSION" and not self._connection.in_transaction:
            return _CursorAfterReadBarrier(cursor, self._barrier)
        return cursor

    def __enter__(self):
        self._connection.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return self._connection.__exit__(exc_type, exc_value, traceback)

    def __getattr__(self, name):
        return getattr(self._connection, name)


class _CoordinatedAccountStore(AccountStore):
    def __init__(self, data_dir: Path, barrier: threading.Barrier) -> None:
        self._migration_barrier = barrier
        super().__init__(data_dir)

    def _connect(self):
        return _ConnectionAfterReadBarrier(super()._connect(), self._migration_barrier)


def test_account_migration_and_create_login_are_transactional(tmp_path: Path):
    legacy = tmp_path / "user_data"
    legacy.mkdir()
    # auth.json is the durable marker that this is an actual pre-account
    # single-user installation, rather than server-owned seed/cache data.
    (legacy / "auth.json").write_text("{}", encoding="utf-8")
    (legacy / "watchlist.parquet").write_bytes(b"legacy")

    store = AccountStore(tmp_path)
    result = store.enter("张三", "电话/001", "任意密码🙂")

    assert result is not None
    assert result.created is True
    assert result.user.name == "张三"
    assert store.user_for_token(result.token) == result.user
    assert (store.workspace(result.user.id) / "user_data" / "watchlist.parquet").read_bytes() == b"legacy"

    assert store.enter("另一个名字", "电话/001", "错误") is None
    logged_in = store.enter("另一个名字", "电话/001", "任意密码🙂")
    assert logged_in is not None
    assert logged_in.created is False
    assert logged_in.user.name == "张三"

    bob = store.enter("李四", "电话/002", "新密码")
    assert bob is not None and bob.created is True
    # A second account must not receive the legacy first-user files.
    assert not (store.workspace(bob.user.id) / "user_data" / "watchlist.parquet").exists()

    import sqlite3

    with sqlite3.connect(store.path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2


def test_first_new_account_does_not_copy_server_seed_or_cache_data(tmp_path: Path):
    legacy = tmp_path / "user_data"
    legacy.mkdir()
    (legacy / "watchlist.parquet").write_bytes(b"server-seed")
    (legacy / "strategy_cache.json").write_text("{}", encoding="utf-8")
    for dirname in ("ext_data", "analysis_menus", "strategies", "backtest_results"):
        seeded = tmp_path / dirname
        seeded.mkdir()
        (seeded / "server-owned.txt").write_text("seed", encoding="utf-8")

    store = AccountStore(tmp_path)
    result = store.enter("新用户", "new-user", "password")

    assert result is not None and result.created is True
    workspace = store.workspace(result.user.id)
    assert list((workspace / "user_data").iterdir()) == []
    assert not (workspace / "ext_data").exists()
    assert not (workspace / "analysis_menus").exists()
    assert not (workspace / "strategies").exists()
    assert not (workspace / "backtest_results").exists()


def test_workspaces_are_distinct_and_logout_revokes_only_one_token(tmp_path: Path):
    store = AccountStore(tmp_path)
    alice = store.enter("Alice", "A", "pw")
    bob = store.enter("Bob", "B", "pw")
    assert alice is not None and bob is not None
    assert alice.user.id != bob.user.id
    assert store.workspace(alice.user.id) != store.workspace(bob.user.id)

    store.revoke(alice.token)
    assert store.user_for_token(alice.token) is None
    assert store.user_for_token(bob.token) == bob.user


def test_operator_listing_is_bounded_and_never_returns_password_material(tmp_path: Path):
    store = AccountStore(tmp_path)
    store.enter("张三", "电话-一", "密码-一")
    store.enter("李四", "电话-二", "密码-二")

    total, rows = store.list_users(limit=1)

    assert total == 2
    assert len(rows) == 1
    assert rows[0].name in {"张三", "李四"}
    assert not hasattr(rows[0], "password_hash")


def test_account_security_migration_tracks_login_and_persistent_lock(tmp_path: Path):
    import sqlite3

    store = AccountStore(tmp_path)
    result = store.enter("张三", "电话-一", "密码-一")
    assert result is not None

    with sqlite3.connect(store.path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        assert version == 5
        assert {"status", "last_login_at"} <= columns
        assert conn.execute("SELECT status FROM users").fetchone()[0] == "active"
        first_login = conn.execute("SELECT last_login_at FROM users").fetchone()[0]
        assert first_login is not None

    # A new store instance must observe the same lock; this is what makes the
    # limiter effective when the server is run with more than one worker.
    key = "hashed-client-key"
    for _ in range(5):
        store.record_login_failure(key, now=100.0)
    other = AccountStore(tmp_path)
    assert other.check_login_lock(key, now=101.0) > 0
    other.clear_login_failures(key)
    assert other.check_login_lock(key, now=101.0) == 0

    logged_in = other.enter("不同名字", "电话-一", "密码-一")
    assert logged_in is not None
    with sqlite3.connect(other.path) as conn:
        assert conn.execute("SELECT last_login_at FROM users").fetchone()[0] >= first_login


def test_concurrent_workers_serialize_database_migrations(tmp_path: Path):
    migration = Path(__file__).resolve().parents[1] / "app" / "db" / "migrations" / "001_accounts.sql"
    db_path = tmp_path / "accounts.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(migration.read_text(encoding="utf-8"))
        conn.execute("PRAGMA user_version = 1")

    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_CoordinatedAccountStore, tmp_path, barrier) for _ in range(2)]
        stores = [future.result(timeout=10) for future in futures]

    assert len(stores) == 2
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
        columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        assert {"status", "last_login_at"} <= columns


def test_concurrent_account_registration_keeps_users_and_sessions_distinct(tmp_path: Path):
    AccountStore(tmp_path)
    worker_count = 6
    barrier = threading.Barrier(worker_count)

    def register(index: int):
        store = AccountStore(tmp_path)
        barrier.wait(timeout=10)
        result = store.enter(f"用户{index}", f"phone-{index}", f"密码-{index}")
        assert result is not None
        assert store.user_for_token(result.token) == result.user
        return result

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        results = list(pool.map(register, range(worker_count)))

    assert all(result.created for result in results)
    assert len({result.user.id for result in results}) == worker_count
    assert len({AccountStore(tmp_path).workspace(result.user.id) for result in results}) == worker_count


def test_concurrent_same_phone_registration_creates_only_one_account(tmp_path: Path):
    AccountStore(tmp_path)
    worker_count = 4
    barrier = threading.Barrier(worker_count)

    def enter_same_account(_index: int):
        store = AccountStore(tmp_path)
        barrier.wait(timeout=10)
        return store.enter("同一用户", "same-phone", "same-password")

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        results = list(pool.map(enter_same_account, range(worker_count)))

    assert all(result is not None for result in results)
    successful = [result for result in results if result is not None]
    assert sum(result.created for result in successful) == 1
    assert len({result.user.id for result in successful}) == 1
    assert all(AccountStore(tmp_path).user_for_token(result.token) == result.user for result in successful)


def test_offline_backup_restore_preserves_accounts_sessions_and_workspaces(tmp_path: Path):
    source = tmp_path / "source"
    backup = tmp_path / "backup"
    restored = tmp_path / "restored"
    store = AccountStore(source)
    alice = store.enter("Alice", "backup-alice", "alice-password")
    bob = store.enter("Bob", "backup-bob", "bob-password")
    assert alice is not None and bob is not None
    (store.workspace(alice.user.id) / "user_data" / "marker.txt").write_text("alice", encoding="utf-8")
    (store.workspace(bob.user.id) / "user_data" / "marker.txt").write_text("bob", encoding="utf-8")

    shutil.copytree(source, backup)
    shutil.copytree(backup, restored)
    restored_store = AccountStore(restored)

    assert restored_store.user_for_token(alice.token) == alice.user
    assert restored_store.user_for_token(bob.token) == bob.user
    assert (restored_store.workspace(alice.user.id) / "user_data" / "marker.txt").read_text(encoding="utf-8") == "alice"
    assert (restored_store.workspace(bob.user.id) / "user_data" / "marker.txt").read_text(encoding="utf-8") == "bob"
    assert restored_store.enter("Alice", "backup-alice", "alice-password") is not None
    assert restored_store.enter("Bob", "backup-bob", "bob-password") is not None


def test_revoke_user_sessions_revokes_only_one_account(tmp_path: Path):
    store = AccountStore(tmp_path)
    alice = store.enter("Alice", "A", "pw")
    bob = store.enter("Bob", "B", "pw")
    assert alice is not None and bob is not None

    store.revoke_user_sessions(alice.user.id)

    assert store.user_for_token(alice.token) is None
    assert store.user_for_token(bob.token) == bob.user
