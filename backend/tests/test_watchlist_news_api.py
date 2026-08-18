from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import watchlist_news as api
from app.data_providers.news_contract import NewsFetchResult, NewsItem


def _request(service):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(watchlist_news_service=service)))


def _item(symbol: str) -> NewsItem:
    return NewsItem(
        id="article-1",
        category="public_news",
        symbol=symbol,
        title="测试资讯",
        source="VibePublic",
        published_at=datetime.now(UTC),
        fetched_at=datetime.now(UTC),
        data_version="v1",
        source_ids=["article-1"],
    )


class _Service:
    def __init__(self):
        self.calls = []

    def get_news(self, **kwargs):
        self.calls.append(kwargs)
        return NewsFetchResult(
            items=[_item(kwargs["symbols"][0])] if kwargs["symbols"] else [],
            source_status="ok" if kwargs["symbols"] else "empty",
            fetched_at=datetime.now(UTC),
        )

    def get_item(self, **kwargs):
        return _item(kwargs["symbols"][0]) if kwargs["symbols"] else None


def test_list_news_passes_only_current_watchlist_symbols(monkeypatch):
    service = _Service()
    monkeypatch.setattr(api.watchlist, "list_symbols", lambda: [{"symbol": "000001.SZ"}])

    response = api.list_news(
        _request(service),
        category="public_news",
        symbol="000001.SZ",
        q="银行",
        limit=20,
    )

    assert response.watchlist_count == 1
    assert service.calls[0]["symbols"] == ["000001.SZ"]
    assert response.items[0].symbol == "000001.SZ"


def test_list_news_rejects_a_symbol_outside_current_watchlist(monkeypatch):
    service = _Service()
    monkeypatch.setattr(api.watchlist, "list_symbols", lambda: [{"symbol": "000001.SZ"}])

    with pytest.raises(HTTPException) as error:
        api.list_news(_request(service), category="public_news", symbol="600000.SH")

    assert error.value.status_code == 403


def test_detail_uses_authenticated_watchlist_scope(monkeypatch):
    service = _Service()
    monkeypatch.setattr(api.watchlist, "list_symbols", lambda: [{"symbol": "000001.SZ"}])

    item = api.news_detail("article-1", _request(service), category="public_news")

    assert item.symbol == "000001.SZ"


def test_list_news_enriches_source_items_with_current_instrument_name(monkeypatch):
    service = _Service()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                watchlist_news_service=service,
                repo=SimpleNamespace(get_name_map=lambda symbols: {"000001.SZ": "平安银行"}),
            )
        )
    )
    monkeypatch.setattr(api.watchlist, "list_symbols", lambda: [{"symbol": "000001.SZ"}])

    response = api.list_news(request, category="public_news", symbol=None, q=None, limit=30, cursor=None)

    assert response.items[0].name == "平安银行"
