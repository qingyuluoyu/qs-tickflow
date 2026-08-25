from __future__ import annotations

from pathlib import Path

from app.strategy.engine import StrategyEngine

BUILTIN_DIR = Path(__file__).resolve().parents[1] / "app" / "strategy" / "builtin"


def _defaults(engine: StrategyEngine, strategy_id: str) -> dict:
    strategy = engine.get(strategy_id)
    return {item["id"]: item.get("default") for item in strategy.meta.get("params", [])}


def test_retired_backtests_are_hidden_without_removing_legacy_definitions():
    engine = StrategyEngine(strategy_dirs=[BUILTIN_DIR])

    visible_ids = {item["id"] for item in engine.list_strategies()}
    retired_ids = {
        "boll_breakout",
        "consecutive_limit_ups",
        "hot_money_breakout",
        "macd_golden",
        "near_limit_up",
        "pullback_to_support",
        "relative_strength_pullback",
    }
    required_ids = {
        "qingshu_one",
        "pullback_ma20_bounce",
        "trend_breakout",
        "oversold_bounce",
        "ma_golden_cross",
        "volume_price_surge",
        "bullish_alignment",
        "limit_up_momentum",
        "martingale_capped",
    }

    assert retired_ids.isdisjoint(visible_ids)
    assert required_ids <= visible_ids
    # Source definitions remain addressable for old composites and saved results.
    for strategy_id in retired_ids:
        assert engine.get(strategy_id).meta["status"] == "retired"


def test_requested_strategies_use_conservative_optimized_defaults():
    engine = StrategyEngine(strategy_dirs=[BUILTIN_DIR])

    assert engine.get("qingshu_one").stop_loss == -0.04
    pullback_defaults = _defaults(engine, "pullback_ma20_bounce")
    assert pullback_defaults["ma_proximity"] == 2.0
    assert pullback_defaults["require_ma_alignment"] is True
    assert pullback_defaults["require_positive_change"] is True
    assert engine.get("pullback_ma20_bounce").stop_loss == -0.06

    assert _defaults(engine, "trend_breakout")["vol_ratio_min"] == 1.2
    assert engine.get("trend_breakout").stop_loss == -0.03

    oversold_defaults = _defaults(engine, "oversold_bounce")
    assert oversold_defaults["rsi_max"] == 25.0
    assert oversold_defaults["vol_ratio_min"] == 1.5

    ma_defaults = _defaults(engine, "ma_golden_cross")
    assert ma_defaults["vol_ratio_min"] == 2.0
    assert ma_defaults["require_ma_golden"] is True
    assert engine.get("ma_golden_cross").stop_loss == -0.03

    assert engine.get("volume_price_surge").stop_loss == -0.03
