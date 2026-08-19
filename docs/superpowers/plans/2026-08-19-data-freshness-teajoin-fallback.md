# Data Freshness and Teajoin Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 A 股数据页面明确区分最新交易日、实时缓存、部分覆盖和过期计算结果；对 Teajoin 已提供的数据走既有 provider 抽象，不用静态样例或旧值冒充当日数据。

**Architecture:** 保持现有 provider → 同步服务 → Parquet/DataStore → FastAPI → `api.ts` → React 页面链路。新增的只是数据新鲜度与覆盖状态的显式契约、指数日线兜底的日期标记，以及市场环境的过期提示；不在页面直接读取供应商或本地文件，也不改变 A 股价格、涨跌幅、交易日和复权口径。

**Tech Stack:** Python 3.11+、FastAPI、Polars、Pytest、React/TypeScript、TanStack Query、Vite、现有 Teajoin custom provider。

## Global Constraints

- 所有行情数据必须经过现有 provider 能力和标准化路径；Teajoin 作为已配置 provider 或现有同步路径使用，不新增硬编码供应商调用。
- 2026-08-19 盘后只能把已完成交易日 2026-08-19 标记为最新日线；历史日线可以展示，但必须带 `as_of`/状态，不得显示为实时。
- 346 个未覆盖标的继续区分 inactive、unresolved 和 provider unavailable；不得用上一交易日硬填当日。
- 指数没有实时快照时，允许使用最近指数日 K 作为“日线收盘兜底”，但必须显示来源和日期；不把日线涨跌幅伪装成实时。
- Regime 自动计算默认关闭的现有服务器偏好保持兼容；页面只对过期状态告警，是否开启自动计算由管理员设置决定。
- 每项变更先添加能在旧实现失败的测试，再写实现；不修改用户已有的资产配置和设置页改动。

---

### Task 1: 固化数据新鲜度与 Teajoin 覆盖边界

**Files:**
- Read: `backend/app/services/kline_sync.py`
- Read: `backend/app/data_providers/custom/provider.py`
- Read: `backend/app/api/data.py`
- Modify: `backend/tests/test_pipeline_and_monitor_fixes.py` or focused backend test module

**Interfaces:**
- Consumes: 现有 pipeline job、provider reconciliation 和 `market_data_health` 结构。
- Produces: 对 target date、partial coverage、inactive/unresolved 的回归断言；不改变历史数据。

- [ ] **Step 1: 检查同步入口、provider 路由和已有 health contract。**
- [ ] **Step 2: 为 target date 已覆盖但存在 unresolved 的场景补失败测试。**
- [ ] **Step 3: 为 Teajoin provider 成功、空数据、字段缺失和能力缺失补契约测试。**
- [ ] **Step 4: 运行定向 Pytest，确认旧实现按预期红灯。**

### Task 2: 修复指数日线兜底的可见性

**Files:**
- Read: `backend/app/api/intraday.py`
- Modify: `backend/app/api/intraday.py`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/pages/Indices.tsx`
- Create/Modify: focused backend/frontend regression tests

**Interfaces:**
- Consumes: `/api/intraday/indices`、`/api/index/daily` 当前字段。
- Produces: 统一的 `source`、`as_of`、`is_realtime` 状态；选中指数即使没有实时缓存也显示最近日线收盘，并明确“日线收盘”而非“实时”。

- [ ] **Step 1: 先断言无实时 quote 时 header 不应为静默 `--`，且必须展示日线日期和来源。**
- [ ] **Step 2: 保持响应向后兼容，新增可选状态字段。**
- [ ] **Step 3: 前端将 quote 与 chart 最新行合并，仅在日期相同且来源允许时显示实时标签。**
- [ ] **Step 4: 覆盖 loading、空数据、部分覆盖和 stale 日线状态。**

### Task 3: 对市场环境和数据页显示真实 freshness

**Files:**
- Read: `backend/app/api/regime.py`
- Read: `backend/app/services/regime_builder.py`
- Read: `frontend/src/pages/Regime.tsx`
- Read: `frontend/src/pages/Data.tsx`
- Modify: `backend/app/api/regime.py` only if contract needs a derived status
- Modify: `frontend/src/pages/Regime.tsx`
- Modify: `frontend/src/pages/Data.tsx`
- Modify: `frontend/src/lib/api.ts`
- Create/Modify: focused frontend/backend regression tests

**Interfaces:**
- Consumes: regime coverage/latest and `market_data_health` API contracts.
- Produces: 当 regime 最新日落后于 enriched 最新交易日时，显示“计算滞后/需重算”，并把 Teajoin pipeline 的 partial coverage 和 unresolved count 放到数据页；不自动触发高成本全量重算。

- [ ] **Step 1: 先补过期 regime 和 partial market data 的失败断言。**
- [ ] **Step 2: 增加纯函数式 freshness 判定，按交易日字段比较，不使用自然日猜测。**
- [ ] **Step 3: 接入现有查询与页面状态，明确正常、部分、过期、不可用四类状态。**
- [ ] **Step 4: 确认既有管理员开关和手动重算入口保持可用。**

### Task 4: 真实数据链路回归与发布检查

**Files:**
- Read: changed files and final diff
- No data file changes

**Interfaces:**
- Consumes: 现有 2026-08-19 本地数据、Teajoin 配置和开发服务。
- Produces: 后端定向测试、前端构建/lint、diff 检查和浏览器人工验证结果；若真实源不可用，明确报告而不降级为伪数据。

- [ ] **Step 1: 运行后端定向 Pytest、Ruff 和前端契约测试。**
- [ ] **Step 2: 运行 `pnpm --dir frontend build` 和 `pnpm --dir frontend lint`。**
- [ ] **Step 3: 在 `/data`、`/indices`、`/regime` 检查 2026-08-19 的来源、日期、部分覆盖和过期提示。**
- [ ] **Step 4: 运行 `git diff --check`，复查无静态样例、无供应商硬编码、无无关改动。**
