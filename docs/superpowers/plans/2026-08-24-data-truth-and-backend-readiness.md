# Data Truth and Backend Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Stop post-close provider request storms, make the dashboard consume TeaJoin's verified latest A-share trading-day data, and make streaming AI status distinguish startup, progress, and real connection failures.

**Architecture:** Keep the existing provider abstraction, MarketOverviewPreloader, QuoteService, APIs, and frontend streaming contracts. QuoteService will accept only a non-empty, date-verified daily preload as the post-close completion signal and will back off failed boundary synchronization. The dashboard index preload remains a symbol-batched TeaJoin daily request because production evidence shows the unfiltered index endpoint is empty while symbol-scoped requests return the current trading day. Frontend dialogs will update status from NDJSON lifecycle events and clear stale startup text after data arrives.

**Tech Stack:** Python 3.11+/FastAPI/Polars/pytest; React 18/TypeScript/Vite/Node test runner; systemd/nginx on Tencent Cloud.

**Global constraints:** Do not call TickFlow as a fallback, do not synthesize market values, do not persist provider diagnostics, do not expose keys, and preserve all existing user changes in the dirty worktree.

### Task 1: Reproduce and stop the post-close request storm

**Files:**
- Modify: `backend/app/services/quote_service.py`
- Modify: `backend/tests/test_quote_provider_cutover.py`

**Steps:**
1. Add failing tests proving a verified current-day daily preload completes the close boundary without calling realtime.
2. Add failing tests proving a failed boundary fetch is delayed with bounded exponential backoff instead of being retried every polling interval.
3. Implement a narrow post-close daily-preload readiness check and retry scheduling state.
4. Keep morning-final behavior unchanged because the previous completed daily bar is not a valid substitute for the morning settlement snapshot.
5. Run the focused quote-provider tests and Ruff on touched Python files.

### Task 2: Lock the TeaJoin dashboard date and index contract

**Files:**
- Modify if required: `backend/app/services/market_overview_preloader.py`
- Modify: `backend/tests/test_dashboard_preload.py`
- Modify: `backend/tests/test_market_overview_freshness.py`

**Steps:**
1. Add/confirm tests that post-close stock daily rows must match the resolved trading date.
2. Add/confirm tests that core indices are fetched by standard symbols and retain the latest two trading dates for change calculation.
3. Reject empty, future-dated, mixed-date, or missing-date provider results without relabelling them as current.
4. Run the dashboard preload and freshness test modules.

### Task 3: Correct streaming connection status lifecycle

**Files:**
- Modify: `frontend/src/components/RpsRotationDialog.tsx`
- Modify: `frontend/src/components/stock-analysis/DebateDialog.tsx`
- Modify: `frontend/tests/stock-analysis-debate-entry.test.mjs`

**Steps:**
1. Add failing source-contract tests requiring a neutral startup status and status clearing/updating on meta, delta, done, and error events.
2. Replace misleading unconditional connection copy with task startup copy.
3. On first server event, replace startup state; on first content/done, clear stale progress; classify thrown fetch errors as connection failures without overriding backend business errors.
4. Run the frontend Node tests and production build.

### Task 4: Full verification and production rollout

**Files:**
- No additional source files unless verification exposes a directly related defect.

**Steps:**
1. Run focused tests, the complete backend suite, the complete frontend Node suite, frontend production build, Ruff for touched Python files, and `git diff --check`.
2. Synchronize only the verified source/build artifacts to `/home/ubuntu/tickflow`, restart `tickflow.service`, and verify readiness before accepting traffic.
3. Measure public root, liveness, and readiness latency; confirm no 502/504 and no service restart.
4. Observe post-close logs for at least two normal polling intervals and confirm realtime/final-retry counters no longer increase.
5. Run the TeaJoin aggregate diagnostic again: current trading date, row count, required nulls, duplicate symbols, and core index coverage.
