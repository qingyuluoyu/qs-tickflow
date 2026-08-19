# AI Stream and Data Freshness Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make stock AI, long-short debate, and RPS analysis fail fast with usable cancellation, while showing consistent freshness metadata for sector and ladder data.

**Architecture:** Keep the existing OpenAI-compatible provider and NDJSON contracts. Add bounded time-to-first-event and inactivity handling at the streaming boundary, propagate `AbortSignal` through frontend stream consumers, and render one shared freshness state from each existing `as_of`/`date` field. No database migration or provider replacement is required.

**Tech Stack:** FastAPI, Python async generators, OpenAI-compatible SDK, React 18, TypeScript, Vite, TanStack Query, existing pytest and Node test harness.

## Global Constraints

- Preserve existing user changes and current API paths.
- Do not expose API keys, provider URLs, or model configuration in client requests.
- Preserve existing `meta`, `delta`, `error`, and `done` stream event semantics.
- Do not replace missing current market data with fabricated or zero-valued data.
- Use the existing sky-blue semantic warning palette.

---

### Task 1: Add regression tests for stream liveness and freshness states

**Files:**
- Modify: `backend/tests/test_stock_debate.py`
- Modify: `backend/tests/test_stock_analysis.py` or the existing stock-analysis test module found by `rg`
- Modify: `frontend/tests/stock-analysis-debate-entry.test.mjs`
- Modify: `frontend/tests/layout-navigation.test.mjs` if the freshness helper is tested there

**Interfaces:**
- Tests consume the existing backend async generators and frontend source-level contract tests.
- Tests produce explicit requirements for first-event delivery, bounded stream failure, abort propagation, and stale-date UI copy.

- [ ] **Step 1: Write failing backend tests** for a stream that never yields a provider event and for a debate generator that emits a bounded error event rather than remaining open.
- [ ] **Step 2: Run the targeted pytest commands** and confirm the new assertions fail for the current implementation.
- [ ] **Step 3: Write failing frontend tests** asserting that stock AI/RPS stream calls accept an `AbortSignal`, that working dialogs expose a stop action, and that concept/industry/ladder pages render a stale-data warning when their returned date is older than the current market date.
- [ ] **Step 4: Run the targeted Node tests** and confirm the failures are caused by the missing behavior rather than test setup errors.

### Task 2: Bound the AI streaming boundary and preserve structured errors

**Files:**
- Modify: `backend/app/services/ai_provider.py`
- Modify: `backend/app/services/stock_analyzer.py`
- Modify: `backend/app/services/stock_debate.py`
- Modify: `backend/app/services/concept_rotation_analyzer.py`
- Modify: `backend/app/api/stock_analysis.py` only if the stream wrapper needs cancellation/error logging changes
- Test: `backend/tests/test_stock_debate.py` and the existing AI provider/stock analysis tests

**Interfaces:**
- `stream_ai_events(..., timeout=...)` remains an async iterator of structured events.
- Analyzer streams continue emitting NDJSON event objects; provider and analyzer failures become `error` plus terminal `done` events where the existing consumer expects completion.

- [ ] **Step 1: Add a bounded first-event/inactivity timeout around provider iteration**, using the existing request timeout as the upper bound and a short first-event budget for user feedback.
- [ ] **Step 2: Emit a structured, non-sensitive provider error** with a request identifier and phase (`connecting` or `streaming`) without leaking API keys or full configuration.
- [ ] **Step 3: Ensure analyzer generators flush an initial event before entering slow provider work and always terminate on timeout/error.**
- [ ] **Step 4: Run the targeted backend tests** and confirm the new regression tests pass.

### Task 3: Add cancellation and recovery to all AI dialogs

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/components/stock-analysis/StockAnalysisDialog.tsx`
- Modify: `frontend/src/components/RpsRotationDialog.tsx`
- Modify: `frontend/src/components/stock-analysis/DebateDialog.tsx` only for shared wording or terminal-state consistency
- Test: `frontend/tests/stock-analysis-debate-entry.test.mjs` and any new focused Node test

**Interfaces:**
- `api.stockAnalysisStream(symbol, focus, signal?)` and `api.rotationAnalyzeStream(..., signal?)` accept an optional `AbortSignal` and pass it to `fetch`.
- Working dialogs expose a stop button, abort their own request on close/unmount, and distinguish user cancellation from provider failure.

- [ ] **Step 1: Thread `AbortSignal` through the two API stream functions** without changing existing call sites that omit it.
- [ ] **Step 2: Add per-dialog abort refs and stop handlers**; reset loading state immediately and show a concise “已中止” state.
- [ ] **Step 3: Add a client-side inactivity timeout** that calls the same abort path, so a stalled server cannot leave an unbounded background request.
- [ ] **Step 4: Run focused frontend tests and build**.

### Task 4: Make data freshness visible across dimension pages

**Files:**
- Modify: `frontend/src/pages/ConceptAnalysis.tsx`
- Modify: `frontend/src/pages/IndustryAnalysis.tsx`
- Modify: `frontend/src/pages/LimitUpLadder.tsx`
- Reuse or create: the smallest existing shared freshness/status component under `frontend/src/components/`
- Test: `frontend/tests/layout-navigation.test.mjs` or a focused freshness test

**Interfaces:**
- Consume each page’s existing `rowsQuery.data.date` or `data.as_of` and the existing market-date/freshness API where available.
- Render a warning only when the displayed snapshot is older than the current market date; never fabricate today’s date.

- [ ] **Step 1: Add a deterministic freshness helper test** for current, stale, missing, and non-trading-day cases.
- [ ] **Step 2: Add the shared sky-blue warning presentation** and wire all three pages to their existing date metadata.
- [ ] **Step 3: Preserve valid empty states and explicit source/degraded labels.**
- [ ] **Step 4: Run focused frontend tests and build.**

### Task 5: Release verification

**Files:**
- Inspect only: final diff, status, runtime logs, and browser state

- [ ] **Step 1:** Run backend targeted tests, then full pytest.
- [ ] **Step 2:** Run frontend tests, lint, and production build.
- [ ] **Step 3:** Run health checks and authenticated browser smoke tests for stock analysis, debate stop, stock AI stop/timeout, RPS stop/timeout, concept/industry/ladder freshness warnings, and console errors.
- [ ] **Step 4:** Review `git diff`, `git diff --check`, and `git status` to verify no unrelated files or generated data changed.
- [ ] **Step 5:** Report exact pass/fail results, remaining risks, and whether the release gate is cleared.
