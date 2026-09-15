from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.backtest import _backtest_end_date_coverage_error, _default_backtest_end_date


class _Repo:
    def __init__(self, latest_by_asset: dict[str, date | None]):
        self.latest_by_asset = latest_by_asset

    def latest_enriched_date(self, asset_type: str) -> date | None:
        return self.latest_by_asset[asset_type]


def test_backtest_coverage_rejects_end_after_stock_enriched_data():
    error = _backtest_end_date_coverage_error(
        _Repo({"stock": date(2026, 9, 14)}),
        asset_type="stock",
        end_date=date(2026, 9, 15),
    )

    assert error == (
        "回测结束日期 2026-09-15 超出股票复权指标数据截止日 2026-09-14；"
        "请先同步并生成指标数据，或将结束日期改为不晚于该日期。"
    )


def test_backtest_coverage_uses_the_requested_asset_type():
    error = _backtest_end_date_coverage_error(
        _Repo({"stock": date(2026, 9, 14), "etf": date(2026, 9, 12)}),
        asset_type="etf",
        end_date=date(2026, 9, 14),
    )

    assert error == (
        "回测结束日期 2026-09-14 超出ETF复权指标数据截止日 2026-09-12；"
        "请先同步并生成指标数据，或将结束日期改为不晚于该日期。"
    )


def test_backtest_coverage_allows_the_latest_enriched_date():
    assert _backtest_end_date_coverage_error(
        _Repo({"stock": date(2026, 9, 14)}),
        asset_type="stock",
        end_date=date(2026, 9, 14),
    ) is None


def test_omitted_backtest_end_defaults_to_the_latest_enriched_date():
    assert _default_backtest_end_date(
        _Repo({"stock": date(2026, 9, 14)}),
        "stock",
    ) == date(2026, 9, 14)


def test_backtest_coverage_reports_missing_enriched_data():
    error = _backtest_end_date_coverage_error(
        _Repo({"stock": None}),
        asset_type="stock",
        end_date=date(2026, 9, 14),
    )

    assert error == "股票复权指标数据尚未生成；请先完成数据同步和指标计算。"


def test_strategy_run_rejects_stale_end_before_starting_a_worker():
    from app.api.backtest import StrategyBacktestRequest, strategy_run

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(repo=_Repo({"stock": date(2026, 9, 14)})))
    )
    req = StrategyBacktestRequest(
        strategy_id="ma_cross",
        start=date(2026, 9, 1),
        end=date(2026, 9, 15),
    )

    with pytest.raises(HTTPException, match="2026-09-14") as exc_info:
        strategy_run(req, request)

    assert exc_info.value.status_code == 422


def test_strategy_stream_reports_stale_end_without_creating_a_job():
    import asyncio

    from app.api import backtest as api

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(repo=_Repo({"stock": date(2026, 9, 14)}))),
        state=SimpleNamespace(),
    )

    async def read_stream() -> str:
        response = await api.strategy_stream(
            request,
            strategy_id="ma_cross",
            start="2026-09-01",
            end="2026-09-15",
        )
        return "".join([chunk async for chunk in response.body_iterator])

    before = set(api._running_jobs)
    body = asyncio.run(read_stream())

    assert "event: error" in body
    assert "2026-09-14" in body
    assert set(api._running_jobs) == before
