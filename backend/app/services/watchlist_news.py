"""Batch watchlist news orchestration and public article cache."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.data_providers import news_registry
from app.data_providers.news_contract import NewsCategory, NewsFetchResult, NewsItem
from app.data_providers.vibe_public_provider import NewsProviderError
from app.services import news_user_store
from app.services.user_context import current_user

_CACHE_LOCK = threading.RLock()


@contextlib.contextmanager
def _exclusive_cache_lock(path: Path):
    """Protect shared public cache writes across backend workers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a+b") as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"0")
            lock_file.flush()
        lock_file.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            lock_file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file, fcntl.LOCK_UN)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class WatchlistNewsService:
    """Keep public article caching separate from user-generated highlights."""

    def __init__(
        self,
        *,
        provider: Any | None = None,
        cache_path: Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.provider = provider
        self.cache_path = cache_path or (settings.data_dir / "cache" / "news_public.json")
        self._clock = clock or _utc_now
        self._cache: dict[str, NewsItem] | None = None

    def get_news(
        self,
        *,
        category: NewsCategory,
        symbols: list[str],
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        query: str | None = None,
        limit: int = 30,
        cursor: str | None = None,
    ) -> NewsFetchResult:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        normalized_symbols = {str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}
        if category == "today_highlight":
            items = news_user_store.filter_highlights(
                symbols=normalized_symbols,
                query=query,
                limit=limit,
            )
            if not items and normalized_symbols:
                # The background preloader is deliberately asynchronous. On a
                # user's first click, build the cards from source-backed public
                # articles already in the shared cache so the tab is not blank.
                cached = self._filter_items(
                    self._load_cache(),
                    normalized_symbols,
                    query,
                    limit,
                )
                source_result: NewsFetchResult | None = None
                if not cached:
                    # A cold process may not have run the preloader yet. Fetch
                    # at most one batch per source, and only use normalized
                    # provider results; no fallback text is fabricated.
                    for source_category in ("public_news", "announcement"):
                        source_result = self.get_news(
                            category=source_category,
                            symbols=sorted(normalized_symbols),
                            start_time=start_time,
                            end_time=end_time,
                            query=query,
                            limit=max(limit, 30),
                            cursor=cursor,
                        )
                        cached = self._filter_items(
                            source_result.items,
                            normalized_symbols,
                            query,
                            limit,
                        )
                        if cached:
                            break
                if cached:
                    generated = self.build_highlights(cached, limit=limit)
                    self._persist_first_open_highlights(generated)
                    return NewsFetchResult(
                        items=generated,
                        source_status=(
                            "stale"
                            if source_result is not None and source_result.stale
                            else "ok"
                        ),
                        source_message=(
                            source_result.source_message
                            if source_result is not None
                            else "基于真实公开资讯生成"
                        ),
                        stale=bool(source_result and source_result.stale),
                        fetched_at=self._clock(),
                    )
                if source_result is not None and source_result.source_status in {
                    "invalid",
                    "unavailable",
                }:
                    return NewsFetchResult(
                        items=[],
                        source_status=source_result.source_status,
                        source_message=source_result.source_message,
                        stale=source_result.stale,
                        fetched_at=self._clock(),
                    )
            return NewsFetchResult(
                items=items,
                source_status="ok" if items else "empty",
                fetched_at=self._clock(),
            )
        if not normalized_symbols:
            return NewsFetchResult(items=[], source_status="empty", fetched_at=self._clock())

        provider = self.provider or news_registry.get_provider()
        if provider is None:
            return NewsFetchResult(
                items=[],
                source_status="unavailable",
                source_message="VibePublic 资讯接口未配置",
                fetched_at=self._clock(),
            )
        try:
            result = provider.get_news(
                category=category,
                symbols=sorted(normalized_symbols),
                start_time=start_time,
                end_time=end_time,
                query=query,
                limit=limit,
                cursor=cursor,
            )
            if result.source_status in {"unavailable", "invalid"} and not result.items:
                cached = self._filter_items(self._load_cache(), normalized_symbols, query, limit, category)
                if cached:
                    return NewsFetchResult(
                        items=cached,
                        source_status="stale",
                        source_message=result.source_message,
                        stale=True,
                        fetched_at=self._clock(),
                    )
            self._merge_cache(result.items)
            items = self._filter_items(result.items, normalized_symbols, query, limit)
            return result.model_copy(update={"items": items})
        except NewsProviderError as exc:
            cached = self._filter_items(self._load_cache(), normalized_symbols, query, limit, category)
            if cached:
                return NewsFetchResult(
                    items=cached,
                    source_status="stale",
                    source_message=str(exc),
                    stale=True,
                    fetched_at=self._clock(),
                )
            return NewsFetchResult(
                items=[],
                source_status=exc.status if exc.status in {"invalid", "unavailable"} else "unavailable",
                source_message=str(exc),
                fetched_at=self._clock(),
            )

    def get_item(self, *, item_id: str, category: NewsCategory, symbols: list[str]) -> NewsItem | None:
        """Resolve one item only within the authenticated user's symbol scope."""
        normalized_symbols = {str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}
        if category == "today_highlight":
            candidates = news_user_store.load_highlights()
        else:
            candidates = self._load_cache()
        for item in candidates:
            if item.id == item_id and item.category == category and item.symbol in normalized_symbols:
                return item
        return None

    def cached_items(self, *, symbols: set[str], limit: int = 100) -> list[NewsItem]:
        """Return public cached articles for a symbol set, never user highlights."""
        return self._filter_items(self._load_cache(), symbols, None, limit)

    def build_highlights(self, items: list[NewsItem], *, limit: int = 5) -> list[NewsItem]:
        """Create source-backed highlight cards without inventing article text."""
        output: list[NewsItem] = []
        for item in items[:limit]:
            digest = hashlib.sha256(
                f"today-highlight|{item.id}|{item.published_at or item.fetched_at}".encode()
            ).hexdigest()[:32]
            output.append(
                NewsItem(
                    id=f"highlight-{digest}",
                    category="today_highlight",
                    symbol=item.symbol,
                    name=item.name,
                    title=item.title,
                    summary=item.summary,
                    content=item.content,
                    url=item.url,
                    source=item.source,
                    published_at=item.published_at,
                    fetched_at=self._clock(),
                    data_version=f"highlight:{item.data_version}",
                    generated=False,
                    source_ids=[item.id],
                )
            )
        return output

    def _persist_first_open_highlights(self, items: list[NewsItem]) -> None:
        """Persist first-open cards only inside the active user's workspace."""
        if not items or current_user() is None:
            return
        existing = news_user_store.load_highlights()
        merged = {item.id: item for item in existing}
        merged.update({item.id: item for item in items})
        news_user_store.save_highlights(list(merged.values()))

    def _filter_items(
        self,
        items: list[NewsItem],
        symbols: set[str],
        query: str | None,
        limit: int,
        category: str | None = None,
    ) -> list[NewsItem]:
        normalized_query = (query or "").strip().casefold()
        filtered = [
            item for item in items
            if item.symbol in symbols
            and (category is None or item.category == category)
            and (
                not normalized_query
                or normalized_query in " ".join(
                    part.casefold()
                    for part in (item.title, item.summary or "", item.content or "", item.source)
                )
            )
        ]
        filtered.sort(key=lambda item: item.published_at or item.fetched_at, reverse=True)
        return filtered[:limit]

    def _load_cache(self) -> list[NewsItem]:
        with _CACHE_LOCK:
            if self._cache is not None:
                return list(self._cache.values())
            path = self.cache_path
            if not path.exists():
                self._cache = {}
                return []
            try:
                with _exclusive_cache_lock(path):
                    payload = json.loads(path.read_text(encoding="utf-8"))
                rows = payload.get("items", []) if isinstance(payload, dict) else []
                self._cache = {
                    item.id: item
                    for item in (NewsItem.model_validate(row) for row in rows)
                    if item.category in {"announcement", "public_news"}
                }
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                self._cache = {}
            return list(self._cache.values())

    def _merge_cache(self, items: list[NewsItem]) -> None:
        if not items:
            return
        with _CACHE_LOCK:
            path = self.cache_path
            with _exclusive_cache_lock(path):
                # Re-read while holding the process lock so two workers do not
                # overwrite each other's newly fetched articles.
                self._cache = {}
                if path.exists():
                    try:
                        payload = json.loads(path.read_text(encoding="utf-8"))
                        rows = payload.get("items", []) if isinstance(payload, dict) else []
                        self._cache = {
                            item.id: item
                            for item in (NewsItem.model_validate(row) for row in rows)
                            if item.category in {"announcement", "public_news"}
                        }
                    except (OSError, ValueError, TypeError, json.JSONDecodeError):
                        self._cache = {}
                for item in items:
                    if item.category in {"announcement", "public_news"}:
                        self._cache[item.id] = item
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
                try:
                    temporary.write_text(
                        json.dumps(
                            {"version": 1, "items": [item.model_dump(mode="json") for item in self._cache.values()]},
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        encoding="utf-8",
                    )
                    os.replace(temporary, path)
                finally:
                    with contextlib.suppress(FileNotFoundError):
                        temporary.unlink()
