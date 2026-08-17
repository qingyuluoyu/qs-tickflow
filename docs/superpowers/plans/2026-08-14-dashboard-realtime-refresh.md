# Dashboard TeaJoin Realtime Refresh Implementation Plan

> **For agentic workers:** Execute this plan inline with test-first checkpoints.

**Goal:** Make the dashboard continuously consume TeaJoin data with a 30-second refresh cadence and render the latest valid snapshot without presenting stale values as current.

**Architecture:** Keep TeaJoin as the selected provider and reuse the existing `/api/intraday/refresh` and `/api/overview/market` contracts. The frontend will poll the backend status/overview at 30 seconds, while the backend will record each TeaJoin fetch outcome; historical daily data remains the explicit fallback until TeaJoin returns a non-empty realtime snapshot.

**Tech Stack:** FastAPI, custom TeaJoin HTTP provider, QuoteService, React, TanStack Query, TypeScript/Vite.

## Global Constraints

- No TickFlow fallback when TeaJoin is selected.
- Never label a historical daily snapshot as today's realtime data.
- Keep provider, status, row count, and snapshot date traceable in the API response.
- Do not change strategy, backtest, or database schemas for this dashboard fix.

### Task 1: Reproduce the realtime contract failure

**Files:**
- Test: `backend/tests/test_teajoin_provider.py`
- Inspect: `data/data_sources/teajoin.yaml`, `backend/app/services/quote_service.py`

- [x] Existing quote-service regression coverage asserts an empty TeaJoin realtime table is classified as `empty` and does not advance the quote timestamp.
- [x] Reproduced the pre-change dashboard baseline: no 30-second refresh configuration was present.

### Task 2: Make the dashboard query the live path every 30 seconds

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`

- [x] Add a 30-second query interval for the overview while the dashboard is mounted.
- [x] Trigger `/api/intraday/refresh` only through the existing backend service and invalidate the overview query after completion.
- [x] Keep the latest valid historical snapshot visible with an explicit date/source label when realtime is empty.

### Task 3: Verify the complete runtime path

- [x] Run the focused backend tests (`35 passed`).
- [x] Run `pnpm build` successfully.
- [x] Open `/`, verify dashboard cards render, verify the source/status/date banner, and observe two `/api/intraday/refresh` requests about 32 seconds apart in the backend log without blanking the page.

### Task 4: Make the dashboard read the TeaJoin snapshot directly

**Files:**
- Modify: `backend/app/data_providers/custom/provider.py`
- Modify: `backend/app/services/market_overview_builder.py`
- Modify: `backend/app/api/overview.py`
- Modify: `data/data_sources/teajoin.yaml`
- Tests: `backend/tests/test_teajoin_provider.py`, `backend/tests/test_market_overview_freshness.py`

- [x] Add an unfiltered TeaJoin daily snapshot read that selects the provider's latest valid trading date without persisting or changing the shared history path.
- [x] Use that snapshot only for `/api/overview/market`; preserve historical/enriched behavior for recap, screener, strategy, and other callers.
- [x] Refresh core index quotes from TeaJoin's index daily endpoint and merge same-date deterministic indicators only when the dates match.
- [x] Recompute dashboard limit-up/down flags from TeaJoin OHLCV plus the instrument master, including a previous-close row so limit arithmetic is deterministic.
- [x] Reject future-dated provider snapshots and expose `snapshot_kind`/`snapshot_rows` in `data_freshness` for traceability.
- [x] Verify the live API returned 5,540 TeaJoin rows and TeaJoin-derived index values while historical `as_of` requests remained persisted-enriched.
