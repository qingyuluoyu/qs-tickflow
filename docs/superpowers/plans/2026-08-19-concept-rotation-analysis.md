# 概念涨幅轮动分析与策略指南入口调整实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复概念涨幅轮动“生成分析”链路的真实失败原因，并从策略创建弹窗移除“策略开发指南”入口，保持轮动数据口径、AI 生成能力和既有接口兼容。

**Architecture:** 先用后端异步服务测试覆盖完整的分析流边界：轮动矩阵已有数据、市场概览失败降级、AI 流正常输出与 AI 异常输出。修复限定在分析流的实际根因位置；前端仅删除两个外链入口，不改变策略生成请求和运行时精简指南。

**Tech Stack:** Python 3.11+, FastAPI, pytest, Polars, React 18/19, TypeScript, pnpm。

## Global Constraints

- 保持 `build_rps_rotation` 的概念/行业及涨幅小数口径不变。
- 不把模型自由文本作为控制协议；分析流继续使用既有 NDJSON 事件结构。
- 不删除 `strategy-guide-compact.md`，AI 策略生成仍需该运行时提示词。
- 不修改用户运行时数据、数据源配置、数据库或无关 UI。
- 仅在实际验证通过后报告完成状态。

### Task 1: 覆盖并修复概念轮动分析流

**Files:**
- Modify: `backend/app/services/concept_rotation_analyzer.py`
- Test: `backend/tests/test_concept_rotation_analyzer.py`

**Interfaces:**
- Consumes: `build_rps_rotation(repo, days, kind, level)`, `build_market_overview(repo, quote_service, depth_service)` and `app.services.ai_provider.stream_ai_text`.
- Produces: `analyze_rotation_stream(...)` yielding NDJSON strings with `meta`, `delta`, `error`, and `done` events.

- [ ] **Step 1: Write the failing regression tests**

  Add tests that feed a non-empty concept matrix and a fake AI stream, then assert the stream emits `meta`, the AI `delta`, and `done`; add a second test asserting market-overview failure still allows AI output. Patch only external providers/services, not the tested prompt assembly and event sequencing.

- [ ] **Step 2: Run the tests before the fix**

  Run:

  ```powershell
  cd backend
  uv run pytest tests/test_concept_rotation_analyzer.py -q
  ```

  Expected: the new regression test fails at the currently broken analysis boundary, or exposes the exact exception/empty event sequence from the existing implementation.

- [ ] **Step 3: Implement the smallest root-cause fix**

  Trace the failure from `analyze_rotation_stream` through matrix loading, market-overview assembly, AI configuration and stream iteration. Change only the failing boundary, preserve the existing event names/messages, and keep deterministic financial calculations outside the model.

- [ ] **Step 4: Run the focused tests after the fix**

  Run:

  ```powershell
  cd backend
  uv run pytest tests/test_concept_rotation_analyzer.py tests/test_rps_rotation.py -q
  uv run ruff check app/services/concept_rotation_analyzer.py tests/test_concept_rotation_analyzer.py tests/test_rps_rotation.py
  ```

  Expected: all focused tests pass with no new Ruff findings.

### Task 2: Remove the strategy guide UI entry

**Files:**
- Modify: `frontend/src/components/screener/StrategyBuilderDialog.tsx`

**Interfaces:**
- Consumes: existing AI/custom strategy-builder tabs and `strategyBuildStream` behavior.
- Produces: the same strategy-builder dialog without the two “策略开发指南” external links.

- [ ] **Step 1: Remove only the two guide link elements**

  Keep the tab descriptions and all strategy generation, validation, save, draft persistence, and custom-template behavior unchanged. Keep `FileText` if it remains used by the custom tab.

- [ ] **Step 2: Build the frontend**

  Run:

  ```powershell
  cd frontend
  pnpm build
  ```

  Expected: the TypeScript/Vite production build exits with code 0.

### Task 3: Final scope and regression verification

- [ ] **Step 1: Check the final diff and status**

  Run:

  ```powershell
  git diff --check
  git status --short
  git diff -- backend/app/services/concept_rotation_analyzer.py backend/tests/test_concept_rotation_analyzer.py frontend/src/components/screener/StrategyBuilderDialog.tsx
  ```

  Expected: only the analysis fix, its regression test, and the requested guide-entry removal are present; no secrets, runtime data, debug output, or unrelated formatting changes appear.

- [ ] **Step 2: Report compatibility and remaining risk**

  Confirm that the public `/api/rps/rotation-analyze` request and NDJSON event contract are unchanged, the strategy prompt runtime file remains available, and any unexecuted live-provider/manual browser verification is explicitly listed.
