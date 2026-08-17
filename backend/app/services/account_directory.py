"""Background-prepared account metadata for the protected operator view.

The customer-facing application never reads this cache.  It is deliberately
limited to non-secret registration metadata so an operator page can render a
bounded page without asking SQLite for every row during a request.
"""
from __future__ import annotations

import threading
import time
from dataclasses import asdict
from typing import Any

from app.services.account_store import AccountStore

_PAGE_SIZE = 500
_MAX_CACHED_USERS = 10_000


class AccountDirectoryCache:
    """Refresh account metadata in the background and serve bounded pages."""

    def __init__(self, store: AccountStore, *, refresh_interval: float = 30.0) -> None:
        if refresh_interval <= 0:
            raise ValueError("refresh_interval must be positive")
        self.store = store
        self.refresh_interval = float(refresh_interval)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._rows: list[dict[str, Any]] = []
        self._total = 0
        self._complete = False
        self._refreshed_at = 0.0
        self._last_success_at = 0.0
        self._last_attempt_at = 0.0
        self._last_error: str | None = None
        self._last_duration_ms = 0.0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self.refresh_now()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="account-directory-refresh",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=min(self.refresh_interval, 2.0))
        self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self.refresh_interval):
            try:
                self.refresh_now()
            except Exception:
                # A temporary SQLite or filesystem error must not stop the
                # server; the last verified snapshot remains usable.
                continue

    def refresh_now(self) -> bool:
        started = time.perf_counter()
        with self._lock:
            self._last_attempt_at = time.time()
        offset = 0
        rows: list[dict[str, Any]] = []
        total = 0
        try:
            while offset < _MAX_CACHED_USERS:
                page_total, page_rows = self.store.list_users(offset=offset, limit=_PAGE_SIZE)
                total = page_total
                rows.extend(asdict(item) for item in page_rows)
                offset += len(page_rows)
                if not page_rows or offset >= page_total:
                    break
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._last_duration_ms = (time.perf_counter() - started) * 1000
            return False
        with self._lock:
            self._rows = rows[:_MAX_CACHED_USERS]
            self._total = total
            self._complete = total <= _MAX_CACHED_USERS
            self._refreshed_at = time.time()
            self._last_success_at = self._refreshed_at
            self._last_error = None
            self._last_duration_ms = (time.perf_counter() - started) * 1000
        return True

    def page(self, *, offset: int = 0, limit: int = 100) -> tuple[int, list[dict[str, Any]]]:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if limit <= 0 or limit > _PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {_PAGE_SIZE}")
        with self._lock:
            if self._complete and offset + limit <= len(self._rows):
                return self._total, [dict(row) for row in self._rows[offset:offset + limit]]
            if self._complete and offset >= self._total:
                return self._total, []
        total, rows = self.store.list_users(offset=offset, limit=limit)
        return total, [asdict(item) for item in rows]

    def status(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            stale = (
                self._last_success_at <= 0
                or (now - self._last_success_at) > max(self.refresh_interval * 2, 60.0)
                or self._last_error is not None
            )
            return {
                "refreshed_at": self._refreshed_at,
                "last_success_at": self._last_success_at,
                "last_attempt_at": self._last_attempt_at,
                "last_error": self._last_error,
                "refresh_duration_ms": round(self._last_duration_ms, 2),
                "total": self._total,
                "complete": self._complete,
                "stale": stale,
            }

    @property
    def refreshed_at(self) -> float:
        with self._lock:
            return self._refreshed_at
