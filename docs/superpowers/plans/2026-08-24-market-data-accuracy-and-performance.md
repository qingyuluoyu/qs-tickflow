# Market Data Accuracy and Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every current-market dashboard snapshot date-verifiable and internally consistent while removing redundant provider calls, repeated overview rebuilds, and avoidable post-warmup memory retention.

**Architecture:** Preserve the custom-provider abstraction and the existing preloader/API contracts. Make each HTTP request payload immutable, admit a dashboard snapshot only after deterministic schema/date/completeness checks, expose the background snapshot generation through the lightweight status response, and let the frontend refresh only when that generation changes. Release native temporary allocations after repository warmup without evicting the live caches that strategies require.

**Tech Stack:** Python 3.11, FastAPI, Polars, pytest, React/TypeScript, TanStack Query, Vite, systemd/nginx.

## Global Constraints

- TeaJoin remains the authoritative configured daily source; no TickFlow fallback and no synthetic prices.
- A-share rates remain decimal internally (`0.0366` means `3.66%`); turnover exposed by the dashboard remains percentage points.
- Completed daily data must match the exchange cutoff date and may not contain duplicates, invalid OHLC, missing required fields, or a materially partial universe.
- Existing API fields remain backward compatible; new status fields are optional to old clients.
- Preserve the dirty worktree and deploy only verified files to `/home/ubuntu/tickflow`.

---

### Task 1: Isolate custom-provider request payloads

**Files:**
- Modify: `backend/app/data_providers/custom/provider.py`
- Modify: `backend/tests/test_teajoin_provider.py`

**Interfaces:**
- Consumes: `DatasetConfig.body`, `DatasetConfig.params`, `_set_nested()`.
- Produces: `_request_rows()` requests whose body and params cannot mutate the shared provider configuration.

- [ ] Add a failing test that performs a symbol-scoped request followed by an unfiltered request and asserts the second JSON body is exactly `{"params": {}}`.
- [ ] Run `uv run pytest tests/test_teajoin_provider.py -q` and confirm the second request incorrectly retains `params.ts_code`.
- [ ] Replace shallow mapping copies with `copy.deepcopy()` for params/body and overrides before nested writes.
- [ ] Add a concurrency regression using two requests with different symbols and assert neither captured payload is contaminated.
- [ ] Run the provider tests and Ruff.

### Task 2: Gate current dashboard snapshots by data quality

**Files:**
- Modify: `backend/app/services/market_overview_preloader.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_dashboard_preload.py`

**Interfaces:**
- Consumes: normalized daily/realtime frames and an expected-stock-symbol loader.
- Produces: a `DashboardSnapshot` only when `symbol/date/OHLCV/amount` are valid, symbols are unique, all rows belong to the allowed date, and current-day stock coverage is at least 90% of the active instrument universe; the index frame must cover all four configured core indices.

- [ ] Add failing tests for a duplicate-symbol daily snapshot, a 10% partial-universe snapshot, mixed/null realtime dates, and a three-of-four index result.
- [ ] Run focused tests and confirm each invalid frame is currently accepted.
- [ ] Implement pure frame-quality helpers returning a machine-readable rejection reason; do not convert bad values to zero.
- [ ] Pass the repository stock-symbol loader into the production fetcher and retain the prior valid snapshot with an explicit quality error when a candidate fails.
- [ ] Run dashboard/preloader/provider-boundary tests and Ruff.

### Task 3: Refresh the dashboard only when its snapshot changes

**Files:**
- Modify: `backend/app/services/market_overview_preloader.py`
- Modify: `backend/app/api/intraday.py`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/pages/Dashboard.tsx`
- Modify: `frontend/tests/market-data-freshness.test.mjs`

**Interfaces:**
- Produces: optional `snapshot_generation`, `snapshot_date`, `snapshot_kind`, and `snapshot_status` fields on `/api/intraday/status`.
- Consumes: those fields in the dashboard polling query; invalidates `overview-market` only when generation changes, and disables background polling for historical dates.

- [ ] Add backend and frontend failing tests proving unchanged status polls do not cause overview invalidation.
- [ ] Increment generation only when snapshot data/status materially changes, not on copying or reading.
- [ ] Add the optional status fields without removing existing response fields.
- [ ] Replace timestamp-based invalidation with generation comparison while keeping the last valid overview visible.
- [ ] Run backend status tests, all frontend Node tests, and `pnpm build`; record request/rebuild counts before and after.

### Task 4: Release temporary native memory after repository warmup

**Files:**
- Modify: `backend/app/tickflow/repository.py`
- Modify: `backend/tests/test_repository_cache.py` or the closest repository cache test module.

**Interfaces:**
- Produces: `_release_temporary_memory()` that calls Python GC and Linux `malloc_trim(0)` when available after the final immutable cache snapshots are installed.
- Preserves: `_enriched_history_cache`, `_enriched_cache`, `_live_agg_cache`, and all public repository getters.

- [ ] Add a failing unit test with a patched libc proving trim is attempted only after warmup completion and absence/failure is harmless.
- [ ] Implement a platform-safe helper with no new dependency and invoke it after large temporary frames go out of scope.
- [ ] Run repository/cache/strategy tests and measure production RSS before and after the same restart/warmup sequence.
- [ ] Reject this optimization if RSS or latency does not measurably improve.

### Task 5: Full verification and controlled production rollout

**Files:**
- No source additions unless a directly related verification failure is reproduced first.

**Interfaces:**
- Production health and dashboard data remain backward compatible.

- [ ] Run focused tests, full backend pytest, full frontend Node suite, frontend production build, Ruff for touched Python, and `git diff --check`.
- [ ] Repeat the TeaJoin aggregate audit: date, row/symbol counts, required nulls, duplicates, OHLC validity, percentage recomputation error, and four-index coverage.
- [ ] Back up and deploy only verified source/build artifacts, restart `tickflow.service`, and wait through warmup plus boot-catchup windows.
- [ ] Confirm readiness, zero restarts/Tracebacks, bounded provider call counts, unchanged financial sync schedule, current snapshot date, and public response latency.
- [ ] Report exact before/after request counts, overview latency, RSS, compatibility impact, rollback files, and unresolved upstream limitations.
