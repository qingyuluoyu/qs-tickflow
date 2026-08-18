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

- [x] Write tests for a single-flight preload, cached response reuse, and empty-provider status preservation.
- [x] Run the preload tests; the callable factory regression and empty-provider behavior are covered.

### Task 2: Add a server-owned dashboard snapshot preloader

**Files:**
- Create: `backend/app/services/market_overview_preloader.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/overview.py`

- [x] Implement bounded background refresh with a lock, last-successful snapshot, source/date metadata, and a non-blocking request path.
- [x] Start and stop it with the FastAPI lifespan; provider calls run outside the cache lock.
- [x] Make `/api/overview/market` read the warmed snapshot for the latest view and preserve the last valid frame on an empty refresh.

### Task 3: Keep current-market semantics truthful

**Files:**
- Modify: `backend/app/services/market_overview_builder.py`
- Modify: `frontend/src/pages/Dashboard.tsx`
- Modify: `frontend/src/lib/api.ts`
- Test: `backend/tests/test_market_overview_freshness.py`

- [x] Ensure an empty TeaJoin realtime result remains `empty` and the dashboard shows the latest completed trading date with an explicit stale status.
- [x] Ensure a provider snapshot is used for breadth, rankings, turnover, limit ladder and index values, while persisted enriched data is only a dated fallback.
- [x] Derive daily turnover from TeaJoin volume plus same-date float shares and extend live board counts with the prior trading-day run length.
- [x] Route the shared index sidebar to the selected custom provider so it cannot display a different cached TickFlow snapshot beside the TeaJoin dashboard.
- [x] Include the core index daily frame in the same preloaded snapshot and reuse it in `/api/intraday/indices`, preventing duplicate provider calls and cross-request date drift.

### Task 4: Match the left navigation to the supplied icon sheet

**Files:**
- Modify: `frontend/src/components/Layout.tsx`
- Test: `frontend/tests/layout-navigation.test.mjs`

- [x] Use the supplied 14-item color/tone mapping with code-native Lucide icons, preserving the existing menu routes and badges.
- [x] Render each icon in a rounded, tinted tile so active state and text remain readable in both themes.

### Task 5: Verify runtime and regressions

- [x] Run focused backend tests (`52 passed`), full backend suite (`747 passed, 1 pre-existing failure`), frontend tests (`5 passed`), production build, and `git diff --check`.
- [x] Query the running app and direct TeaJoin snapshot without printing credentials; dashboard totals match the TeaJoin frame for 2026-08-14.
