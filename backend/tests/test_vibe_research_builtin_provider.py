from __future__ import annotations

from datetime import UTC, datetime

from app.data_providers.vibe_research_provider import VibeResearchProvider


def test_builtin_provider_normalizes_original_vibe_sources(monkeypatch):
    monkeypatch.setattr(
        "app.services.stock_insight.announcements",
        lambda code, limit=15: [
            {
                "date": "2026-08-15",
                "title": f"{code}:半年度报告公告",
                "type": "定期报告",
                "url": f"https://example.test/ann/{code}",
            }
        ],
    )
    monkeypatch.setattr(
        "app.services.stock_insight.stock_news",
        lambda code, limit=20: [
            {
                "新闻标题": f"{code} 业绩新闻",
                "发布时间": "2026-08-15 10:11:51",
                "文章来源": "公开媒体",
                "新闻链接": f"https://example.test/news/{code}",
            }
        ],
    )

    provider = VibeResearchProvider(clock=lambda: datetime(2026, 8, 18, tzinfo=UTC))
    announcements = provider.get_news("announcement", ["600519.SH"])
    news = provider.get_news("public_news", ["600519.SH"])

    assert announcements.source_status == "ok"
    assert announcements.items[0].symbol == "600519.SH"
    assert announcements.items[0].title == "600519:半年度报告公告"
    assert announcements.items[0].summary == "定期报告"
    assert news.items[0].source == "公开媒体"
    assert news.items[0].published_at is not None
    assert news.items[0].published_at.isoformat().startswith("2026-08-15T02:11:51")


def test_builtin_provider_reports_partial_upstream_failure(monkeypatch):
    def fetch(code, limit=15):
        if code == "600519":
            return [{"date": "2026-08-15", "title": "公告", "type": "其他", "url": "u"}]
        raise RuntimeError("source unavailable")

    monkeypatch.setattr("app.services.stock_insight.announcements", fetch)
    provider = VibeResearchProvider(clock=lambda: datetime(2026, 8, 18, tzinfo=UTC))

    result = provider.get_news("announcement", ["600519.SH", "000001.SZ"])

    assert result.source_status == "invalid"
    assert len(result.items) == 1
    assert "000001.SZ" in (result.source_message or "")


def test_builtin_provider_refetches_announcements_when_larger_limit_needs_more_rows(monkeypatch):
    calls = []

    def fetch(code, limit=15):
        calls.append(limit)
        return [
            {"date": "2026-08-15", "title": f"公告-{i}", "type": "其他", "url": f"u-{i}"}
            for i in range(min(limit, 3))
        ]

    monkeypatch.setattr("app.services.stock_insight.announcements", fetch)
    provider = VibeResearchProvider(clock=lambda: datetime(2026, 8, 18, tzinfo=UTC))

    provider.get_news("announcement", ["600519.SH"], limit=20)
    provider.get_news("announcement", ["600519.SH"], limit=100)

    assert calls == [20, 100]
