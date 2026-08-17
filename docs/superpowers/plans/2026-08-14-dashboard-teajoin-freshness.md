# Dashboard TeaJoin Freshness Cutover Implementation Plan

> **For agentic workers:** Execute the tasks inline with test-first verification. Do not claim current-market data when TeaJoin has not returned a current snapshot.

**Goal:** Make the market dashboard use TeaJoin as its sole selected realtime source, remove hidden TickFlow fallback behavior, and expose an explicit stale/empty-source state instead of presenting yesterday's snapshot as today's market.

**Architecture:** Keep `/api/overview/market` and the React query contract stable, but extend the response with source/freshness metadata. QuoteService remains the single realtime ingestion path; it records whether the selected TeaJoin provider returned data, returned an empty snapshot, or failed. The dashboard uses that metadata to explain the data date and refuses to label a stale snapshot as realtime.

**Tech Stack:** Python 3.11+, FastAPI, Polars, pytest, React/TypeScript, Vite.

## Global Constraints

- Never silently call TickFlow after TeaJoin is selected for realtime data.
- Keep API keys out of logs, fixtures, and browser code.
- Preserve the last valid persisted snapshot, but label it with its actual effective date and source state.
- Empty or stale TeaJoin data must remain distinguishable from a transport or schema failure.

### Task 1: Reproduce and lock the provider cutover behavior

**Files:**
- Create: `backend/tests/test_quote_provider_cutover.py`
- Modify: `backend/app/services/quote_service.py`

- [x] Add a failing test proving a selected custom realtime provider with no dataset never calls the TickFlow client and reports `provider_unavailable`.
- [x] Add a failing test proving an empty TeaJoin realtime response reports `empty` and does not update quote timestamps or symbol counts.
- [x] Implement the minimal status fields and fail-closed custom-provider branch.
- [x] Run the focused tests with `backend/.venv/Scripts/python.exe -m pytest -q`.

### Task 2: Add dashboard freshness/source metadata

**Files:**
- Create: `backend/tests/test_market_overview_freshness.py`
- Modify: `backend/app/services/market_overview_builder.py`
- Modify: `frontend/src/lib/api.ts`

- [x] Add a failing test proving the overview reports the selected daily source, snapshot date, current Beijing date, and stale state.
- [x] Add metadata without changing existing KPI field meanings or percentage units.
- [x] Verify explicit historical dates are not incorrectly marked as the current snapshot.

### Task 3: Make the dashboard fail-closed and explain TeaJoin availability

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`
- Test: `frontend` production build.

- [x] Show TeaJoin-specific status when the realtime provider returned no rows or failed.
- [x] Keep historical data visible only with an explicit date/source warning; never show “实时” for a stale snapshot.
- [x] Run `pnpm build` and the affected backend tests.

### Task 4: Runtime verification

- [x] Query `/api/intraday/status`, `/api/overview/market`, and the TeaJoin provider test endpoint with the configured key without printing secrets.
- [x] Confirm frontend and backend remain healthy on ports 3011 and 3018.
- [x] Record the remaining external blocker if TeaJoin's realtime endpoint returns an empty dataset for the current session.
