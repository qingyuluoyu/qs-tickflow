from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_financial_analysis_propagates_incomplete_provider_completion(monkeypatch, tmp_path):
    from app.services import ai_provider, financial_analyzer

    monkeypatch.setattr(
        financial_analyzer,
        "_load_stock_financials",
        lambda _data_dir, _symbol: {"metrics": [{"period_end": "20250630", "roe": 12.0}]},
    )

    async def fake_events(*_args, **_kwargs):
        yield {"type": "delta", "content": "只生成了一半"}
        yield {
            "type": "done",
            "complete": False,
            "truncated": True,
            "finish_reason": "length",
            "continuations": 0,
        }

    monkeypatch.setattr(ai_provider, "stream_ai_events", fake_events)

    events = [
        json.loads(raw)
        async for raw in financial_analyzer.analyze_financials_stream(
            tmp_path, "000001.SZ",
        )
    ]

    assert events[-1]["type"] == "done"
    assert events[-1]["complete"] is False
    assert events[-1]["truncated"] is True
    assert events[-1]["finish_reason"] == "length"


@pytest.mark.asyncio
async def test_chat_marks_length_stopped_tool_round_as_incomplete(monkeypatch, tmp_path):
    from app.services import chat

    async def fake_tool_stream(*_args, **_kwargs):
        yield {
            "type": "round_done",
            "tool_calls": [],
            "finish_reason": "length",
        }

    monkeypatch.setattr(chat, "stream_ai_text_with_tools", fake_tool_stream)

    events = [
        event
        async for event in chat.run_chat_tools_stream(
            None, tmp_path, [{"role": "user", "content": "请分析"}],
        )
    ]

    assert events[-1]["type"] == "done"
    assert events[-1]["complete"] is False
    assert events[-1]["truncated"] is True
    assert events[-1]["finish_reason"] == "length"
