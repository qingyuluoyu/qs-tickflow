# Dashboard Ranking Drilldown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the dashboard's four bottom rankings clearly show stock names and codes, and let concept/industry heat rows open a member-stock popup with a direct jump to individual stock analysis.

**Architecture:** Reuse the existing `DimensionMembersDialog` and `api.dimensionMembers` flow. Extend the dashboard overview rank contract with the exact extension source field needed to resolve members, wire dashboard row clicks to the dialog, and add query-string hydration to the existing stock-analysis page so navigation preserves symbol and name without changing its existing behavior.

**Tech Stack:** React + TypeScript, React Router, TanStack Query, FastAPI/Python, pytest, Vite.

## Global Constraints

- Keep the change scoped to the dashboard drill-down and the minimum shared route contract needed for navigation.
- Preserve existing TeaJoin/overview data calculations and the existing `DimensionMembersDialog` data validation/virtualized list.
- Do not add dependencies or change database schemas.
- Keep old API fields and old stock-analysis navigation behavior compatible.

---

### Task 1: Expose the extension source field in dashboard dimension ranks

**Files:**
- Modify: `backend/app/services/market_overview_builder.py:533-580`
- Modify: `frontend/src/lib/api.ts:357-370`
- Test: `backend/tests/test_market_overview_dimension_source.py`

**Interfaces:**
- Produces an optional `source_field: string` on each concept/industry rank item, formatted as `<extension_config_id>.<field_name>`.

- [ ] **Step 1: Write the failing test**

```python
def test_dimension_rank_exposes_member_source_field(monkeypatch, tmp_path):
    # The fixture config contains one concept field and one matching stock.
    result = builder._dimension_rank(rows, repo, "concept")
    assert result["leading"][0]["source_field"] == "teajoin_concepts.所属概念"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest backend/tests/test_market_overview_dimension_source.py -q`
Expected: FAIL because rank items currently do not contain `source_field`.

- [ ] **Step 3: Write the minimal implementation**

Track the source reference while grouping values and include it in each emitted item; keep all existing aggregate fields unchanged. Add `source_field?: string | null` to `OverviewDimensionRankItem`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest backend/tests/test_market_overview_dimension_source.py -q`
Expected: PASS.

### Task 2: Make dashboard rankings readable and clickable

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx:500-575, 850-900`
- Modify: `frontend/src/components/DimensionMembersDialog.tsx:1-20, 170-210`

**Interfaces:**
- `HotRankCard` receives `onDimensionClick(target)` and opens `DimensionMembersDialog` with the rank's `source_field`.
- `StockList` keeps its existing `onStockClick` callback while rendering name as the primary label and code as a readable secondary label.

- [ ] **Step 1: Write the failing browser behavior check**

Open `/`, click a concept/industry rank row, and assert a dialog heading contains the selected dimension name and the dialog contains a `股票` column. Before the change, the row is not clickable and no dialog opens.

- [ ] **Step 2: Run the check to verify it fails**

Use the in-app browser DOM snapshot and record the expected absence of a dialog after clicking a rank row.

- [ ] **Step 3: Write the minimal implementation**

Add a dashboard `dimensionTarget` state, pass rank source metadata into `HotRankCard`, make each dimension row a button with visible name/count/leader, and render `DimensionMembersDialog`. Increase the bottom four list row typography/height and preserve both name and code without truncation at normal desktop widths.

- [ ] **Step 4: Run the browser check to verify it passes**

Click both concept and industry rows; confirm the popup loads member stocks and closes without affecting other dashboard sections.

### Task 3: Preserve code/name when jumping to individual stock analysis

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx:850-900`
- Modify: `frontend/src/pages/StockAnalysis.tsx:1-75`

**Interfaces:**
- Dashboard navigation target: `/stock-analysis?symbol=<encoded symbol>&name=<encoded name>`.
- StockAnalysis reads `symbol` and `name` query parameters once on mount, while retaining last-stock fallback when no query is supplied.

- [ ] **Step 1: Write the failing browser behavior check**

From a dimension popup, click `个股分析` for a member and assert the URL includes the member code/name and the page header/search selection shows the same stock. Before the change, the route ignores query parameters.

- [ ] **Step 2: Run the check to verify it fails**

Navigate to `/stock-analysis?symbol=000001.SZ&name=%E5%B9%B3%E5%AE%89%E9%93%B6%E8%A1%8C` and confirm the page remains unselected.

- [ ] **Step 3: Write the minimal implementation**

Use `useSearchParams`, initialize state from query parameters, and call `rememberStock` when a valid query symbol is present. Keep the existing last-stock effect as the fallback path only.

- [ ] **Step 4: Run the browser check to verify it passes**

Confirm the target stock is selected and the K-line/analysis board starts loading for that symbol.

### Task 4: Verify build and regression scope

**Files:**
- No additional production files.

- [ ] **Step 1: Run focused backend tests**

Run: `python -m pytest backend/tests/test_market_overview_dimension_source.py backend/tests/test_ext_data_dimension_members.py -q`

- [ ] **Step 2: Run the frontend build**

Run: `npm run build` from `frontend`.

- [ ] **Step 3: Run browser regression checks**

Verify dashboard initial render, four stock lists, concept popup, industry popup, member jump, and direct query-string stock-analysis hydration; confirm no new console errors.
