"""概念/行业轮动 AI 分析流回归测试。"""

from __future__ import annotations

import json

import pytest

from app.services import ai_provider, market_overview_builder, rps_rotation
from app.services import concept_rotation_analyzer as analyzer

DATES = [
    "2026-08-14",
    "2026-08-13",
    "2026-08-12",
    "2026-08-11",
    "2026-08-10",
    "2026-08-07",
    "2026-08-06",
]
ROTATION = {
    "dates": DATES,
    "columns": {day: [["人工智能", 0.05], ["机器人", 0.03]] for day in DATES},
    "concept_count": 2,
}


async def _fake_ai_stream(*_args, **_kwargs):
    yield "客观轮动报告"


@pytest.mark.asyncio
async def test_analyze_rotation_stream_emits_meta_delta_and_done(monkeypatch):
    monkeypatch.setattr(rps_rotation, "build_rps_rotation", lambda *_args, **_kwargs: ROTATION)
    monkeypatch.setattr(market_overview_builder, "build_market_overview", lambda *_args: {})
    monkeypatch.setattr(ai_provider, "ai_configured", lambda: True)
    monkeypatch.setattr(ai_provider, "stream_ai_text", _fake_ai_stream)

    events = [
        json.loads(event)
        async for event in analyzer.analyze_rotation_stream(object(), days=12)
    ]

    assert [event["type"] for event in events] == ["status", "meta", "delta", "done"]
    assert events[2]["content"] == "客观轮动报告"


@pytest.mark.asyncio
async def test_analyze_rotation_stream_continues_when_market_overview_fails(monkeypatch):
    monkeypatch.setattr(rps_rotation, "build_rps_rotation", lambda *_args, **_kwargs: ROTATION)

    def _raise_overview(*_args):
        raise RuntimeError("overview unavailable")

    monkeypatch.setattr(market_overview_builder, "build_market_overview", _raise_overview)
    monkeypatch.setattr(ai_provider, "ai_configured", lambda: True)
    monkeypatch.setattr(ai_provider, "stream_ai_text", _fake_ai_stream)

    events = [
        json.loads(event)
        async for event in analyzer.analyze_rotation_stream(object(), days=12)
    ]

    assert [event["type"] for event in events] == ["status", "meta", "delta", "done"]


@pytest.mark.asyncio
async def test_analyze_rotation_stream_returns_error_when_rotation_build_fails(monkeypatch):
    def _raise_rotation(*_args):
        raise RuntimeError("rotation matrix unavailable")

    monkeypatch.setattr(rps_rotation, "build_rps_rotation", _raise_rotation)

    events = [
        json.loads(event)
        async for event in analyzer.analyze_rotation_stream(object(), days=12)
    ]

    assert events[0]["type"] == "status"
    assert events[0]["message"] == "正在准备概念轮动数据…"
    assert len(events[0]["padding"]) == 2048
    assert events[1] == {
        "type": "error",
        "message": "概念轮动数据生成失败,请稍后重试",
    }
