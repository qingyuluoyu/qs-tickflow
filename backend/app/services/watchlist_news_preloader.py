"""Background prefetch for public news and per-account source-backed highlights."""
from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.services import watchlist
from app.services.user_context import reset_current_user, set_current_user
from app.services.watchlist_news import WatchlistNewsService

logger = logging.getLogger(__name__)


class WatchlistNewsPreloader:
    def __init__(
        self,
        *,
        account_store: Any,
        shared_root: Path,
        service: WatchlistNewsService,
        interval_s: float = 300.0,
    ) -> None:
        self.account_store = account_store
        self.shared_root = Path(shared_root)
        self.service = service
        self.interval_s = max(30.0, float(interval_s))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="watchlist-news-preloader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def status(self) -> dict[str, object]:
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "interval_s": self.interval_s,
        }

    def run_once(self) -> dict[str, int]:
        identities = self.account_store.list_active_identities()
        scoped: list[tuple[Any, Path, list[str]]] = []
        union: set[str] = set()
        for identity in identities:
            root = self.account_store.ensure_workspace(identity.id)
            tokens = set_current_user(identity, root)
            try:
                symbols = sorted({
                    str(row.get("symbol", "")).strip().upper()
                    for row in watchlist.list_symbols()
                    if row.get("symbol")
                })
            finally:
                reset_current_user(tokens)
            scoped.append((identity, root, symbols))
            union.update(symbols)

        if not union:
            return {"users": len(scoped), "symbols": 0, "written": 0}

        now = datetime.now(UTC)
        successful_fetch = False
        for category in ("announcement", "public_news"):
            result = self.service.get_news(
                category=category,
                symbols=sorted(union),
                start_time=now - timedelta(days=7),
                end_time=now,
                limit=100,
            )
            successful_fetch = successful_fetch or result.source_status in {"ok", "empty"}

        if not successful_fetch:
            return {"users": len(scoped), "symbols": len(union), "written": 0}

        written = 0
        for identity, root, symbols in scoped:
            tokens = set_current_user(identity, root)
            try:
                items = self.service.cached_items(symbols=set(symbols), limit=100)
                highlights = self.service.build_highlights(items, limit=5)
                # A successful empty upstream response is authoritative for the
                # current window and clears yesterday's source-backed cards.
                from app.services import news_user_store

                news_user_store.save_highlights(highlights)
                written += 1
            except Exception:
                logger.exception("watchlist news highlight write failed for user %s", identity.id)
            finally:
                reset_current_user(tokens)
        return {"users": len(scoped), "symbols": len(union), "written": written}

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("watchlist news preloader failed")
            self._stop.wait(self.interval_s)
