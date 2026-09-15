# Production Freshness, Backtest and AI Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不伪造实时性、不绕过 provider 抽象的前提下恢复当天行情可用性，统一部署回测前后端版本，并让所有 AI 流在超时和空回答时返回真实终态。

**Architecture:** TeaJoin 继续作为历史日K和正式盘后数据的权威来源；新浪仅作为明确标记的盘中展示或盘后临时快照，TeaJoin 后续发布的正式日K按现有 merge-upsert 覆盖临时分区。回测继续只读取持久化 enriched 数据，AI 调用继续通过统一 provider，但补齐工具流首包/停顿超时和测试接口空回答判断。部署采用同一 Git 提交完整构建，不再只热替换单个后端文件。

**Tech Stack:** Python 3.11、FastAPI、Polars、Pytest、React 18、TypeScript、Vite、Docker Compose、Nginx。

## Global Constraints

- TeaJoin 保持正式历史数据权威源；任何跨源降级必须带 `data_source` 和 `is_provisional`，不得静默混写。
- 新浪临时日K仅允许当天盘后使用；后续 TeaJoin 正式日K必须能够无迁移地覆盖。
- 回测不得直接调用 TeaJoin，必须使用 enriched Parquet，并拒绝超过最新 enriched 交易日的请求。
- AI 密钥、数据源密钥和密码不得写入代码、计划、日志或 Git。
- 不覆盖主工作区现有未提交改动；实现只在 `codex/backtest-data-freshness` 隔离工作区进行。
- 生产发布必须来自单一提交；失败时保留当前健康容器并可回滚到发布前镜像。

## Acceptance Matrix

| 编号 | 验收条件 | 证据 |
| --- | --- | --- |
| A1 | 盘中 TeaJoin 无全市场实时快照时，看板可使用明确标注为 `sina.realtime` 的只读快照，且不写入日K分区 | 后端契约测试 + `/api/dashboard` freshness 字段 |
| A2 | 盘后 TeaJoin 尚未发布当天日K时，调度器仍进入管道并写入标记为 `data_source=sina,is_provisional=true` 的当天快照 | 单元测试 + 服务器 Parquet 抽样 |
| A3 | TeaJoin 正式日K标准化后带 `data_source=teajoin,is_provisional=false`，可覆盖同日临时记录 | provider/repository 回归测试 |
| A4 | 日K与 enriched 的最新日期达到最近已完成交易日，且数据源失败、空数据、过期状态彼此区分 | `/api/data/status`、仓库查询、pipeline job 终态 |
| B1 | 前端默认回测结束日等于最新 enriched 日期，不能选择更晚日期 | 前端构建 + 页面检查 |
| B2 | 后端省略结束日时使用最新 enriched 日期；显式超出范围返回 422，不创建回测任务 | API 测试 |
| B3 | 至少一项内置策略在可用区间返回成功终态；零交易时仍返回选股/候选统计，不伪装为数据错误 | 服务器 SSE 冒烟测试 |
| C1 | 普通 AI 流和工具 AI 流均具备首包 20 秒、连续停顿 45 秒的默认保护，并关闭未完成流 | 异步超时回归测试 |
| C2 | AI 测试接口收到空回答时返回 `ok=false` | API/service 测试 |
| C3 | 聊天、策略生成、个股分析、多空辩论、财务分析、市场复盘、概念轮动逐项产生 `done` 或明确 `error`，记录首包和总耗时 | 服务器串行验收记录 |
| D1 | 后端、前端和静态资源来自同一 Git 提交；容器重建后补丁不丢失 | 发布提交 SHA + 容器内文件校验 |
| D2 | `/health`、`/api/health`、域名 HTTPS 均通过；Nginx 保持 80→443，3018 不作为公网入口 | curl、ss、docker compose ps |
| D3 | 发布失败不影响旧容器；回滚后健康检查恢复 | 发布前镜像标签和回滚命令演练 |

---

### Task 1: Data provenance and post-close fallback reachability

**Files:**
- Modify: `backend/app/data_providers/normalizer.py`
- Modify: `backend/app/parquet.py`
- Modify: `backend/app/indicators/pipeline.py`
- Modify: `backend/app/services/sina_snapshot.py`
- Modify: `backend/app/jobs/daily_pipeline.py`
- Test: `backend/tests/test_data_contract.py`
- Test: `backend/tests/test_pipeline_and_monitor_fixes.py`

