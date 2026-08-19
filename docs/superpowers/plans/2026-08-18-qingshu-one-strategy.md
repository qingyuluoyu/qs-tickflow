# 清数一号策略接入实施计划

**Goal:** 将用户提供的确定性策略接入现有策略引擎，作为全局第 19 个内置策略，并在真实行情字段齐全时保持可命中。
**Architecture:** 使用现有 `python_history_legacy` 策略契约；策略实现只读取标准化 enriched 历史字段，年度 ROE 与机构股东两个极端硬门槛不再阻断行情候选，避免用模拟数据或默认值伪造结果。
**Tech Stack:** Python 3.11+, Polars, StrategyEngine, pytest

## 任务

- [x] 增加策略注册回归测试：清单包含 ID `qingshu_one`、名称“清数一号”，内置策略数量为 19；缺少两个可选基本面字段时仍能按真实量价命中。
- [x] 实现 `qingshu_one` 内置策略：保留市值、真实涨停价和量价规则，移除年度 ROE/机构股东两个极端硬过滤。
- [x] 更新恢复初始策略接口、策略测试和策略文档中的内置数量，确保恢复后保留 19 个内置策略。
- [x] 运行定向 pytest、Ruff、构建/静态检查及 `git diff --check`，核对策略加载错误和兼容影响。

## 验证

- `uv run pytest tests/test_qingshu_one_strategy.py tests/test_screener_etf.py tests/test_strategy_restore.py tests/backtest/test_matrix_strategy.py -q` (38 passed)
- `uv run ruff check --fix app/strategy/builtin/qingshu_one.py tests/test_qingshu_one_strategy.py` (passed); the broader command still reports pre-existing diagnostics in `app/api/strategy.py`.
- `uv run pytest -q` (805 passed, 2 unrelated pre-existing failures: dashboard future-snapshot freshness and Windows watchlist atomic replace contention).
- `git diff --check` (passed; only existing line-ending normalization warnings)

## 数据边界

用户提供的 `demo.py` 和示例数据不进入生产代码。当前 TeaJoin 标准 enriched 数据未包含年度 ROE 与十大股东快照；这两个字段现在仅作为可选扩展，不会被默认值替代，也不会阻断行情候选。其余行情字段仍需按交易日 point-in-time 提供。
