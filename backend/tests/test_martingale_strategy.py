from pathlib import Path

import pytest
from pydantic import ValidationError

from app.api.backtest import StrategyBacktestRequest
from app.backtest.engine import normalize_martingale_parameters
from app.backtest.strategy import StrategyBacktestConfig, StrategyBacktestService
from app.strategy.engine import StrategyEngine

BUILTIN_DIR = Path(__file__).resolve().parents[1] / "app" / "strategy" / "builtin"


def test_capped_martingale_strategy_is_registered_with_explicit_risk_contract():
    engine = StrategyEngine(strategy_dirs=[BUILTIN_DIR])

    strategy = engine.get("martingale_capped")
    assert strategy.meta["position_sizing"] == "martingale_capped"
    assert strategy.meta["research_only"] is True
    assert "无限补仓" in strategy.meta["risk_note"]
    assert strategy.entry_signals == ["signal_martingale_reversal"]


def test_capped_martingale_parameters_are_bounded():
    engine = StrategyEngine(strategy_dirs=[BUILTIN_DIR])
    params = {item["id"]: item for item in engine.get("martingale_capped").meta["params"]}

    assert params["base_position_pct"]["default"] == 0.1
    assert params["base_position_pct"]["max"] <= 0.5
    assert params["multiplier"]["default"] == 2.0
    assert params["max_levels"]["default"] == 2


def test_backtest_result_config_records_effective_martingale_parameters():
    config = StrategyBacktestConfig(
        strategy_id="martingale_capped",
        symbols=None,
        start=__import__("datetime").date(2026, 1, 1),
        end=__import__("datetime").date(2026, 1, 10),
    )

    result_config = StrategyBacktestService._config_to_dict(
        config,
        effective_position_sizing="martingale_capped",
        effective_martingale_base_pct=0.1,
        effective_martingale_multiplier=2.0,
        effective_martingale_max_level=2,
    )

    assert result_config["position_sizing"] == "martingale_capped"
    assert result_config["martingale_base_pct"] == 0.1
    assert result_config["martingale_multiplier"] == 2.0
    assert result_config["martingale_max_level"] == 2


def test_strategy_backtest_api_rejects_non_finite_exposure():
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            StrategyBacktestRequest(
                strategy_id="martingale_capped",
                max_exposure_pct=value,
            )


def test_martingale_parameter_normalization_matches_engine_bounds():
    assert normalize_martingale_parameters(
        base_pct=10_000.0,
        multiplier=10_000.0,
        max_level=10_000,
        max_exposure_pct=1.0,
    ) == (1.0, 4.0, 4)
