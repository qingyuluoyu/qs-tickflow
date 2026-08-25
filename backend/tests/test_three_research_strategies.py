from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from app.strategy.engine import StrategyEngine

BUILTIN_DIR = Path(__file__).resolve().parents[1] / "app" / "strategy" / "builtin"
NEW_IDS = {"squeeze_breakout", "relative_strength_pullback", "risk_capped_reversal"}


def test_three_research_strategies_are_registered_and_matrix_native():
    engine = StrategyEngine(strategy_dirs=[BUILTIN_DIR])
    defs = {item.meta["id"]: item for item in engine.strategy_definitions()}

    assert set(defs) >= NEW_IDS
    assert all(defs[strategy_id].execution_backend == "matrix_native" for strategy_id in NEW_IDS)


def test_three_research_strategies_compute_binary_signals_on_daily_matrix():
    rows = []
    for i in range(90):
        close = 20.0 + i * 0.05 + (0.4 if i % 7 == 0 else 0.0)
        rows.append({
            "symbol": "000001.SZ",
            "name": "测试",
            "date": date(2026, 1, 1) + timedelta(days=i),
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 100_000.0,
            "signal_limit_up": False,
            "signal_limit_down": False,
        })
    market = build_market_data_matrix(pl.DataFrame(rows))
    engine = StrategyEngine(strategy_dirs=[BUILTIN_DIR])

    for strategy_id in NEW_IDS:
        definition = engine.get(strategy_id)
        signals = definition.matrix_strategy.compute_signals(market, {})
        assert signals.entry.shape == market.shape
        assert signals.exit.shape == market.shape
        assert set(signals.entry.astype(int).ravel()) <= {0, 1}
        assert set(signals.exit.astype(int).ravel()) <= {0, 1}


def test_risk_capped_reversal_explicitly_disclaims_unbounded_martingale():
    engine = StrategyEngine(strategy_dirs=[BUILTIN_DIR])
    definition = engine.get("risk_capped_reversal")

    assert "不是无限加仓马丁格尔" in definition.meta["risk_note"]
