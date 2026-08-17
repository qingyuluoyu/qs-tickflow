"""Per-account real-time monitor engine registry.

Market data is shared and read-only, but monitor rules, strategy overrides,
cooldowns and latest strategy results are private account state.  The quote
poller uses this registry to evaluate one engine per authenticated account
instead of reusing the legacy process-wide engine.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from app.services.account_store import AccountStore
from app.services.user_context import UserIdentity
from app.strategy import config as strategy_config
from app.strategy import monitor_rules
from app.strategy.engine import StrategyEngine
from app.strategy.monitor import MonitorRuleEngine

logger = logging.getLogger(__name__)


@dataclass
class AccountMonitorHandle:
    user: UserIdentity
    data_root: Path
    strategy_engine: StrategyEngine
    monitor_engine: MonitorRuleEngine
    lock: threading.RLock
    last_evaluation_at: float = 0.0
    last_evaluation_duration_ms: float = 0.0
    evaluation_count: int = 0
    evaluation_error_count: int = 0
    evaluation_skipped_count: int = 0
    evaluation_running: bool = False


class AccountMonitorRuntime:
    """Lazily refreshed, account-scoped monitor engines.

    Refreshing the account list is bounded and happens outside the quote hot
    path at most once per ``refresh_interval``.  A rule write calls
    :meth:`invalidate`, so an account does not have to wait for the next
    refresh cycle before its monitor changes take effect.
    """

    def __init__(
        self,
        *,
        account_store: AccountStore,
        shared_root: Path,
        builtin_dir: Path,
        history_loader,
        history_loader_etf,
        sector_monitor_service,
        repo=None,
        refresh_interval: float = 15.0,
    ) -> None:
        if refresh_interval <= 0:
            raise ValueError("refresh_interval must be positive")
        self.account_store = account_store
        self.shared_root = Path(shared_root)
        self.builtin_dir = Path(builtin_dir)
        self.history_loader = history_loader
        self.history_loader_etf = history_loader_etf
        self.sector_monitor_service = sector_monitor_service
        self.repo = repo
        self.refresh_interval = float(refresh_interval)
        self._lock = threading.RLock()
        self._handles: dict[str, AccountMonitorHandle] = {}
        self._last_refresh = 0.0
        self._last_success_at = 0.0
        self._last_attempt_at = 0.0
        self._last_error: str | None = None
        self._last_duration_ms = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the account refresh loop once.

        The initial refresh is synchronous so the first market poll never
        observes an empty account registry by accident. Later refreshes run in
        this bounded background loop and never block an HTTP request.
        """
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
        self.refresh_now()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="account-monitor-refresh",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the refresh loop and wait briefly for the current refresh."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=min(self.refresh_interval, 2.0))
        self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self.refresh_interval):
            self.refresh_now()

    def refresh_if_due(self) -> None:
        if time.monotonic() - self._last_refresh >= self.refresh_interval:
            self.refresh_now()

    def refresh_now(self) -> bool:
        """Discover accounts and atomically install their current rule sets.

        If the account store is temporarily unavailable, retain the last
        verified registry. Returning ``False`` lets health surfaces distinguish
        a stale snapshot from an empty, healthy directory.
        """
        started = time.perf_counter()
        with self._lock:
            self._last_attempt_at = time.time()
        records = []
        offset = 0
        try:
            while True:
                total, page = self.account_store.list_users(offset=offset, limit=500)
                records.extend(page)
                offset += len(page)
                if not page or offset >= total:
                    break
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._last_duration_ms = (time.perf_counter() - started) * 1000
            logger.warning("account monitor refresh failed; retaining snapshot", exc_info=True)
            return False

        discovered = {record.id: record for record in records}
        with self._lock:
            for user_id, record in discovered.items():
                try:
                    handle = self._handles.get(user_id)
                    if handle is None:
                        handle = self._build_handle(
                            UserIdentity(record.id, record.name, record.phone),
                        )
                        self._handles[user_id] = handle
                    else:
                        handle.user = UserIdentity(record.id, record.name, record.phone)
                    self._reload_handle(handle)
                except Exception:
                    # One malformed workspace must not stop monitoring for
                    # every other account.  Keep the last verified engine if
                    # this is an existing account.
                    logger.warning(
                        "account monitor refresh failed (user=%s)", user_id,
                        exc_info=True,
                    )
            for user_id in set(self._handles) - set(discovered):
                self._handles.pop(user_id, None)
            self._last_refresh = time.monotonic()
            self._last_success_at = time.time()
            self._last_error = None
            self._last_duration_ms = (time.perf_counter() - started) * 1000
        return True

    def status(self) -> dict[str, object]:
        with self._lock:
            now = time.time()
            last_success = self._last_success_at
            handles = list(self._handles.values())
            return {
                "running": self._thread is not None and self._thread.is_alive(),
                "last_success_at": last_success,
                "last_attempt_at": self._last_attempt_at,
                "last_error": self._last_error,
                "refresh_duration_ms": round(self._last_duration_ms, 2),
                "total": len(handles),
                "enabled_rule_accounts": sum(
                    1 for handle in handles if handle.monitor_engine.rule_count > 0
                ),
                "evaluation_running": sum(1 for handle in handles if handle.evaluation_running),
                "evaluation_count": sum(handle.evaluation_count for handle in handles),
                "evaluation_error_count": sum(handle.evaluation_error_count for handle in handles),
                "evaluation_skipped_count": sum(handle.evaluation_skipped_count for handle in handles),
                "stale": (
                    last_success <= 0
                    or (now - last_success) > max(self.refresh_interval * 2, 60.0)
                    or self._last_error is not None
                ),
            }

    def _build_handle(self, user: UserIdentity) -> AccountMonitorHandle:
        root = self.account_store.ensure_workspace(user.id)
        strategy_dirs = [
            self.builtin_dir,
            *(root / "strategies" / source for source in ("custom", "ai", "composite")),
        ]
        strategy_engine = StrategyEngine(
            strategy_dirs=strategy_dirs,
            override_loader=lambda strategy_id, data_root=root: strategy_config.load_override(
                data_root, strategy_id,
            ),
        )
        monitor_engine = MonitorRuleEngine()
        monitor_engine.set_strategy_engine(strategy_engine)
        monitor_engine.set_data_dir(root)
        monitor_engine.set_sector_monitor_service(self.sector_monitor_service)
        monitor_engine.set_history_loader(self.history_loader)
        monitor_engine.set_history_loader_etf(self.history_loader_etf)
        return AccountMonitorHandle(
            user=user,
            data_root=root,
            strategy_engine=strategy_engine,
            monitor_engine=monitor_engine,
            lock=threading.RLock(),
        )

    def record_evaluation(
        self,
        user_id: str,
        *,
        duration_ms: float = 0.0,
        error: bool = False,
        skipped: bool = False,
        running: bool | None = None,
        complete: bool = True,
    ) -> None:
        """Record bounded monitor work without exposing account data."""
        with self._lock:
            handle = self._handles.get(user_id)
            if handle is None:
                return
            if skipped:
                handle.evaluation_skipped_count += 1
            elif complete:
                handle.evaluation_count += 1
                handle.last_evaluation_at = time.time()
                handle.last_evaluation_duration_ms = max(0.0, float(duration_ms))
            if error:
                handle.evaluation_error_count += 1
            if running is not None:
                handle.evaluation_running = running

    def _load_rules(self, handle: AccountMonitorHandle) -> list[dict]:
        rules = monitor_rules.load_all(handle.data_root)
        resolver = getattr(self.repo, "resolve_asset_type", None)
        if not callable(resolver):
            return rules
        for rule in rules:
            if rule.get("asset_type", "stock") != "stock" or rule.get("scope") != "symbols":
                continue
            symbols = [symbol for symbol in rule.get("symbols", []) if symbol]
            try:
                if symbols and all(resolver(symbol) == "index" for symbol in symbols):
                    rule["asset_type"] = "index"
            except Exception:
                continue
        return rules

    def _reload_handle(self, handle: AccountMonitorHandle) -> None:
        # set_rules performs an atomic replacement and also clears stale
        # cooldown/state entries for deleted or changed rules.
        with handle.lock:
            handle.monitor_engine.set_rules(self._load_rules(handle))

    def invalidate(self, user_id: str) -> None:
        """Reload one account immediately after a rule/strategy change."""
        with self._lock:
            handle = self._handles.get(user_id)
            if handle is None:
                # The account may have been created moments ago; a bounded
                # refresh discovers it without exposing any other account.
                self.refresh_now()
                handle = self._handles.get(user_id)
            if handle is None:
                return
            with handle.lock:
                handle.strategy_engine.reload()
                handle.monitor_engine.invalidate_strategy_state()
                handle.monitor_engine.set_rules(self._load_rules(handle))

    def get(self, user_id: str) -> MonitorRuleEngine | None:
        with self._lock:
            handle = self._handles.get(user_id)
            return handle.monitor_engine if handle else None

    def entries(self, *, active_only: bool = False) -> list[AccountMonitorHandle]:
        with self._lock:
            handles = list(self._handles.values())
        if active_only:
            return [handle for handle in handles if handle.monitor_engine.rule_count > 0]
        return handles

    def has_users(self) -> bool:
        with self._lock:
            return bool(self._handles)

    def index_symbols(self) -> set[str]:
        symbols: set[str] = set()
        for handle in self.entries(active_only=True):
            for rule in handle.monitor_engine.rules.values():
                if (
                    rule.get("enabled", True)
                    and rule.get("asset_type") == "index"
                    and rule.get("scope") == "symbols"
                ):
                    symbols.update(str(symbol) for symbol in rule.get("symbols", []) if symbol)
        return symbols

    def intraday_symbols(self, asset_type: str) -> set[str]:
        symbols: set[str] = set()
        for handle in self.entries(active_only=True):
            symbols.update(handle.monitor_engine.intraday_signal_symbols(asset_type))
        return symbols

    def watchlist_symbols(self, *, limit_per_account: int = 5, max_total: int = 5000) -> set[str]:
        """Return a bounded union of account watchlists for server polling.

        This method deliberately reads each validated workspace directly and
        never relies on the request-scoped user ContextVar.  A partially
        written or malformed private file is skipped and retried on the next
        background refresh instead of contaminating another account.
        """
        if limit_per_account <= 0 or max_total <= 0:
            return set()
        symbols: set[str] = set()
        for handle in self.entries():
            path = handle.data_root / "user_data" / "watchlist.parquet"
            if not path.exists():
                continue
            try:
                frame = pl.read_parquet(path, columns=["symbol"])
            except Exception:
                logger.warning("account watchlist read failed (user=%s)", handle.user.id, exc_info=True)
                continue
            if frame.is_empty() or "symbol" not in frame.columns:
                continue
            for value in frame["symbol"].head(limit_per_account).to_list():
                symbol = str(value or "").strip().upper()
                if symbol:
                    symbols.add(symbol)
                    if len(symbols) >= max_total:
                        return symbols
        return symbols

    def has_asset_rules(self, asset_type: str) -> bool:
        return any(
            handle.monitor_engine.has_asset_rules(asset_type)
            for handle in self.entries(active_only=True)
        )
