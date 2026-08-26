# 三个研究策略实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** 在现有矩阵回测契约下增加三个可复现的研究型策略，并在相同 20 万元、半年、A 股、T+1、成本和涨跌停约束下给出真实横向结果。

**Architecture:** 新策略全部作为 `backend/app/strategy/builtin/*.py` 的 `matrix_native` 叶子策略注册，不改数据源、不引入第二套指标计算、不把未来数据放入信号。马丁格尔只作为风险对照：本轮不实现无限补仓或隐式加仓，因为现有撮合器是单标的一层持仓、等权配置；新增策略会明确标注为“受限研究信号”，不会把普通等权回测冒充成真正的马丁格尔收益。

**Tech Stack:** Python 3.11+, NumPy, Polars, 项目现有 `MarketDataMatrix` / `SignalMatrix` / `StrategyBacktestService`，pytest，现有 TeaJoin/Parquet 行情快照。

## Global Constraints

- 保持 A 股 T+1、涨跌停、停牌、佣金、印花税和滑点约束。
- 指标只使用信号日已经可获得的字段；不得使用未来函数或回填的点时数据。
- 新策略没有样本外证据前，只能称为研究候选，不得称为“超级好”“稳定”或“可实盘”。
- 不修改现有 19 个策略的计算公式；只更新注册数量断言和新增策略测试。

### Task 1: 写新策略注册和公式契约的失败测试

**Files:**
- Create: `backend/tests/test_three_research_strategies.py`
- Modify: `backend/tests/backtest/test_matrix_strategy.py:258-266,675-686`
- Modify: `backend/tests/test_qingshu_one_strategy.py:13-18`
- Modify: `backend/tests/test_screener_etf.py:43-59`

**Interfaces:**
- Tests expect strategy IDs `squeeze_breakout`, `relative_strength_pullback`, and `risk_capped_reversal`.
- Each strategy must expose `META`, `EXECUTION_BACKEND = "matrix_native"`, `MATRIX_STRATEGY`, valid `required_fields`, warmup bars, and a deterministic `compute_signals` result.

- [ ] **Step 1: Write the failing test**

```python
def test_three_research_strategies_are_registered_and_matrix_native():
    engine = StrategyEngine(strategy_dirs=[BUILTIN_DIR])
    defs = {item.meta["id"]: item for item in engine.strategy_definitions()}
    assert {"squeeze_breakout", "relative_strength_pullback", "risk_capped_reversal"} <= set(defs)
    assert all(defs[sid].execution_backend == "matrix_native" for sid in NEW_IDS)
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `cd backend; uv run pytest tests/test_three_research_strategies.py -q`

Expected: FAIL because the three strategy files do not exist yet.

### Task 2: Implement three matrix-native research strategies

**Files:**
- Create: `backend/app/strategy/builtin/squeeze_breakout.py`
- Create: `backend/app/strategy/builtin/relative_strength_pullback.py`
- Create: `backend/app/strategy/builtin/risk_capped_reversal.py`

**Interfaces:**
- `required_fields()` returns only fields available in `MarketDataMatrix`.
- `required_warmup_bars()` returns at least 60.
- `compute_signals(market, params)` returns entry/exit matrices using `matrix_feature` and no future rows.

- [ ] **Step 1: Implement `squeeze_breakout`**

Use Bollinger bandwidth `(boll_upper-boll_lower)/ma20` below a configurable compression threshold within a recent lookback, then require close above the upper band, positive candle and volume ratio above a threshold. Exit on MA20 breakdown. This is a volatility-compression breakout, not a promise of a positive return.

- [ ] **Step 2: Implement `relative_strength_pullback`**

Require `close > MA60`, positive 20/60-day momentum, price within a configurable percentage of MA20, and a bullish recovery candle. Exit on MA20 breakdown or MA5 dead cross.

- [ ] **Step 3: Implement `risk_capped_reversal`**

Require RSI14 below an upper bound, close above MA5 after a 60-day low proximity event, positive candle and optional volume confirmation. Set explicit stop-loss and maximum holding days. The metadata must say it is a bounded reversal research signal and **not** a true Martingale; no repeated doubling is implemented in this engine.

### Task 3: Verify formulas and regression behavior

**Files:**
- Modify: `backend/tests/test_three_research_strategies.py`

- [ ] **Step 1: Add deterministic synthetic matrix cases**
- [ ] **Step 2: Verify each strategy emits entry only when its documented conditions hold**
- [ ] **Step 3: Verify exits and missing-feature failures are explicit**
- [ ] **Step 4: Run focused tests**

Run: `cd backend; uv run pytest tests/test_three_research_strategies.py tests/backtest/test_matrix_strategy.py -q`

### Task 4: Run the same-condition six-month audit

**Files:**
- Create: `artifacts/three_strategy_backtest_20260221_20260821.json`
- Create: `artifacts/build_three_strategy_report.py` (only if a Word appendix is requested)

- [ ] **Step 1: Run all three with initial capital ¥200,000, max 10 positions, 100% exposure, equal sizing, open_t+1, 0.03% commission, 0.05% sell stamp tax, 5 bps slippage, stock daily data, and the latest completed local data date.**
- [ ] **Step 2: Record data freshness, trade count, max drawdown, Sharpe, win rate, profit factor, exposure, execution rejects, and errors.**
- [ ] **Step 3: Do not rank a strategy with no trades or a failed feature contract as profitable.**
- [ ] **Step 4: Compare against the existing 19-strategy audit without selecting candidates after seeing returns.**

### Task 5: Report limitations and next experiment

- [ ] State that no “super good” or guaranteed strategy exists.
- [ ] Explain why unlimited Martingale is unsuitable for A shares and is not implemented as a production default.
- [ ] Provide the exact next experiment: bounded layer sizing needs a separate execution contract, explicit max layers, max per-symbol exposure, stop conditions, and dedicated tests before it can be compared fairly.
