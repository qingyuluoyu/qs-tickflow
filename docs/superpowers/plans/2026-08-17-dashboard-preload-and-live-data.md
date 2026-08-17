# Market Dashboard Preload and Live Data Implementation Plan

> **For agentic workers:** Execute the tasks inline with test-first verification.

**Goal:** Make the market dashboard return a warmed overview quickly and never present a stale TeaJoin snapshot as current-market data.

**Architecture:** Keep the existing `/api/overview/market` contract and provider boundary. Add a server-owned, short-lived dashboard snapshot cache that is warmed after startup and refreshed in the background; the request path serves the last valid snapshot while a refresh is in progress. Preserve explicit source/date/status metadata so an unavailable TeaJoin realtime endpoint is distinguishable from a current snapshot.

**Tech Stack:** FastAPI, Polars, TeaJoin custom provider, APScheduler/threaded preloader, React Query, pytest.

## Global Constraints

- TeaJoin remains the selected market-data provider; do not silently fall back to TickFlow.
- Do not fabricate current-day values when TeaJoin returns an empty realtime snapshot.
- Preserve the existing API response fields and historical-date behavior.
- Keep the change limited to the dashboard overview and its direct preload/status path.

---

### Task 1: Lock the slow/missing-preload behavior

**Files:**
- Create: `backend/tests/test_dashboard_preload.py`
- Modify: `backend/app/services/market_overview_preloader.py`

- [ ] Write tests for a single-flight preload, cached response reuse, and empty-provider status preservation.
- [ ] Run `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_dashboard_preload.py -q` and confirm the tests fail before implementation.

### Task 2: Add a server-owned dashboard snapshot preloader

**Files:**
- Create: `backend/app/services/market_overview_preloader.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/overview.py`

- [ ] Implement bounded background refresh with a lock, last-successful snapshot, source/date metadata, and a non-blocking `get_or_build` path.
- [ ] Start and stop it with the FastAPI lifespan; do not block startup or run provider calls while holding the cache lock.
- [ ] Make `/api/overview/market` read the warmed snapshot for the latest view and invalidate it after data refresh.

### Task 3: Keep current-market semantics truthful

**Files:**
- Modify: `backend/app/services/market_overview_builder.py`
- Modify: `frontend/src/pages/Dashboard.tsx`
- Modify: `frontend/src/lib/api.ts`
- Test: `backend/tests/test_market_overview_freshness.py`

- [ ] Ensure an empty TeaJoin realtime result remains `empty` and the dashboard shows the latest completed trading date with an explicit non-realtime status.
- [ ] Ensure a provider-confirmed current snapshot is used for breadth, rankings, and index values, while persisted enriched data is only a dated fallback.

### Task 4: Verify runtime and regressions

- [ ] Run the focused backend tests, affected provider tests, frontend tests, typecheck, lint, production build, and `git diff --check`.
- [ ] Query local TeaJoin health without printing credentials and check the dashboard response date/source/latency in the running app.

