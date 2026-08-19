from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import ai_provider, stock_debate


def test_stage_plan_is_bounded_and_matches_archive_flow():
    assert stock_debate.stage_plan(1) == ["bull", "bear", "referee"]
    assert stock_debate.stage_plan(2) == ["bull", "bear", "bull_rebut", "bear_rebut", "referee"]
    assert stock_debate.stage_plan(99) == stock_debate.stage_plan(2)


def test_payload_empty_ignores_metadata_but_keeps_observations():
    assert stock_debate.payload_empty({"period": "近5年", "metrics": {}})
    assert not stock_debate.payload_empty({"period": "近5年", "metrics": {"pe_ttm": 18.2}})
    assert stock_debate.payload_empty({"code": "000001", "rows": []})


def test_build_dossier_marks_required_gaps_and_optional_no_record():
    fetchers = {
        "quote": lambda: {"close": 12.34, "change_pct": 1.2},
        "valuation": lambda: {"period": "近5年", "metrics": {}},
        "financials": lambda: {"roe": 11.2},
        "kline": lambda: [{"date": "2026-08-18", "close": 12.34}],
        "fund_flow": lambda: {"rows": []},
        "announcements": lambda: [],
        "reports": lambda: [],
        "news": lambda: [{"title": "公开信息"}],
    }

    dossier, progress = stock_debate.build_dossier("000001.SZ", fetchers)

    assert len(progress) == len(stock_debate.DOSSIER_SPECS)
    assert "估值与历史分位" in dossier["missing"]
    assert "资金流向" in dossier["missing"]
    assert "近期公告" not in dossier["missing"]
    assert "近期研报" not in dossier["missing"]
    assert any(section["title"] == "近期公告" and isinstance(section["data"], str)
               for section in dossier["sections"])
    assert dossier["code"] == "000001.SZ"


@pytest.mark.asyncio
async def test_stock_analysis_debate_api_keeps_symbol_and_round_contract(monkeypatch):
    from app.api.stock_analysis import DebateRequest, debate_stock

    async def fake_stream(*_args):
        yield {"type": "done", "code": "000001.SZ", "stages": []}

    monkeypatch.setattr("app.api.stock_analysis.stock_debate.run_debate_stream", fake_stream)
    repo = SimpleNamespace(store=SimpleNamespace(data_dir="data"))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(repo=repo)))

    response = await debate_stock(request, DebateRequest(symbol="000001.sz", rounds=1))
    chunks = [chunk async for chunk in response.body_iterator]
    assert response.media_type == "application/x-ndjson"
    assert '"code": "000001.SZ"' in chunks[0]

    with pytest.raises(HTTPException, match="symbol 格式"):
        await debate_stock(request, DebateRequest(symbol="000001", rounds=1))
    with pytest.raises(HTTPException, match="rounds"):
        await debate_stock(request, DebateRequest(symbol="000001.SZ", rounds=3))


@pytest.mark.asyncio
async def test_run_stream_has_dossier_then_three_stages(monkeypatch):
    fetchers = {
        key: (lambda key=key: {"value": key}) for key, *_ in stock_debate.DOSSIER_SPECS
    }
    monkeypatch.setattr(stock_debate, "_default_fetchers", lambda *_args: fetchers)
    monkeypatch.setattr(ai_provider, "ai_configured", lambda: True)

    async def fake_stream(*_args, **_kwargs):
        yield {"type": "delta", "content": "阶段回答"}
        yield {"type": "done", "complete": True, "truncated": False}

    monkeypatch.setattr(ai_provider, "stream_ai_events", fake_stream)

    events = [event async for event in stock_debate.run_debate_stream(
        repo=object(), data_dir=None, symbol="000001.SZ", rounds=1,
    )]

    assert events[0]["type"] == "status"
    assert events[1]["type"] == "dossier_progress"
    assert any(event["type"] == "dossier" for event in events)
    assert [event["stage"] for event in events if event["type"] == "stage"] == [
        "bull", "bear", "referee",
    ]
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_run_stream_uses_answer_events_without_leaking_reasoning(monkeypatch):
    fetchers = {
        key: (lambda key=key: {"value": key}) for key, *_ in stock_debate.DOSSIER_SPECS
    }
    monkeypatch.setattr(stock_debate, "_default_fetchers", lambda *_args: fetchers)
    monkeypatch.setattr(ai_provider, "ai_configured", lambda: True)

    async def structured_events(*_args, **_kwargs):
        yield {"type": "reasoning_delta", "content": "内部思考不应展示"}
        yield {"type": "delta", "content": "多方可展示回答"}
        yield {"type": "done", "complete": True, "truncated": False}

    monkeypatch.setattr(ai_provider, "stream_ai_events", structured_events)

    events = [event async for event in stock_debate.run_debate_stream(
        repo=object(), data_dir=None, symbol="000001.SZ", rounds=1,
    )]

    bull_deltas = [event["text"] for event in events
                   if event["type"] == "delta" and event["stage"] == "bull"]
    assert bull_deltas == ["多方可展示回答"]


@pytest.mark.asyncio
async def test_run_stream_marks_empty_stage_as_failed(monkeypatch):
    fetchers = {
        key: (lambda key=key: {"value": key}) for key, *_ in stock_debate.DOSSIER_SPECS
    }
    monkeypatch.setattr(stock_debate, "_default_fetchers", lambda *_args: fetchers)
    monkeypatch.setattr(ai_provider, "ai_configured", lambda: True)

    async def empty_events(*_args, **_kwargs):
        yield {"type": "done", "complete": True, "truncated": False}

    monkeypatch.setattr(ai_provider, "stream_ai_events", empty_events)

    events = [event async for event in stock_debate.run_debate_stream(
        repo=object(), data_dir=None, symbol="000001.SZ", rounds=1,
    )]

    assert any(
        event["type"] == "error" and event["stage"] == "bull"
        for event in events
    )
    bull_done = next(event for event in events
                     if event["type"] == "stage_done" and event["stage"] == "bull")
    assert bull_done["failed"] is True
    done = next(event for event in events if event["type"] == "done")
    assert done["failed_stages"] == ["bull", "bear", "referee"]


@pytest.mark.asyncio
async def test_dossier_stream_reports_first_section_before_fetching_next():
    def must_not_run_yet():
        raise AssertionError("第二个数据源不应在第一条进度之前执行")

    fetchers = {
        "quote": lambda: {"close": 12.34},
        "valuation": must_not_run_yet,
    }

    stream = stock_debate.collect_dossier_stream("000001.SZ", fetchers)
    first = await anext(stream)
    await stream.aclose()

    assert first["type"] == "dossier_progress"
    assert first["title"] == "实时行情"
    assert first["loaded"] == 1


@pytest.mark.asyncio
async def test_dossier_stream_turns_slow_source_into_a_gap():
    def slow_quote():
        time.sleep(0.05)
        return {"close": 12.34}

    stream = stock_debate.collect_dossier_stream(
        "000001.SZ",
        {"quote": slow_quote, "valuation": lambda: {"pe": 12.0}},
        timeout_s=0.001,
    )
    first = await anext(stream)
    await stream.aclose()

    assert first["type"] == "dossier_progress"
    assert first["title"] == "实时行情"
    assert first["ok"] is False
