# Financial Analysis TeaJoin Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the financial analysis page search TeaJoin when the local instrument cache misses and return TeaJoin financial records under the field contract consumed by the page.

**Architecture:** Keep the existing financial API routes and local parquet cache as the first read. Add a financial-only service boundary that canonicalizes raw TeaJoin/Tushare fields and performs an on-demand custom-provider read only when the requested symbol/table has no local rows. Add a financial-only search route so other pages using the shared instrument search are unchanged.

**Tech Stack:** FastAPI, Polars, custom HTTP provider, React Query, TypeScript, pytest, pnpm/Vite.

## Global Constraints

- Preserve the existing provider abstraction and TeaJoin body-token contract.
- Do not fabricate unavailable EPS/ROE or report values; expose only fields present in TeaJoin or deterministic aliases.
- Keep local parquet reads first and use TeaJoin only for a requested symbol/table cache miss.
- Keep changes scoped to the financial analysis page and its financial API; no database migration or destructive data rewrite.
- Preserve existing raw columns for compatibility while adding canonical response fields.

---

### Task 1: Reproduce and lock the broken financial contract

**Files:**
- Create: `backend/tests/test_financial_view.py`
- Test: `backend/tests/test_financial_view.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_normalize_financial_frame_adds_frontend_contract_aliases():
    raw = pl.DataFrame({
        "ts_code": ["000001.SZ"], "trade_date": ["20260813"],
        "turnover_rate": [0.5], "total_mv": [100.0],
    })
    result = normalize_financial_frame("metrics", raw)
    assert result.to_dicts()[0]["period_end"] == "20260813"
    assert result.to_dicts()[0]["announce_date"] == "20260813"
    assert result.to_dicts()[0]["market_cap"] == 1_000_000.0


def test_normalize_financial_frame_maps_tushare_report_fields():
    raw = pl.DataFrame({
        "symbol": ["000001.SZ"], "end_date": ["20240630"],
        "ann_date": ["20240816"], "oper_cost": [10.0],
        "operate_profit": [12.0], "n_income": [8.0],
    })
    row = normalize_financial_frame("income", raw).to_dicts()[0]
    assert row["period_end"] == "20240630"
    assert row["announce_date"] == "20240816"
    assert row["operating_cost"] == 10.0
    assert row["operating_profit"] == 12.0
    assert row["net_income"] == 8.0
```

- [ ] **Step 2: Run the focused tests to verify RED**

Run: `cd backend; uv run pytest tests/test_financial_view.py -q`

Expected: FAIL because `app.services.financial_view.normalize_financial_frame` does not exist.

### Task 2: Add canonical financial view and TeaJoin cache-miss retrieval

**Files:**
- Create: `backend/app/services/financial_view.py`
- Modify: `backend/app/api/financials.py`
- Test: `backend/tests/test_financial_view.py`

- [ ] **Step 1: Implement deterministic field aliases and units**

`normalize_financial_frame(table, frame)` must add `period_end`/`announce_date`, map report aliases (`oper_cost`→`operating_cost`, `operate_profit`→`operating_profit`, `n_income`→`net_income`, and the balance/cash-flow equivalents), and expose metrics `market_cap`/`float_market_cap` as `total_mv`/`circ_mv` multiplied by 10,000 because TeaJoin daily_basic reports market value in 万元. It must retain all raw columns and return an empty frame unchanged.

- [ ] **Step 2: Implement on-demand custom-provider fallback**

Add `load_financial_frame(data_dir, table, symbol)`:

1. Read the existing parquet with `get_financial_df` and filter the exact normalized symbol.
2. If rows exist, canonicalize and return them without a network call.
3. If rows are missing, resolve the configured financial provider; only if it is a custom provider with the `financial` dataset call `provider.get_financials(table, [symbol], latest_only=True)`.
4. Canonicalize the returned frame and return it; catch provider/network failures with a warning and return the empty canonical frame.

- [ ] **Step 3: Route all five financial table endpoints through the service**

Replace each direct `get_financial_df`/filter block in `backend/app/api/financials.py` with `load_financial_frame`, preserving the current `{data: [...]}` response and capability checks. No writes are performed on this read path.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `cd backend; uv run pytest tests/test_financial_view.py tests/test_teajoin_provider.py tests/test_financial_shares.py -q`

Expected: all focused tests pass.

### Task 3: Make financial stock search TeaJoin-aware without changing shared search

**Files:**
- Modify: `backend/app/api/financials.py`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/queryKeys.ts`
- Modify: `frontend/src/components/financials/StockFinancialSearch.tsx`
- Test: `backend/tests/test_financial_view.py`

- [ ] **Step 1: Write the failing search fallback test**

```python
def test_search_financial_symbols_falls_back_to_custom_instruments(monkeypatch):
    repo = FakeRepo(local_rows=[])
    monkeypatch.setattr(financial_view, "get_custom_instruments", lambda: [
        {"symbol": "600519.SH", "name": "贵州茅台", "code": "600519", "asset_type": "stock"},
    ])
    result = search_financial_symbols(repo, "600519", limit=20)
    assert result == [{"symbol": "600519.SH", "name": "贵州茅台", "code": "600519", "asset_type": "stock"}]
```

- [ ] **Step 2: Run the test to verify RED**

Run: `cd backend; uv run pytest tests/test_financial_view.py::test_search_financial_symbols_falls_back_to_custom_instruments -q`

Expected: FAIL because the financial-only search helper is not implemented.

- [ ] **Step 3: Implement the financial-only route and client**

Add `GET /api/financials/search?q=&limit=`. Search local stock instruments first; when there are no matches, fetch the configured custom provider's instruments, filter by code/symbol/name, and return the same `{results: [...]}` shape. Add `api.financialSearch` and a `QK.financialSearch` key, then switch only `StockFinancialSearch` to this method.

- [ ] **Step 4: Run backend and frontend checks**

Run: `cd backend; uv run pytest tests/test_financial_view.py tests/test_financial_shares.py -q`

Run: `cd frontend; pnpm build`

Expected: focused backend tests pass and Vite build exits 0.

### Task 4: Align the financial page display with real TeaJoin fields

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/components/financials/StockFinancialDetail.tsx`
- Test: `backend/tests/test_financial_view.py`

- [ ] **Step 1: Add real metrics fields to the TypeScript contract**

Expose `period_end`, `announce_date`, `close`, `turnover_rate`, `pe`, `pe_ttm`, `pb`, `ps`, `ps_ttm`, `dv_ratio`, `dv_ttm`, `market_cap`, and `float_market_cap` as optional metric fields.

- [ ] **Step 2: Replace unavailable placeholder metric cards**

Render the TeaJoin daily_basic fields above with correct units and labels. Keep report-table aliases from Task 2, and keep the existing empty state only when the API truly returns no rows.

- [ ] **Step 3: Run the complete verification matrix**

Run: `cd backend; uv run pytest -q`

Run: `cd frontend; pnpm build`

Run: `curl.exe -sS http://localhost:3018/api/financials/search?q=600519&limit=20` and `curl.exe -sS "http://localhost:3018/api/financials/metrics?symbol=000001.SZ"`.

Expected: backend tests pass, frontend build exits 0, search returns `600519.SH`, and metrics response contains non-null `period_end` plus real TeaJoin daily_basic values.
