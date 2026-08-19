# Dashboard A-Share Session Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the dashboard choose data by Beijing-time A-share session: current-day realtime only during the active market session, and the latest completed provider daily snapshot during lunch breaks, after close, weekends, and holidays.

**Architecture:** Keep all provider I/O in the existing background preloader. The preloader will select the configured realtime/daily provider, reject data outside the allowed session/date boundary, and carry session metadata with the immutable snapshot. The overview builder will consume a current closed daily snapshot when available, otherwise retain the latest local completed partition and expose the exact freshness state.

**Tech Stack:** FastAPI/Python, Polars, pytest, existing custom provider contract, React/TanStack Query dashboard.

## Global Constraints

- A股交易时段固定按北京时间 09:30–11:30、13:00–15:00；服务器时区不得影响业务口径。
- 盘中只使用当前交易日实时快照；盘前、午休、收盘后和休市不得把旧实时响应标记成今日盘中数据。
- 完整日线指标不得使用未收盘的当前日 K 线。
- 所有 provider 数据经过日期、字段和空数据校验；无法确认时 fail-closed 并保留最近有效快照。
- HTTP 看板请求不执行全市场同步；用户私有缓存和数据隔离保持不变。

---

### Task 1: Make the background snapshot session-aware

**Files:**
- Modify: `backend/app/services/market_overview_preloader.py`
- Modify: `data/data_sources/teajoin.yaml`
- Test: `backend/tests/test_dashboard_preload.py`

**Interfaces:**
- `make_dashboard_snapshot_fetcher()` continues returning `Callable[[], DashboardSnapshot]`.
- `DashboardSnapshot.market_as_of` carries `session`, `trade_date`, `intraday_date`, `cutoff_time`, `is_partial`, and `date_verified`.

- [x] Add a single active-session predicate using `MarketAsOf.session`; do not call the configured realtime endpoint in `PREOPEN`, `LUNCH`, `POST_CLOSE`, or `CLOSED`.
- [x] Normalize optional realtime `date`/`trade_date` and timestamp fields to Beijing dates; preserve the existing provider contract when the source omits them, but never accept a frame whose explicit date is in the future or not the current session date.
- [x] Keep the latest completed daily provider frame in the existing throttled cache and mark it as a closed snapshot with session metadata.
- [x] Map TeaJoin realtime `trade_date`/`date`/`timestamp` fields when present without changing required fields or request parameters.
- [x] Add tests for active-session realtime, preopen/post-close realtime suppression, future-date rejection, and daily exact-date selection.

### Task 2: Route the application preloader through the selected provider

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_dashboard_preload.py`

**Interfaces:**
- App state still exposes one `market_overview_preloader`; existing HTTP callers remain unchanged.

- [x] Select `make_dashboard_snapshot_fetcher()` when the configured provider exposes realtime/daily capabilities.
- [x] Keep the existing Sina fetcher only as an explicit fallback when no configured custom realtime provider is available, and only during active sessions.
- [x] Ensure provider selection is evaluated inside the fetch cycle so settings changes do not require a process restart.

### Task 3: Consume completed daily snapshots and expose freshness

**Files:**
- Modify: `backend/app/services/market_overview_builder.py`
- Test: `backend/tests/test_market_overview_freshness.py`

**Interfaces:**
- `build_market_overview()` keeps its current parameters and response shape; only `data_freshness` gains/uses compatible metadata.

- [x] Accept a non-partial current-day daily snapshot after close, and the latest provider-confirmed completed snapshot while closed, only when it is not newer than the resolved market date.
- [x] Keep local enriched data as the fallback when the provider snapshot is empty, failed, partial, or from another date.
- [x] Set `calendar_basis` and `is_stale` from the accepted snapshot/session instead of assuming every weekday is open.
- [x] Add regression tests for open, lunch, post-close, weekend/holiday-style closed, stale, and future-date snapshots.

### Task 4: Verify the dashboard data boundary

**Files:**
- Modify: `docs/custom-data-source.md` (only if the realtime date metadata contract changes)

- [x] Run the targeted preloader/freshness tests and the full backend test suite.
- [x] Run `pnpm build` and `pnpm lint -- --quiet` because the dashboard contract is consumed by TypeScript types.
- [x] Check `git diff --check`, health endpoint, and the live preloader snapshot for session/date metadata.

## Rollback

The change is code/config compatible and does not alter persisted schemas. Reverting the preloader and builder changes restores the current local fallback; existing snapshot metadata remains optional and is ignored by older callers.
