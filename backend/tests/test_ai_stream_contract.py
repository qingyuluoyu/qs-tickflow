from __future__ import annotations

import asyncio
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


class _HangingStream:
    def __init__(self):
        self.closed = False
        self._never = asyncio.Event()

    def __aiter__(self):
        return self

    async def __anext__(self):
        await self._never.wait()
        raise StopAsyncIteration

    async def aclose(self):
        self.closed = True


class _StallingStream:
    def __init__(self, first):
        self.first = first
        self.closed = False
        self._sent = False
        self._never = asyncio.Event()

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._sent:
            self._sent = True
            return self.first
        await self._never.wait()
        raise StopAsyncIteration

    async def aclose(self):
        self.closed = True


def _chunk(*, content="", reasoning="", finish_reason=None):
    delta = SimpleNamespace(content=content, reasoning=reasoning, reasoning_content=None)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


def _tool_chunk(*, reasoning_content=None, call_id=None, name=None, arguments=None, finish_reason=None):
    function = SimpleNamespace(name=name, arguments=arguments)
    tool_call = SimpleNamespace(index=0, id=call_id, function=function)
    delta = SimpleNamespace(
        content="",
        reasoning=None,
        reasoning_content=reasoning_content,
        tool_calls=[tool_call] if any(value is not None for value in (call_id, name, arguments)) else [],
    )
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


@pytest.mark.asyncio
async def test_tool_stream_preserves_reasoning_content_for_follow_up_round(monkeypatch):
    client, _ = _fake_client([
        [
            _tool_chunk(reasoning_content="需要先查询行情"),
            _tool_chunk(call_id="call_1", name="query_quote"),
            _tool_chunk(arguments='{"code":"600519.SH"}', finish_reason="tool_calls"),
        ],
    ])
    profile = SimpleNamespace(
        provider="openai_compat", api_key="test", model="test-model",
        base_url="https://example.com", user_agent="",
    )
    monkeypatch.setattr(ai_provider, "resolve_current_profile", lambda: profile)
    monkeypatch.setattr(ai_provider, "_openai_client", lambda _profile, _timeout: client)

    events = [event async for event in ai_provider.stream_ai_text_with_tools(
        [{"role": "user", "content": "查行情"}], [{"type": "function"}], max_tokens=100,
    )]

    assert events[-1]["type"] == "round_done"
    assert events[-1]["reasoning_content"] == "需要先查询行情"


@pytest.mark.asyncio
async def test_chat_tool_round_replays_reasoning_content(monkeypatch, tmp_path):
    from app.services import chat

    calls = []

    async def fake_tool_stream(working, _tools, **_kwargs):
        calls.append(working)
        if len(calls) == 1:
            yield {
                "type": "round_done",
                "reasoning_content": "需要先查询行情",
                "tool_calls": [{
                    "id": "call_1",
                    "name": "query_quote",
                    "arguments": '{"code":"600519.SH"}',
                }],
            }
            return
        yield {"type": "delta", "text": "已完成"}
        yield {"type": "round_done", "tool_calls": []}

    monkeypatch.setattr(chat, "stream_ai_text_with_tools", fake_tool_stream)
    monkeypatch.setattr(chat, "exec_tool", lambda *_args, **_kwargs: {"symbol": "600519.SH"})

    events = [event async for event in chat.run_chat_tools_stream(
        None, tmp_path, [{"role": "user", "content": "查行情"}],
    )]

    assert events[-1]["type"] == "done"
    assistant = next(item for item in calls[1] if item.get("role") == "assistant")
    assert assistant["reasoning_content"] == "需要先查询行情"


def test_chat_history_is_bounded_before_provider_request():
    from app.services import chat

    messages = []
    for index in range(8):
        messages.extend([
            {"role": "user", "content": f"问题{index}" + ("u" * 7_990)},
            {"role": "assistant", "content": f"回答{index}" + ("a" * 7_990)},
        ])

    safe = chat._safe_messages(messages)

    assert sum(len(item["content"]) for item in safe) <= chat.MAX_MODEL_HISTORY_CHARS
    assert safe[-1]["content"].startswith("回答7")


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
async def test_stream_ai_events_times_out_when_provider_never_emits_first_chunk(monkeypatch):
    hanging = _HangingStream()
    completions = SimpleNamespace(create=lambda **_kwargs: None)

    async def create(**_kwargs):
        return hanging

    completions.create = create
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    profile = SimpleNamespace(
        provider="openai_compat", api_key="test", model="test-model",
        base_url="https://example.com", user_agent="",
    )
    monkeypatch.setattr(ai_provider, "resolve_current_profile", lambda: profile)
    monkeypatch.setattr(ai_provider, "_openai_client", lambda _profile, _timeout: client)

    with pytest.raises(ai_provider.AiStreamTimeoutError, match="首条响应"):
        [event async for event in ai_provider.stream_ai_events(
            [{"role": "user", "content": "问题"}],
            max_tokens=100,
            first_event_timeout=0.001,
        )]

    assert hanging.closed is True


@pytest.mark.asyncio
async def test_stream_ai_text_times_out_when_provider_stalls_between_chunks(monkeypatch):
    first = _chunk(content="首段")
    hanging = _StallingStream(first)

    async def create(**_kwargs):
        return hanging

    profile = SimpleNamespace(
        provider="openai_compat", api_key="test", model="test-model",
        base_url="https://example.com", user_agent="",
    )
    completions = SimpleNamespace(create=create)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(ai_provider, "resolve_current_profile", lambda: profile)
    monkeypatch.setattr(ai_provider, "_openai_client", lambda _profile, _timeout: client)

    # The provider adapter must expose the bounded inactivity contract to callers.
    with pytest.raises(ai_provider.AiStreamTimeoutError, match="连续响应"):
        [chunk async for chunk in ai_provider._stream_openai(
            [{"role": "user", "content": "问题"}],
            temperature=0.5,
            max_tokens=100,
            timeout=1,
            first_event_timeout=0.01,
            inactivity_timeout=0.001,
        )]

    assert hanging.closed is True


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

    assert [event["type"] for event in events] == ["status", "meta", "reasoning_delta", "delta", "done"]
    assert events[2]["content"] == "思考"
    assert events[3]["content"] == "回答"
    assert events[-1]["truncated"] is False


@pytest.mark.asyncio
async def test_stock_stream_reports_preflight_failure_instead_of_closing_silently(monkeypatch, tmp_path):
    repo = SimpleNamespace(resolve_asset_type=lambda _symbol: "stock")

    def fail_before_ai(_repo, _symbol):
        raise RuntimeError("行情读取失败")

    monkeypatch.setattr(stock_analyzer, "_load_kline", fail_before_ai)
    events = [json.loads(raw) async for raw in stock_analyzer.analyze_stock_stream(
        repo, tmp_path, "000001.SZ",
    )]

    assert [event["type"] for event in events] == ["status", "error"]
    assert "行情读取失败" in events[-1]["message"]
