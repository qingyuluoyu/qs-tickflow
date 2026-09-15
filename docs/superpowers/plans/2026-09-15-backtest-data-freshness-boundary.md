# Backtest Data Freshness Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent strategy backtests from accepting an end date after the locally generated enriched dataset and guide the UI to use the last available trading date.

**Architecture:** Keep TeaJoin as the provider and the enriched Parquet repository as the single backtest data source. The API reads the existing repository's per-asset latest enriched date before scheduling a strategy run; the page reads the existing data-status response to constrain and default its date picker.

**Tech Stack:** FastAPI, Pydantic, Polars-backed `KlineRepository`, React 18, TypeScript, Vitest/pytest, pnpm.

## Global Constraints

- Do not query a provider directly from a backtest request; the backtest must use persisted enriched data.
- Never silently clamp an explicitly submitted end date; return a clear error that states the available-through date.
- Treat ETF and stock enriched repositories independently.
- Preserve existing request fields, job/SSE contracts, and strategy execution behavior for covered date ranges.
- Do not add data, secrets, generated outputs, or runtime configuration to Git.

---

### Task 1: Cover the API date-coverage contract

**Files:**
- Modify: `backend/tests/backtest/test_backtest_api.py`
- Modify: `backend/app/api/backtest.py`

**Interfaces:**
- Consumes: `request.app.state.repo.latest_enriched_date(asset_type)`.
- Produces: strategy run rejection with HTTP 422 and a detail containing the requested end date and available latest enriched date.

- [ ] **Step 1: Write the failing API test**

```python
def test_strategy_run_rejects_end_after_latest_enriched_date(client, monkeypatch):
    monkeypatch.setattr(client.app.state.repo, "latest_enriched_date", lambda _asset: date(2026, 9, 14))

    response = client.post(
        "/api/backtest/strategy/run",
        json={"strategy": "ma_cross", "start": "2026-09-01", "end": "2026-09-15"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "回测结束日期 2026-09-15 超出股票复权指标数据截止日 2026-09-14；请先同步并生成指标数据，或将结束日期改为不晚于该日期。"
```

- [ ] **Step 2: Run the test and verify it fails because the endpoint currently queues the run**

Run: `cd backend; uv run python -m pytest tests/backtest/test_backtest_api.py::test_strategy_run_rejects_end_after_latest_enriched_date -q`

Expected: FAIL because the response is not HTTP 422.

- [ ] **Step 3: Add the minimal reusable coverage check before strategy work is scheduled**

```python
def _backtest_end_date_coverage_error(request: Request, *, asset_type: str, end_date: date) -> str | None:
    data_asset_type = "etf" if asset_type == "etf" else "stock"
    latest_date = request.app.state.repo.latest_enriched_date(data_asset_type)
    if latest_date is None:
        return f"{_asset_label(data_asset_type)}复权指标数据尚未生成；请先完成数据同步和指标计算。"
    if end_date > latest_date:
        return (
            f"回测结束日期 {end_date} 超出{_asset_label(data_asset_type)}复权指标数据截止日 "
            f"{latest_date}；请先同步并生成指标数据，或将结束日期改为不晚于该日期。"
        )
    return None
```

Call this helper from `strategy_run` after parsing the request dates and before creating the worker future. Convert a non-empty result to `HTTPException(status_code=422, detail=error)`.

- [ ] **Step 4: Run the focused test and the affected API module tests**

Run: `cd backend; uv run python -m pytest tests/backtest/test_backtest_api.py -q`

Expected: PASS.

### Task 2: Apply the same check to the strategy SSE, optimizer, and walk-forward entry points

**Files:**
- Modify: `backend/app/api/backtest.py`
- Modify: `backend/tests/backtest/test_backtest_api.py`

**Interfaces:**
- Consumes: `_backtest_end_date_coverage_error(request, asset_type, end_date)` from Task 1.
- Produces: no strategy job is created when an SSE endpoint receives an uncovered end date; the stream emits its normal error event containing the coverage message.

- [ ] **Step 1: Write failing stream tests for a stale requested end date**

```python
def test_strategy_stream_reports_stale_end_date_before_creating_job(client, monkeypatch):
    monkeypatch.setattr(client.app.state.repo, "latest_enriched_date", lambda _asset: date(2026, 9, 14))

    response = client.get(
        "/api/backtest/strategy/stream",
        params={"strategy": "ma_cross", "start": "2026-09-01", "end": "2026-09-15"},
    )

    assert response.status_code == 200
    assert "2026-09-14" in response.text
    assert "error" in response.text
```

