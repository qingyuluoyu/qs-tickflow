from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from app.strategy.engine import StrategyDataContext, StrategyEngine

BUILTIN_DIR = Path(__file__).resolve().parents[1] / "app" / "strategy" / "builtin"


def test_qingshu_one_is_pinned_first_of_nineteen_builtin_strategies():
    engine = StrategyEngine(strategy_dirs=[BUILTIN_DIR])

    assert engine.load_errors() == []
    strategies = engine.list_strategies()
    assert len(strategies) == 19
    # 清数一号是旗舰策略, 列表默认置顶
    assert strategies[0]["id"] == "qingshu_one"
    strategy = engine.get("qingshu_one")
    assert strategy.meta["name"] == "清数一号"
    assert strategy.source == "builtin"
    assert strategy.execution_backend == "python_history_legacy"
    assert strategy.lookback_days >= 130
    assert engine.required_history_bars(["qingshu_one"]) == 130
    assert {param["id"] for param in strategy.meta["params"]}.isdisjoint({
        "roe_min_pct", "required_annual_roe_years", "institution_holder_min_count",
    })


def test_qingshu_one_keeps_hitting_candidates_without_extreme_fundamental_filters():
    engine = StrategyEngine(strategy_dirs=[BUILTIN_DIR])
    as_of = date(2026, 8, 17)
    rows = []
    for offset in range(380):
        day = as_of - timedelta(days=379 - offset)
        rows.append(
            {
                "symbol": "000001.SZ",
                "date": day,
                "open": 10.0,
                "high": 10.2,
                "low": 9.8,
                "close": 10.1,
                "raw_close": 10.1,
                "raw_high": 10.2,
                "raw_low": 9.8,
                "volume": 300.0 if offset >= 357 else 100.0,
                "amount": 100000.0,
                "total_shares": 20_000_000_000.0,
                "signal_limit_up": True,
            }
        )
    panel = pl.DataFrame(rows)
    result = engine.run(
        "qingshu_one",
        StrategyDataContext(
            asset_type="stock",
            timeframe="1d",
            as_of=as_of,
            current=panel.filter(pl.col("date") == as_of),
            history=panel,
        ),
    )

    assert result.total == 1
    assert result.rows[0]["symbol"] == "000001.SZ"


def test_qingshu_one_uses_six_selected_rules_and_accepts_four_matches():
    engine = StrategyEngine(strategy_dirs=[BUILTIN_DIR])
    strategy = engine.get("qingshu_one")
    params = {param["id"]: param for param in strategy.meta["params"]}
    assert params["recent_limit_up_min_count"]["default"] == 3
    assert params["min_rule_matches"]["default"] == 4
    assert params["min_rule_matches"]["max"] == 6
    as_of = date(2026, 8, 17)
    rows = []
    for offset in range(380):
        day = as_of - timedelta(days=379 - offset)
        is_target_day = offset == 379
        rows.append(
            {
                "symbol": "000001.SZ",
                "date": day,
                "open": 10.0,
                "high": 10.2,
                "low": 9.8,
                "close": 10.1,
                "raw_close": 10.1,
                "raw_high": 10.2,
                "raw_low": 9.8,
                "volume": 100.0,
                "amount": 100000.0,
                "total_shares": 20_000_000_000.0,
                # 全程未放量且目标日不涨停,使“连续放量”和“当日触发”两项
                # 不满足;保留的六项中其余四项满足。
                "signal_limit_up": not is_target_day,
            }
        )
    panel = pl.DataFrame(rows)

    result = engine.run(
        "qingshu_one",
        StrategyDataContext(
            asset_type="stock",
            timeframe="1d",
            as_of=as_of,
            current=panel.filter(pl.col("date") == as_of),
            history=panel,
        ),
    )

    assert result.total == 1
    assert result.rows[0]["qingshu_rule_matches"] == 4
    assert result.rows[0]["qingshu_status"] == "qualified"


def test_qingshu_one_returns_candidate_with_complete_point_in_time_inputs():
    engine = StrategyEngine(strategy_dirs=[BUILTIN_DIR])
    as_of = date(2026, 8, 17)
    rows = []
    for offset in range(380):
        day = as_of - timedelta(days=379 - offset)
        close = 10.0 + offset * 0.01
        rows.append(
            {
                "symbol": "000001.SZ",
                "name": "测试股票",
                "date": day,
                "open": close - 0.1,
                "high": close + 0.1,
                "low": close - 0.1,
                "close": close,
                "volume": 300.0 if offset >= 357 else 100.0,
                "amount": 100000.0,
                "total_shares": 20_000_000_000.0,
                "signal_limit_up": True,
                "qingshu_roe_complete_years": 5,
                "qingshu_roe_min_pct": 12.0,
                "qingshu_institution_holder_count": 5,
                "change_pct": 0.01,
                "vol_ratio_5d": 2.0,
                "momentum_20d": 0.1,
            }
        )
    panel = pl.DataFrame(rows)
    result = engine.run(
        "qingshu_one",
        StrategyDataContext(
            asset_type="stock",
            timeframe="1d",
            as_of=as_of,
            current=panel.filter(pl.col("date") == as_of),
            history=panel,
        ),
    )

    assert result.total == 1
    assert result.rows[0]["symbol"] == "000001.SZ"
    assert result.rows[0]["qingshu_candidate_qualified"] is True
    assert result.rows[0]["qingshu_status"] == "triggered"


def test_qingshu_one_declares_historical_share_dependency_for_backtests():
    engine = StrategyEngine(strategy_dirs=[BUILTIN_DIR])

    assert "total_shares" in engine.get("qingshu_one").required_features
