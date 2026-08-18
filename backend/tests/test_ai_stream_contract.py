from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import polars as pl
import pytest

from app.services import ai_provider, market_recap, stock_analyzer


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for chunk in self._chunks:
            yield chunk


def _chunk(*, content="", reasoning="", finish_reason=None):
    delta = SimpleNamespace(content=content, reasoning=reasoning, reasoning_content=None)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


class _FakeCompletions:
    def __init__(self, streams):
        self.streams = list(streams)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeStream(self.streams.pop(0))


def _fake_client(streams):
    completions = _FakeCompletions(streams)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


def test_report_save_contract_keeps_answer_and_reasoning_fields_optional():
    from app.api.market_recap import SaveReportRequest as ReviewSaveRequest
    from app.api.stock_analysis import SaveReportRequest as StockSaveRequest

    review = ReviewSaveRequest(as_of="2026-08-17", content="回答", reasoning="草稿")
    stock = StockSaveRequest(symbol="000001.SZ", content="回答", reasoning="草稿")

    assert review.reasoning == "草稿"
    assert review.complete is True
    assert stock.reasoning == "草稿"
    assert stock.truncated is False


@pytest.mark.asyncio
async def test_stream_ai_events_separates_reasoning_from_answer(monkeypatch):
    client, _ = _fake_client([
        [_chunk(reasoning="内部草稿"), _chunk(content="真实回答", finish_reason="stop")],
    ])
    profile = SimpleNamespace(provider="openai_compat", api_key="test", model="test-model", base_url="https://example.com", user_agent="")
    monkeypatch.setattr(ai_provider, "resolve_current_profile", lambda: profile)
    monkeypatch.setattr(ai_provider, "_openai_client", lambda _profile, _timeout: client)

    events = [event async for event in ai_provider.stream_ai_events(
        [{"role": "user", "content": "问题"}], max_tokens=100,
    )]

    assert events == [
        {"type": "reasoning_delta", "content": "内部草稿"},
        {"type": "delta", "content": "真实回答"},
        {"type": "done", "complete": True, "truncated": False, "finish_reason": "stop", "continuations": 0},
    ]


@pytest.mark.asyncio
async def test_stream_ai_events_continues_length_stopped_answer(monkeypatch):
    client, completions = _fake_client([
        [_chunk(content="第一段", finish_reason="length")],
        [_chunk(content="第二段", finish_reason="stop")],
    ])
    profile = SimpleNamespace(provider="openai_compat", api_key="test", model="test-model", base_url="https://example.com", user_agent="")
    monkeypatch.setattr(ai_provider, "resolve_current_profile", lambda: profile)
    monkeypatch.setattr(ai_provider, "_openai_client", lambda _profile, _timeout: client)

    events = [event async for event in ai_provider.stream_ai_events(
        [{"role": "user", "content": "问题"}], max_tokens=100, max_continuations=1,
    )]

    assert events[-1] == {
        "type": "done", "complete": True, "truncated": False,
        "finish_reason": "stop", "continuations": 1,
    }
    assert [event for event in events if event["type"] == "delta"] == [
        {"type": "delta", "content": "第一段"},
        {"type": "delta", "content": "第二段"},
    ]
    assert any(event["type"] == "continuation" for event in events)
    assert completions.calls[1]["messages"][-2:] == [
        {"role": "assistant", "content": "第一段"},
        {"role": "user", "content": "请从上一个回答末尾继续，只输出尚未完成的内容，不要重复已有内容。"},  # noqa: RUF001
    ]


@pytest.mark.asyncio
async def test_stream_ai_events_marks_bounded_exhaustion_as_incomplete(monkeypatch):
    client, _ = _fake_client([
        [_chunk(content="未完成", finish_reason="length")],
    ])
    profile = SimpleNamespace(provider="openai_compat", api_key="test", model="test-model", base_url="https://example.com", user_agent="")
    monkeypatch.setattr(ai_provider, "resolve_current_profile", lambda: profile)
    monkeypatch.setattr(ai_provider, "_openai_client", lambda _profile, _timeout: client)

    events = [event async for event in ai_provider.stream_ai_events(
        [{"role": "user", "content": "问题"}], max_tokens=100, max_continuations=0,
    )]

    assert events[-1] == {
        "type": "done", "complete": False, "truncated": True,
        "finish_reason": "length", "continuations": 0,
    }


async def _fake_structured_events(*_args, **_kwargs):
    yield {"type": "reasoning_delta", "content": "思考"}
    yield {"type": "delta", "content": "回答"}
    yield {"type": "done", "complete": True, "truncated": False, "finish_reason": "stop", "continuations": 0}


@pytest.mark.asyncio
async def test_review_stream_keeps_reasoning_separate(monkeypatch):
    overview = {
        "as_of": "2026-08-17",
        "emotion": {"score": 60, "label": "偏暖"},
        "indices": [],
        "limit": {},
        "amount": {},
    }
    monkeypatch.setattr(market_recap, "build_market_overview", lambda *_args, **_kwargs: overview)
    monkeypatch.setattr(ai_provider, "stream_ai_events", _fake_structured_events)

    events = [json.loads(raw) async for raw in market_recap.recap_market_stream(object())]

    assert [event["type"] for event in events] == ["meta", "reasoning_delta", "delta", "done"]
    assert events[1]["content"] == "思考"
    assert events[2]["content"] == "回答"
    assert events[-1]["complete"] is True


@pytest.mark.asyncio
async def test_stock_stream_keeps_reasoning_separate(monkeypatch, tmp_path):
    df = pl.DataFrame({
        "date": [date(2026, 8, 17)],
        "close": [10.0],
    })
    repo = SimpleNamespace(resolve_asset_type=lambda _symbol: "stock")
    monkeypatch.setattr(stock_analyzer, "_load_kline", lambda _repo, _symbol: df)
    monkeypatch.setattr(stock_analyzer, "compute_levels", lambda _df: {})
    monkeypatch.setattr(stock_analyzer, "summarize_levels", lambda _levels, _close: "价位摘要")
    monkeypatch.setattr(stock_analyzer, "_load_financials", lambda _data_dir, _symbol: {})
    monkeypatch.setattr(ai_provider, "stream_ai_events", _fake_structured_events)

    events = [json.loads(raw) async for raw in stock_analyzer.analyze_stock_stream(repo, tmp_path, "000001.SZ")]

    assert [event["type"] for event in events] == ["meta", "reasoning_delta", "delta", "done"]
    assert events[1]["content"] == "思考"
    assert events[2]["content"] == "回答"
    assert events[-1]["truncated"] is False