- [ ] **Step 2: Run the stream test and verify it fails before implementation**

Run: `cd backend; uv run python -m pytest tests/backtest/test_backtest_api.py::test_strategy_stream_reports_stale_end_date_before_creating_job -q`

Expected: FAIL because the endpoint starts a run or reports an unrelated downstream no-data error.

- [ ] **Step 3: Guard all strategy-based asynchronous entry points before creating a job**

Use the Task 1 helper after each endpoint resolves `end_date`. For SSE responses, emit the project’s existing structured error event and return before `_make_job_key()` or task submission. Apply this to strategy streaming, optimization, and walk-forward endpoints so all controls on the same strategy page follow one data-coverage rule.

- [ ] **Step 4: Run focused stream/API tests**

Run: `cd backend; uv run python -m pytest tests/backtest/test_backtest_api.py -q`

Expected: PASS.

### Task 3: Make the strategy page use the repository date range

**Files:**
- Modify: `frontend/src/pages/backtest/StrategyBacktest.tsx`

**Interfaces:**
- Consumes: `useDataStatus()` `TableStats.latest_date` for the currently selected stock or ETF enriched dataset.
- Produces: all default and quick-range end dates are `latest_date`; the end date picker has `max=latest_date`; an out-of-range manual/saved end date is visibly blocked before request submission.

- [ ] **Step 1: Add a failing component-level assertion or existing frontend test for the date bound**

```tsx
expect(screen.getByLabelText("结束日期")).toHaveAttribute("max", "2026-09-14")
expect(screen.getByText("回测数据截至 2026-09-14")).toBeInTheDocument()
```

If the repository has no component-test harness for this page, record that limitation and use the TypeScript build plus a manual browser check in Step 4; do not introduce a test framework for this focused bug fix.

- [ ] **Step 2: Run the selected test and verify it fails, or record the absent harness**

Run: `cd frontend; pnpm test -- --run StrategyBacktest`

Expected: FAIL for the missing date bound, or an explicit “no test script” result.

- [ ] **Step 3: Implement the smallest UI boundary**

```tsx
const latestDate = backtestDataStatus?.latest_date ?? null
const suggestedEndDate = latestDate ?? TODAY
const endExceedsAvailableData = Boolean(latestDate && end && end > latestDate)
```

Use `suggestedEndDate` in default-when-loaded behavior and quick ranges. Keep a saved/manual value that exceeds `latestDate` unchanged, show an inline Chinese error, disable Run, and add `max={latestDate ?? undefined}` to the end picker. Update the run handler to display the same client-side error as a guard; retain backend validation as the authority.

- [ ] **Step 4: Build and manually inspect the screen**

Run: `cd frontend; pnpm build`

Expected: PASS. Manually select stock and ETF: the UI must state their separate latest available dates, forbid a later end date, and use the latest available date for quick ranges.

### Task 4: Validate release readiness and document the operational behavior

**Files:**
- Modify: `docs/strategy.md`
- Modify: `backend/tests/backtest/test_backtest_api.py`

**Interfaces:**
- Documents that TeaJoin data must be synced and enriched before backtests and that the date picker/API will reject uncovered ranges.

- [ ] **Step 1: Add regression coverage for current data and no enriched dataset**

```python
assert valid_response.status_code == 200
assert empty_data_response.status_code == 422
assert "尚未生成" in empty_data_response.json()["detail"]
```

- [ ] **Step 2: Run the test group and static checks**

Run: `cd backend; uv run python -m pytest tests/backtest/test_backtest_api.py -q; uv run ruff check app/api/backtest.py tests/backtest/test_backtest_api.py`

Expected: PASS.

- [ ] **Step 3: Add concise user-facing operational guidance**

Add a short “回测数据边界” paragraph to `docs/strategy.md`: daily provider data is persisted first, then enriched; only enriched coverage can be backtested; a non-trading day may legitimately show the prior trading day as the latest date.

- [ ] **Step 4: Run final cross-layer checks**

Run: `cd frontend; pnpm build; cd ..; git diff --check`

Expected: PASS with only the planned backend, frontend, documentation, and test changes.
