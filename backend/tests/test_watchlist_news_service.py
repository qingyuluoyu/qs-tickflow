from __future__ import annotations

from datetime import UTC, datetime

from app.data_providers.news_contract import NewsFetchResult, NewsItem
from app.services import news_user_store
from app.services.user_context import UserIdentity, reset_current_user, set_current_user
from app.services.watchlist_news import WatchlistNewsService


def _item() -> NewsItem:
    return NewsItem(
        id="cached-1",
        category="public_news",
        symbol="600519.SH",
        title="缓存新闻",
        source="Vibe-Research",
        published_at=datetime(2026, 8, 18, tzinfo=UTC),
        fetched_at=datetime(2026, 8, 18, tzinfo=UTC),
        data_version="v1",
        source_ids=["cached-1"],
    )


class _FlakyProvider:
    def __init__(self) -> None:
        self.calls = 0

    def get_news(self, category, symbols, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return NewsFetchResult(
                items=[_item()],
                source_status="ok",
                fetched_at=datetime.now(UTC),
            )
        return NewsFetchResult(
            items=[],
            source_status="unavailable",
            source_message="公开源暂时不可用",
            fetched_at=datetime.now(UTC),
        )


def test_service_returns_stale_public_cache_when_provider_reports_unavailable(tmp_path):
    provider = _FlakyProvider()
    service = WatchlistNewsService(provider=provider, cache_path=tmp_path / "news.json")

    assert service.get_news(category="public_news", symbols=["600519.SH"]).source_status == "ok"
    result = service.get_news(category="public_news", symbols=["600519.SH"])

    assert result.source_status == "stale"
    assert result.stale is True
    assert [item.id for item in result.items] == ["cached-1"]


def test_today_highlight_builds_from_cached_source_items_on_first_open(tmp_path):
    class _SourceProvider:
        def get_news(self, category, symbols, **kwargs):
            return NewsFetchResult(
                items=[_item()],
                source_status="ok",
                fetched_at=datetime.now(UTC),
            )

    user = UserIdentity("first-open", "First Open", "phone-first-open")
    token = set_current_user(user, tmp_path / "users" / user.id)
    try:
        service = WatchlistNewsService(
            provider=_SourceProvider(),
            cache_path=tmp_path / "news.json",
        )
        service.get_news(category="public_news", symbols=["600519.SH"])

        result = service.get_news(category="today_highlight", symbols=["600519.SH"])

        assert result.source_status == "ok"
        assert result.items[0].category == "today_highlight"
        assert result.items[0].source_ids == ["cached-1"]
        assert [item.id for item in news_user_store.load_highlights()] == [result.items[0].id]
    finally:
        reset_current_user(token)


def test_today_highlight_fetches_source_once_when_cache_is_cold(tmp_path):
    class _ColdProvider:
        def __init__(self):
            self.calls = []

        def get_news(self, category, symbols, **kwargs):
            self.calls.append(category)
            return NewsFetchResult(
                items=[_item().model_copy(update={"category": category})],
                source_status="ok",
                fetched_at=datetime.now(UTC),
            )

    provider = _ColdProvider()
    user = UserIdentity("cold-open", "Cold Open", "phone-cold-open")
    token = set_current_user(user, tmp_path / "users" / user.id)
    try:
        service = WatchlistNewsService(provider=provider, cache_path=tmp_path / "news.json")
        result = service.get_news(category="today_highlight", symbols=["600519.SH"])

        assert result.source_status == "ok"
        assert provider.calls == ["public_news"]
        assert result.items[0].source_ids == ["cached-1"]
    finally:
        reset_current_user(token)
