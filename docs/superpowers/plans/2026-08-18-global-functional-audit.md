# 全局功能集中测试与看板数据审计计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不破坏账户隔离、数据源插件化和历史页面的前提下，验证全局功能的可用性、延迟与数据新鲜度，并让看板回到原始本地 enriched 聚合路径；只有 TeaJoin 返回校验通过的当日实时快照时才允许覆盖原始结果。

**Architecture:** 恢复原项目基于本地 enriched 快照的看板聚合路径；看板专用预加载器仅在后台读取 TeaJoin 实时快照，用于通过日期、字段和行数校验后覆盖本地结果。实时响应为空、失败或不是当日时，保持原始本地结果并返回来源、交易日、状态和延迟元数据；HTTP 请求不再同步调用 TeaJoin daily。

**Tech Stack:** FastAPI、Polars、Pydantic、TeaJoin custom provider、TanStack Query、Vite、pytest、Ruff。

## 全局约束

- 不回退或删除当前用户隔离、策略管理、资讯弹窗和 TeaJoin provider 适配；只允许按证据修复看板和验证链路。
- 市场数据必须通过 provider 契约进入看板；不能在 API 或前端直接拼接 TeaJoin 响应。
- 盘中日线只允许使用上一完整交易日；盘中当前日只允许使用实时快照，且必须标明 `snapshot_kind` 和 `realtime_status`。
- 上游空数据、超时、字段缺失和日期超前必须区分，不得默认零值或伪装成今日数据。
- 每个测试账户的自选、偏好、策略、资讯摘要和报告必须隔离；公共行情缓存不得包含用户字段。
- 不提交 `data/`、密钥、Token、用户数据和临时诊断输出。

---

### Task 1: 原始版与当前版调用链差异审计

**Files:**
- Reference: `F:/千户个人/tickflow-stock-panel-main (2).zip`
- Inspect: `backend/app/api/overview.py`
- Inspect: `backend/app/services/market_overview_builder.py`
- Inspect: `backend/app/services/market_overview_preloader.py`
- Inspect: `backend/app/main.py`
- Inspect: `frontend/src/pages/Dashboard.tsx`

- [x] 解压原始压缩包到临时目录并确认原始版本没有 `data/data_sources/teajoin.yaml` 和看板预加载器。
- [x] 对比原始/current `build_market_overview`：非看板实时路径的 breadth、amount、limit、activity、trend 和四榜数值一致；概念/行业排名仅增加了 `source_field` 元数据。
- [x] 记录当前真实源证据：TeaJoin daily 返回 5539 行、最新日期 2026-08-17、约 1.7 秒；TeaJoin realtime HTTP 200 但 `data.items=[]`，约 1.1 秒。
- [x] 记录当前看板证据：预加载返回 `teajoin.daily`、状态 `empty`、日期 2026-08-17、约 2.9 秒；聚合约 1.9 秒。

### Task 2: 看板实时/日线日期口径修复

**Files:**
- Modify: `backend/app/services/market_overview_preloader.py`
- Modify: `backend/app/services/market_overview_builder.py`
- Modify: `backend/app/api/overview.py`
- Test: `backend/tests/test_market_overview_freshness.py`
- Test: `backend/tests/test_dashboard_preload.py`

**接口契约:**

- `DashboardSnapshot.status`: `success | empty | provider_unavailable | error`
- `DashboardSnapshot.kind`: `{provider}.realtime | {provider}.daily | persisted.enriched`
- `data_freshness.realtime_rows`: 只表示本轮 realtime 实际行数，不得复用 daily snapshot 行数。
- `data_freshness.snapshot_date`: 实际用于统计的交易日。
- 盘中 `daily_date` 为上一完整交易日；只有 `realtime` 非空且通过字段/日期校验时才允许 `snapshot_kind={provider}.realtime`。

- [x] 为“realtime 返回 200 空表”写失败测试：状态为 `empty`、实时行数为 0、看板统计日期仍为上一完整交易日并标记 `is_stale`，不能把 daily 行数填到 `realtime_rows`。
- [x] 修复预加载状态与行数来源，保持上一份有效快照但更新本轮 realtime 状态。
- [ ] 为 provider 返回未来日期、缺少 `symbol/close/date`、空表分别增加失败路径测试。（已覆盖未来日期、缺少 close、空表；缺少 date 仍按实时接口契约自动补当前交易日。）
- [x] 修正现有未来日期测试的时间注入边界，使模拟交易日不依赖宿主机当前日期。
- [x] 运行看板定向测试和 provider 契约测试，确认原始本地 enriched 路径不变。

