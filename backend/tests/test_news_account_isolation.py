from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.data_providers.news_contract import NewsFetchResult, NewsItem
from app.services import news_user_store
from app.services.user_context import UserIdentity, reset_current_user, set_current_user


def _bind(tmp_path: Path, user_id: str):
    user = UserIdentity(user_id, user_id.title(), f"phone-{user_id}")
    return set_current_user(user, tmp_path / "users" / user_id)


def _item(item_id: str, symbol: str) -> NewsItem:
    return NewsItem(
        id=item_id,
        category="public_news",
        symbol=symbol,
        title=item_id,
        source="VibePublic",
        fetched_at=datetime.now(UTC),
        data_version="v1",
        source_ids=[item_id],
    )


def test_news_highlights_are_stored_in_the_authenticated_workspace(tmp_path: Path):
    alice = _bind(tmp_path, "alice")
    try:
        news_user_store.save_highlights([_item("alice-article", "000001.SZ")])
    finally:
        reset_current_user(alice)

    bob = _bind(tmp_path, "bob")
    try:
        assert news_user_store.load_highlights() == []
    finally:
        reset_current_user(bob)

    alice_file = tmp_path / "users" / "alice" / "user_data" / "news_highlights.json"
    bob_file = tmp_path / "users" / "bob" / "user_data" / "news_highlights.json"
    assert alice_file.exists()
    assert not bob_file.exists()


def test_news_highlights_reject_unknown_source_ids_for_user_scope(tmp_path: Path):
    token = _bind(tmp_path, "alice")
    try:
        news_user_store.save_highlights([_item("alice-article", "000001.SZ")])
        assert news_user_store.filter_highlights(
            symbols={"000001.SZ"},
            source_ids={"other-user-article"},
        ) == []
    finally:
        reset_current_user(token)


class _FakeProvider:
    name = "vibe_public"

    def __init__(self):
        self.calls: list[list[str]] = []

    def get_news(self, category, symbols, **kwargs):
        self.calls.append(symbols)
        return NewsFetchResult(
            items=[_item("a", "000001.SZ"), _item("b", "600000.SH")],
            source_status="ok",
            fetched_at=datetime.now(UTC),
        )


def test_news_service_fetches_in_one_batch_and_filters_to_user_symbols(tmp_path: Path):
    from app.services.watchlist_news import WatchlistNewsService

    provider = _FakeProvider()
    service = WatchlistNewsService(provider=provider, cache_path=tmp_path / "news.json")
    result = service.get_news(category="public_news", symbols=["000001.SZ"])

    assert [item.symbol for item in result.items] == ["000001.SZ"]
    assert provider.calls == [["000001.SZ"]]


def test_news_preloader_fetches_union_but_writes_highlights_per_user(tmp_path: Path):
    from app.services import watchlist
    from app.services.user_context import current_user
    from app.services.watchlist_news_preloader import WatchlistNewsPreloader

    alice = UserIdentity("alice", "Alice", "phone-alice")
    bob = UserIdentity("bob", "Bob", "phone-bob")

    class _Accounts:
        def list_active_identities(self):
            return [alice, bob]

        def ensure_workspace(self, user_id):
            return tmp_path / "users" / user_id

    for user, symbol in ((alice, "000001.SZ"), (bob, "600000.SH")):
        token = set_current_user(user, tmp_path / "users" / user.id)
        try:
            watchlist.add(symbol)
        finally:
            reset_current_user(token)

    class _UnionProvider(_FakeProvider):
        def get_news(self, category, symbols, **kwargs):
            self.calls.append(symbols)
            return NewsFetchResult(
                items=[_item(symbol, symbol) for symbol in symbols],
                source_status="ok",
                fetched_at=datetime.now(UTC),
            )

    provider = _UnionProvider()
    service = __import__("app.services.watchlist_news", fromlist=["WatchlistNewsService"]).WatchlistNewsService(
        provider=provider,
        cache_path=tmp_path / "news.json",
    )
    preloader = WatchlistNewsPreloader(
        account_store=_Accounts(),
        shared_root=tmp_path,
        service=service,
    )

    assert preloader.run_once() == {"users": 2, "symbols": 2, "written": 2}
    assert current_user() is None
    assert provider.calls == [["000001.SZ", "600000.SH"], ["000001.SZ", "600000.SH"]]

    token = set_current_user(alice, tmp_path / "users" / "alice")
    try:
        assert [item.symbol for item in news_user_store.load_highlights()] == ["000001.SZ"]
    finally:
        reset_current_user(token)
    token = set_current_user(bob, tmp_path / "users" / "bob")
    try:
        assert [item.symbol for item in news_user_store.load_highlights()] == ["600000.SH"]
    finally:
        reset_current_user(token)
