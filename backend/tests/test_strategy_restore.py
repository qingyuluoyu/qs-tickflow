from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.strategy import RestoreDefaultsRequest, restore_default_strategies
from app.strategy.engine import StrategyEngine


def _strategy_code(strategy_id: str) -> str:
    return f'''import polars as pl
META = {{
    "id": "{strategy_id}",
    "name": "{strategy_id}",
    "asset_types": ["stock"],
    "timeframes": ["1d"],
}}
def filter(df, params):
    return pl.lit(True)
'''


def _request(data_dir: Path, engine: StrategyEngine):
    repo = SimpleNamespace(store=SimpleNamespace(data_dir=data_dir))
    state = SimpleNamespace(repo=repo, strategy_engine=engine)
    return SimpleNamespace(app=SimpleNamespace(state=state))


def _engine(data_dir: Path) -> StrategyEngine:
    builtin = Path(__file__).resolve().parents[1] / "app" / "strategy" / "builtin"
    return StrategyEngine(
        strategy_dirs=[
            builtin,
            *(data_dir / "strategies" / source for source in ("custom", "ai", "composite")),
        ]
    )


def test_restore_defaults_requires_explicit_confirmation(tmp_path):
    engine = _engine(tmp_path)

    with pytest.raises(HTTPException) as exc_info:
        restore_default_strategies(RestoreDefaultsRequest(confirm=False), _request(tmp_path, engine))

    assert exc_info.value.status_code == 400
    assert "确认" in exc_info.value.detail


def test_restore_defaults_removes_user_strategies_and_returns_all_builtins(tmp_path):
    for source, strategy_id in (("custom", "custom_saved"), ("ai", "ai_saved"), ("composite", "composite_saved")):
        strategy_dir = tmp_path / "strategies" / source
        strategy_dir.mkdir(parents=True, exist_ok=True)
        (strategy_dir / f"{strategy_id}.py").write_text(_strategy_code(strategy_id), encoding="utf-8")

    overrides_dir = tmp_path / "user_data" / "strategy_overrides"
    overrides_dir.mkdir(parents=True)
    (overrides_dir / "custom_saved.json").write_text('{"name":"changed"}', encoding="utf-8")
    (overrides_dir / "ma_golden_cross.json").write_text('{"params":{"window":99}}', encoding="utf-8")

    engine = _engine(tmp_path)
    assert len(engine.list_strategies()) == 25

    result = restore_default_strategies(
        RestoreDefaultsRequest(confirm=True),
        _request(tmp_path, engine),
    )

    assert result["ok"] is True
    assert result["count"] == 22
    assert len(result["builtin_strategy_ids"]) == 22
    assert result["deleted"] == ["ai_saved", "composite_saved", "custom_saved"]
    assert not list((tmp_path / "strategies").glob("**/*.py"))
    assert not list(overrides_dir.glob("*.json"))
    assert {item["source"] for item in engine.list_strategies()} == {"builtin"}
    assert len(engine.list_strategies()) == 22
