from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from app.data_providers import news_registry
from app.data_providers.vibe_public_config import config_from_dict
from app.data_providers.vibe_public_provider import (
    NewsProviderError,
    VibePublicProvider,
)


def _config():
    return config_from_dict(
        {
            "name": "vibe_public",
            "display_name": "Vibe 资讯",
            "enabled": True,
            "datasets": {
                "public_news": {
                    "url": "https://news.example.test/articles",
                    "method": "POST",
                    "response_path": "payload.items",
                    "field_map": {
                        "article_id": "id",
                        "ticker": "symbol",
                        "headline": "title",
                        "abstract": "summary",
                        "published": "published_at",
                        "link": "url",
                        "publisher": "source",
                    },
                    "symbols_body_path": "filters.symbols",
                    "start_body_path": "filters.start",
                    "end_body_path": "filters.end",
                    "query_body_path": "filters.query",
                    "limit_body_path": "filters.limit",
                },
            },
        }
    )


def test_provider_batches_symbols_and_normalizes_vibe_public_fields():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.method == "POST"
        body = request.read()
        assert b"000001.SZ" in body and b"600000.SH" in body
        return httpx.Response(
            200,
            json={
                "payload": {
                    "items": [
                        {
                            "article_id": "a-1",
                            "ticker": "000001.SZ",
                            "headline": "平安银行公告",
                            "abstract": "摘要",
                            "published": "2026-08-18T10:30:00+08:00",
                            "link": "https://news.example.test/a-1",
                            "publisher": "VibePublic",
                        }
                    ]
                }
            },
        )

    provider = VibePublicProvider(_config(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        result = provider.get_news(
            category="public_news",
            symbols=["000001.SZ", "600000.SH"],
            start_time=datetime(2026, 8, 17),
            end_time=datetime(2026, 8, 18),
            query="公告",
            limit=30,
        )
    finally:
        provider.close()

    assert len(seen) == 1
    assert result.source_status == "ok"
    assert result.items[0].id == "a-1"
    assert result.items[0].symbol == "000001.SZ"
    assert result.items[0].title == "平安银行公告"
    assert result.items[0].published_at is not None


def test_provider_returns_empty_without_calling_upstream_for_empty_symbols():
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    provider = VibePublicProvider(_config(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        result = provider.get_news(category="public_news", symbols=[])
    finally:
        provider.close()

    assert called is False
    assert result.items == []
    assert result.source_status == "empty"


def test_provider_does_not_fallback_when_upstream_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "offline"})

    provider = VibePublicProvider(_config(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        with pytest.raises(NewsProviderError, match="unavailable"):
            provider.get_news(category="public_news", symbols=["000001.SZ"])
    finally:
        provider.close()


def test_registry_uses_the_original_vibe_public_source_when_config_is_missing(tmp_path):
    news_registry.load(tmp_path / "missing-vibe-public.yaml")

    provider = news_registry.get_provider()
    assert provider is not None
    assert provider.name == "vibe_research"
    assert provider.capabilities.news is True
    assert news_registry.errors() == []


def test_registry_respects_an_explicit_disabled_config(tmp_path):
    path = tmp_path / "vibe-public.yaml"
    path.write_text("enabled: false\n", encoding="utf-8")

    news_registry.load(path)

    assert news_registry.get_provider() is None
    assert news_registry.errors() == []
