from datetime import date, timedelta
from pathlib import Path

import polars as pl

from app.backtest.matrix import build_market_data_matrix, matrix_feature
from app.strategy.engine import StrategyEngine

BUILTIN_DIR = Path(__file__).resolve().parents[1] / "app" / "strategy" / "builtin"


def _panel() -> pl.DataFrame:
    dates = [date(2026, 7, 1) + timedelta(days=index) for index in range(70)]
    close = [10.0 + index * 0.01 for index in range(70)]
    close[-3:] = [10.50, 11.55, 12.05]
    open_ = [value * 0.995 for value in close]
    open_[-1] = 11.70
    volume = [1000.0] * 70
    volume[-3:] = [1000.0, 1800.0, 2400.0]
    boards = [0] * 70
    boards[-2] = 1
    return pl.DataFrame(
        {
            "symbol": ["600001.SH"] * len(dates),
            "name": ["示例股票"] * len(dates),
            "date": dates,
            "open": open_,
            "high": [max(o, c) for o, c in zip(open_, close, strict=True)],
            "low": [min(o, c) for o, c in zip(open_, close, strict=True)],
            "close": close,
            "volume": volume,
            "consecutive_limit_ups": boards,
        }
    )


def test_hot_money_strategies_are_registered_without_load_errors():
    engine = StrategyEngine([BUILTIN_DIR])
    assert engine.load_errors() == []
    for strategy_id in ("hot_money_breakout", "limit_up_reclaim", "dragon_pullback"):
        strategy = engine.get(strategy_id)
        assert strategy.execution_backend == "matrix_native"
        assert strategy.meta["asset_types"] == ["stock"]


def test_hot_money_matrix_signals_use_supported_fields():
    engine = StrategyEngine([BUILTIN_DIR])
    market = build_market_data_matrix(
        _panel(),
        field_columns={
            "consecutive_limit_ups",
            "price_limit_pct",
            "raw_close",
        },
    )
    for strategy_id in ("hot_money_breakout", "limit_up_reclaim", "dragon_pullback"):
        strategy = engine.get(strategy_id)
        signals = strategy.matrix_strategy.compute_signals(
            market,
            StrategyEngine.resolve_params(strategy),
        )
        assert signals.entry.shape == market.shape
        assert signals.exit.shape == market.shape


def test_raw_change_pct_uses_unadjusted_close_for_limit_rules():
    panel = _panel().with_columns(
        pl.when(pl.col("date") == date(2026, 9, 8))
        .then(pl.lit(11.55))
        .otherwise(pl.col("close"))
        .alias("raw_close")
    )
    market = build_market_data_matrix(panel, field_columns={"raw_close"})
    raw_change = matrix_feature(market, "raw_change_pct")
    assert raw_change[-1, 0] == 0.0
