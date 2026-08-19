from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.data_providers.news_contract import NewsItem


def test_news_item_requires_real_title_and_normalizes_utc_timestamp():
    item = NewsItem(
        id="article-1",
        category="public_news",
        symbol="000001.SZ",
        name="平安银行",
        title="  业绩快报  ",
        summary=None,
        content=None,
        url="https://example.test/article-1",
        source="VibePublic",
        published_at="2026-08-18T10:30:00+08:00",
        fetched_at=datetime(2026, 8, 18, 3, 0, tzinfo=UTC),
        data_version="v1",
        generated=False,
        source_ids=["article-1"],
    )

    assert item.title == "业绩快报"
    assert item.published_at == datetime(2026, 8, 18, 2, 30, tzinfo=UTC)


def test_news_item_rejects_empty_title():
    with pytest.raises(ValueError, match="title"):
        NewsItem(
            id="article-1",
            category="announcement",
            title=" ",
            source="VibePublic",
            fetched_at=datetime.now(UTC),
            data_version="v1",
        )
