# AI Reasoning Visibility and Complete Answers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Separate provider reasoning from the user-facing answer in review and stock-analysis conversations, keep reasoning collapsed until explicitly opened, and continue bounded length-stopped responses so the visible answer is complete whenever the provider can complete it.

**Architecture:** Add a backward-compatible structured event stream in `ai_provider` that distinguishes reasoning, answer deltas, continuation status, and completion metadata. The two analysis services will emit the new events while retaining the existing `meta/delta/error/done` event names; frontend stores will keep reasoning separate from answer and expose completion metadata to the existing dialogs. Reports will persist optional reasoning and completion flags so history behaves the same as a live task.

**Tech Stack:** Python 3.11, FastAPI NDJSON streaming, OpenAI-compatible async SDK, React 18, TypeScript, Node test runner, pytest.

## Global Constraints

- Preserve the existing NDJSON endpoints and old `delta` consumers.
- Never expose reasoning by default; label it as model working notes when expanded.
- Continuation is bounded (at most two follow-up requests) and must not loop indefinitely.
- Preserve user-scoped report storage and existing report fields; new fields are optional for old JSON files.
- Do not log API keys, prompts, report contents, or reasoning text.

---

### Task 1: Define and test structured AI stream events

**Files:**
- Modify: `backend/app/services/ai_provider.py`
- Test: `backend/tests/test_ai_provider.py`

**Interfaces:**
- Produces `stream_ai_events(messages, temperature, max_tokens, timeout, max_continuations)` yielding dictionaries with `type` `reasoning_delta`, `delta`, `continuation`, or `done`.
- Keeps `stream_ai_text` as a compatibility wrapper that yields answer text only.

- [x] **Step 1: Write failing tests** for reasoning/content separation, `finish_reason=length` continuation, and bounded incomplete completion metadata using mocked OpenAI streams.
- [x] **Step 2: Run the focused pytest file and confirm the new tests fail** because the structured event helper does not yet exist.
- [x] **Step 3: Implement provider event parsing** for `delta.content`, `delta.reasoning`, `delta.reasoning_content`, and chunk `finish_reason`; add a bounded continuation request that sends the accumulated assistant answer and asks only for the missing continuation.
- [x] **Step 4: Keep `stream_ai_text` behavior unchanged** by forwarding only `delta` content and suppressing reasoning/status events.
- [x] **Step 5: Run the focused provider tests and confirm they pass.**

### Task 2: Wire review and stock-analysis services to the new protocol

**Files:**
- Modify: `backend/app/services/market_recap.py`
- Modify: `backend/app/services/stock_analyzer.py`
- Modify: `backend/app/jobs/daily_pipeline.py`
- Test: `backend/tests/test_ai_stream_contract.py`

**Interfaces:**
- Both analyzers emit answer `delta` events only for the final answer, reasoning in `reasoning_delta`, continuation status, and a `done` event containing `complete`, `truncated`, `finish_reason`, and continuation count.
- Existing scheduled review retry treats `complete=false` as a failed attempt and can use its existing bounded retry path.

- [x] **Step 1: Write failing service contract tests** using monkeypatched provider events and minimal fake repository/data builders.
- [x] **Step 2: Run the focused service tests and confirm they fail** because analyzers currently call `stream_ai_text` and emit only `delta/done`.
- [x] **Step 3: Switch both services to `stream_ai_events`** without changing their prompts or market/financial data assembly.
- [x] **Step 4: Update scheduled review handling** to retry a stream that ends with `complete=false` instead of archiving it as successful.
- [x] **Step 5: Run service and existing market/stock AI tests.**

### Task 3: Persist completion metadata and optional reasoning

**Files:**
- Modify: `backend/app/api/financials.py` only if the shared report contract is extended for consistency; otherwise leave it unchanged.
- Modify: `backend/app/api/stock_analysis.py`
- Modify: `backend/app/api/market_recap.py`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/aiReportStore.ts` only if financial reports are included; otherwise leave it unchanged.
- Modify: `frontend/src/lib/stockAnalysisStore.ts`
- Modify: `frontend/src/lib/reviewStore.ts`

**Interfaces:**
- Save payloads accept optional `reasoning`, `complete`, and `truncated` fields while old clients remain valid.
- Existing JSON report stores continue reading records without the new fields.

- [x] **Step 1: Add failing contract assertions** for new stream fields and optional report fields.
- [x] **Step 2: Implement Pydantic/API and frontend type additions** with backward-compatible defaults.
- [x] **Step 3: Accumulate reasoning separately in both stores**, carry completion metadata, and save it with the report after a complete stream.
- [x] **Step 4: Refuse silent success for a truncated stream**; keep the answer visible and mark the task incomplete with a retryable message.
- [x] **Step 5: Run backend contract tests and TypeScript typecheck.**

### Task 4: Add collapsed reasoning UI and complete-answer status

**Files:**
- Modify: `frontend/src/components/stock-analysis/StockAnalysisDialog.tsx`
- Modify: `frontend/src/pages/Review.tsx`
- Test: `frontend/tests/ai-reasoning-ui.test.mjs`

**Interfaces:**
- Reasoning is hidden initially and revealed only by an explicit button/details control labelled “思考过程（模型草稿）”.
- The Markdown answer always renders from the answer-only `content` field.
- A non-complete stream shows a clear retry/incomplete status instead of pretending the answer is complete.

- [x] **Step 1: Write failing frontend source-contract tests** for separate reasoning state, a collapsed control, and complete/truncated rendering.
- [x] **Step 2: Run the Node tests and confirm failure.**
- [x] **Step 3: Implement the controls** with local open state reset when the task/report changes; keep history reasoning optional and closed by default.
- [x] **Step 4: Add the same rendering to the review report panel**, preserving copy/download of the answer only.
- [x] **Step 5: Run frontend tests and build.**

### Task 5: Full verification and runtime smoke test

**Files:**
- No additional source files; inspect the final diff and generated plan only.

- [x] **Step 1: Run targeted backend tests and the full backend suite.**
- [x] **Step 2: Run all frontend Node tests, TypeScript build, and Vite production build.**
- [x] **Step 3: Run `git diff --check` and verify no sensitive data or unrelated files were changed.**
- [x] **Step 4: Check `/health`, `/openapi.json`, and the frontend root on the running local servers.**
- [x] **Step 5: Report actual pass/fail results, compatibility, cost/latency impact, and remaining provider-specific risks.**