### Task 3: 看板延迟与请求并发验证

**Files:**
- Test: `backend/tests/test_dashboard_preload.py`
- Test: `backend/tests/test_market_overview_freshness.py`
- Inspect: `backend/app/services/market_overview_preloader.py`
- Inspect: `frontend/src/pages/Dashboard.tsx`

- [x] 验证 30 秒预加载周期内 provider 请求单飞，不允许 API 请求再次同步调用外部源。
- [x] 验证预加载失败保留上一有效快照，且不会把状态重置成成功。
- [ ] 测量同一环境下：provider 请求耗时、预加载耗时、`/api/overview/market` 聚合耗时和前端首屏接口数。（已完成 provider、预加载、服务层聚合和浏览器首屏人工检查；带认证的 HTTP 聚合耗时及完整资源计数待补。）
- [ ] 若出现超过 5 秒的请求，只优化重复读取/重复网络调用，不通过增加超时或静默重试掩盖数据源故障。

### Task 4: 全局功能回归与账户隔离

**Files:**
- Inspect/test all affected backend API and service tests.
- Test: `backend/tests/test_account_e2e.py`
- Test: `backend/tests/test_user_data_isolation.py`
- Test: `backend/tests/test_news_account_isolation.py`
- Test: `backend/tests/test_provider_data_boundary.py`

- [x] 运行完整后端测试，记录所有失败并按 P0/P1/P2 分类。
- [x] 验证注册、登录、切换、注销后自选/策略/偏好/资讯互不串号。
- [x] 验证 TeaJoin provider 缺能力、空响应、字段错误、超时和失败重试均 fail-closed。
- [x] 验证 stock analysis、financials、kline、screener、strategy、review、data 页面仍使用各自原有契约，不被看板专用实时路径影响。

### Task 5: 前端构建和人工验收

**Files:**
- Inspect: `frontend/src/pages/Dashboard.tsx`
- Inspect: `frontend/src/lib/api.ts`
- Inspect: `frontend/src/lib/queryKeys.ts`

- [x] 执行 `pnpm build` 和受影响页面 ESLint。
- [ ] 人工检查看板加载、实时为空、旧快照、恢复实时源、概念/行业弹窗、四榜股票名称、窄屏滚动和浅色主题。
- [ ] 人工检查浏览器刷新/切换账户后没有旧账户 Query 缓存泄漏。

### Task 6: 回滚与发布判定

- [ ] 若实时修复未通过，保留 `dashboard_live` 开关关闭路径，恢复原本地 enriched 看板，不回退整个项目。
- [ ] 发布前确认后端完整测试、前端构建、数据源契约测试和人工验收全部通过。
- [ ] 汇报实际命令、耗时、数据日期、失败状态、兼容影响和剩余风险；未验证项目明确列出。

## 当前审计结论（本轮实测）

- 本轮已修正未来日期测试的时间注入，新增实时行数口径、provider 异常、缺少收盘价、非当日实时快照和本地回退回归测试；完整后端结果为 `835 passed, 6 warnings`。
- 看板已回退到原始 enriched 聚合：TeaJoin daily 仅作为状态探测，不再替换本地统计；只有 `kind=*.realtime`、状态成功、行数大于 0 且 `snapshot_date == cn_today()` 才能覆盖原始结果。
- 当前真实 TeaJoin 结果仍是：daily 5539 行、最新交易日 2026-08-17；realtime HTTP 200 但空表，预加载状态 `empty`、`realtime_rows=0`，看板明确标记 `is_stale=true`，没有把日线行数伪装成实时行数。
- 同一环境实测预加载约 3.25 秒、看板聚合约 1.71 秒；无证据表明请求路径存在超过 5 秒的同步外部调用。前端采用后台预加载 + 30 秒轻量刷新，不在浏览器请求中重复拉 TeaJoin。
- 未完成项：TeaJoin realtime 空响应的接口参数/交易时段契约仍需供应商侧确认；缺少 symbol/close/date 的专门失败用例和浏览器人工验收仍待下一轮。