**Interfaces:**
- Produces: canonical columns `data_source: Utf8` and `is_provisional: Boolean` on daily and enriched storage.
- Produces: `provider_snapshot_ready_for_pipeline(provider_date, target, now) -> bool`.

- [ ] **Step 1: Write failing provenance tests.** Assert `normalize_daily(..., source="teajoin")` emits `teajoin/false`, and `fetch_spot_daily()` emits `sina/true`.
- [ ] **Step 2: Run the focused tests and confirm the old implementation fails because the columns are absent.**
- [ ] **Step 3: Add the two additive storage columns and preserve them through enriched storage selection.** Existing Parquet remains readable through `missing_columns="insert"`.
- [ ] **Step 4: Write a failing scheduler test.** Assert a missing TeaJoin target is allowed after 15:10 for the current target date, but remains deferred before close or for an older target.
- [ ] **Step 5: Implement the pure readiness helper and use it in scheduled retries and boot catch-up.**
- [ ] **Step 6: Run provider, pipeline, repository and indicator tests.**

### Task 2: Display-only intraday fallback and backtest contract

**Files:**
- Modify: `backend/app/main.py`
- Already modified: `backend/app/api/backtest.py`
- Already modified: `frontend/src/pages/backtest/StrategyBacktest.tsx`
- Test: `backend/tests/test_dashboard_preload.py`
- Test: `backend/tests/backtest/test_backtest_data_coverage.py`

**Interfaces:**
- Consumes: `make_dashboard_failover_fetcher(..., allow_cross_source_fallback=True)`.
- Produces: source-labelled display snapshot; no dashboard fallback persistence.
- Produces: backtest coverage error contract already introduced in commit `2128f8b`.

- [ ] **Step 1: Add/retain a failing production-composition assertion showing the dashboard fallback is disabled.**
- [ ] **Step 2: Enable the existing source-labelled, display-only failover in application startup.** Do not change `QuoteService` persistence fail-closed behavior.
- [ ] **Step 3: Re-run dashboard and backtest API tests.**
- [ ] **Step 4: Build the frontend so the latest-enriched date restriction ships with the backend coverage check.**

### Task 3: AI stream bounds and truthful test endpoint

**Files:**
- Modify: `backend/app/services/ai_provider.py`
- Modify: `backend/app/api/strategy.py`
- Test: `backend/tests/test_ai_stream_contract.py`
- Test: `backend/tests/test_ai_follow_up.py`

**Interfaces:**
- Extends: `stream_ai_text_with_tools(..., first_event_timeout=None, inactivity_timeout=None)` without breaking existing callers.
- Changes: `/api/strategies/ai/test` returns `ok=false` and `error="AI 返回空内容"` for empty/whitespace responses.

- [ ] **Step 1: Add failing hanging/stalling tool-stream tests and verify RED.**
- [ ] **Step 2: Apply the existing first-event/inactivity timeout pattern to the tool stream and always close it in `finally`.**
- [ ] **Step 3: Add a failing empty-response test for the AI test endpoint and verify RED.**
- [ ] **Step 4: Implement the minimal empty-response guard and verify GREEN.**
- [ ] **Step 5: Run the AI stream, follow-up, chat-tool and feature contract tests.**

### Task 4: Release, deployment and production acceptance

**Files:**
- Update: this plan with actual verification results.
- No runtime data or secret files are committed.

**Interfaces:**
- Produces: one Git commit SHA, one Docker image tagged with the pre-release image ID, and a server acceptance record.

- [ ] **Step 1: Run backend focused suites, Ruff, frontend tests/build and `git diff --check`.**
- [ ] **Step 2: Review the final diff for unrelated files, secrets and silent vendor mixing; commit and push the branch.**
- [ ] **Step 3: On the server, record the current image ID and checksums, download the exact commit, preserve `.env` and `data/`, then build without stopping the healthy container.**
- [ ] **Step 4: Replace the container only after the image builds; poll `/api/health` until ready and automatically roll back on failure.**
- [ ] **Step 5: Verify A1–D3 with repository queries, backtest SSE, serial AI feature tests, HTTPS health checks and container/source SHA evidence.**
- [ ] **Step 6: Record passed, failed and unexecuted acceptance items honestly; never convert an unavailable upstream into a passing result.**
