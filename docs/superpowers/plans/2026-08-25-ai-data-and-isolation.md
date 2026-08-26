# AI 数据与账户隔离修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让财务分析、个股分析和问 AI 使用同一份 TeaJoin 优先的数据口径，识别不完整回答，并保证浏览器账户切换时 AI 会话隔离。

**Architecture:** 保留现有模块化单体结构，扩展 `financial_view` 作为财务数据适配边界；所有 AI 流统一使用可标识完成状态的事件协议。问 AI 的浏览器状态通过已有账户存储命名空间隔离，后端继续使用现有用户工作区。

**Tech Stack:** FastAPI、Polars、OpenAI-compatible streaming、React/TypeScript、Vitest/Pytest。

## Global Constraints

- 不修改无关页面和现有用户数据文件。
- TeaJoin 数据必须保留供应商、报告期、公告日期和采集时间语义；不以默认零值掩盖缺失。
- 不保存 `complete=false` 或 `truncated=true` 的 AI 报告。
- 所有账户切换必须中止旧账户的前端 AI 请求并清理内存状态。

---

### Task 1: 统一财务读取并修复工具表名

**Files:**
- Modify: `backend/app/services/financial_view.py`
- Modify: `backend/app/services/stock_analyzer.py`
- Modify: `backend/app/services/chat.py`
- Modify: `backend/app/services/ai_tools.py`
- Test: `backend/tests/test_ai_financial_data_source.py`

- [ ] 写测试：本地存在旧财务行且 TeaJoin 返回更新行时，统一读取器选择更新数据；本地完全缺失时仍调用 TeaJoin；`balance_sheet` 工具表名可用。
- [ ] 运行新增测试并确认在修改前失败。
- [ ] 扩展统一读取器：读取本地后比较最新 `period_end`/`announce_date`，必要时请求当前自定义 provider；统一规范化和关闭 request-scoped provider。
- [ ] 让个股分析、问 AI 底稿和 `query_financials` 调用统一读取器；将工具枚举和执行统一为 `balance_sheet`。
- [ ] 运行新增测试及现有财务视图、AI follow-up 测试。

### Task 2: 财务分析和问 AI 的完整性协议

**Files:**
- Modify: `backend/app/services/financial_analyzer.py`
- Modify: `backend/app/services/ai_provider.py`
- Modify: `backend/app/services/chat.py`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/aiReportStore.ts`
- Modify: `frontend/src/lib/askAiStore.ts`
- Test: `backend/tests/test_ai_completion_contract.py`

- [ ] 写测试：财务模型以 `length` 结束时产生 `continuation` 和 `truncated`；问 AI 工具循环达到上限时产生不完整标记；正常停止仍为完整。
- [ ] 运行测试并确认在修改前失败。
- [ ] 财务分析改用结构化流事件，允许有限续写，透传 `complete/truncated/finish_reason`。
- [ ] 问 AI 工具流透传 finish reason，达到轮次或工具上限时明确 `complete=false`，不静默发送完整状态。
- [ ] 前端处理完整性字段，异常结束不归档、不显示为完整报告，并显示重试提示。
- [ ] 运行新增测试及 `test_ai_stream_contract.py`。

### Task 3: 问 AI 前端账户隔离

**Files:**
- Modify: `frontend/src/lib/askAiStore.ts`
- Modify: `frontend/src/components/AuthGate.tsx`
- Test: `frontend/src/lib/askAiStore.test.ts`

- [ ] 写测试：用户 A 与用户 B 同一股票的会话键不同；切换账户会中止任务、清理内存任务和对话框。
- [ ] 运行测试并确认在修改前失败。
- [ ] 增加 `resetAccountState()`，使用当前账户命名空间存储问 AI 对话；在登录、退出时调用。
- [ ] 补充旧版本未命名空间记录的兼容读取策略，禁止跨账户复用。
- [ ] 运行前端测试和 TypeScript 构建。

### Task 4: 日期与发布验证

**Files:**
- Modify: `backend/app/services/ai_tools.py`
- Test: `backend/tests/test_ai_market_date.py`

- [ ] 写测试：周末/节假日问 AI 市场工具返回最近真实交易日，而不是当天空快照。
- [ ] 运行测试并确认在修改前失败。
- [ ] 复用现有 `resolve_market_as_of`/交易日口径，并在工具结果中返回 `as_of`、数据源和新鲜度。
- [ ] 运行 AI 相关后端测试、完整后端测试、前端构建和 `git diff --check`。
