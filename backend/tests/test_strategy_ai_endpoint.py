from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_ai_test_does_not_report_success_for_an_empty_completion(monkeypatch):
    from app.api import strategy
    from app.services import ai_provider

    received: dict = {}

    async def fake_generate(*_args, **kwargs):
        received.update(kwargs)
        return ""

    monkeypatch.setattr(ai_provider, "generate_ai_text", fake_generate)
    monkeypatch.setattr(ai_provider, "current_ai_model", lambda: "test-model")
    monkeypatch.setattr(ai_provider, "current_ai_provider", lambda: "openai_compat")

    result = await strategy.ai_test(None)

    assert received["disable_thinking"] is True
    assert result["ok"] is False
    assert result["error"] == "AI 服务未返回可用正文，请稍后重试"  # noqa: RUF001
    assert result["error_type"] == "EmptyAiResponse"
