from datetime import date
from pathlib import Path

from app.backtest.strategy import StrategyBacktestConfig
from app.backtest.worker import make_worker_task


def test_worker_task_keeps_shared_market_root_and_personal_strategy_root(tmp_path: Path):
    shared = tmp_path / "shared"
    personal = tmp_path / "users" / "user-a"
    config = StrategyBacktestConfig(
        strategy_id="builtin.demo",
        symbols=None,
        start=date(2025, 1, 1),
        end=date(2025, 1, 2),
    )

    task = make_worker_task("backtest", shared, config, user_data_dir=personal)

    assert Path(task["data_dir"]) == shared.resolve()
    assert Path(task["user_data_dir"]) == personal.resolve()
