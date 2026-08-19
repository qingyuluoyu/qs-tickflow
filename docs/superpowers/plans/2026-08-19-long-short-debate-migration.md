# 个股分析多空辩论迁移计划

## 目标

将 `F:\千户个人\Vibe-Research-main (2).zip` 中的“多空辩论”能力迁移到当前项目，仅在“个股分析”页的“点位提醒”右侧增加入口。保留原能力的核心流程：同一份客观数据底稿、多方立论、空方立论、可选交叉反驳、中立主持归纳分歧与验证清单。

## 边界与兼容策略

- 压缩包只作为只读参考，不复制它的独立 FastAPI 应用、浏览器端 API Key、LLM 配置或数据工具。
- 复用当前项目的标准证券代码（`000001.SZ` / `600000.SH` / `8xxxxx.BJ`）、现有行情仓库、个股洞察数据服务和服务端 AI provider。LLM 密钥、模型、账户隔离和错误处理继续由当前项目负责。
- 新接口放在现有 `stock-analysis` 路由下，使用 NDJSON 流式事件；不新增顶层页面、不改路由导航、不改其它页面和数据库结构。
- 辩论结果只在当前弹窗内显示，不新增持久化表或报告写入，避免引入用户数据归属和迁移风险。用户可关闭弹窗后重新开始。
- 数据源请求有界、串行执行，避免压缩包中并发调用公开财经接口造成限流；缺失数据明确显示并禁止模型臆测。
- 轮数只允许 1 或 2：分别对应 3 或 5 次 AI 阶段调用；后端固定阶段数、输出长度和 provider 超时，前端支持中止。

## 实施工作包

### 1. 先行测试与契约

- 新增后端服务测试，覆盖：标准代码边界、轮次阶段计划、数据空值/元信息判空、底稿缺口标记、事件顺序、模型未配置时的安全失败。
- 新增前端静态契约测试，确认入口文案位于“点位提醒”之后、使用当前选中的标准 symbol、调用新的 stock-analysis debate client，且没有新增全局导航入口。

### 2. 后端事实底稿与辩论服务

- 新增 `backend/app/services/stock_debate.py`。
- 迁移压缩包中的底稿判空、数据缺口、阶段提示词、阶段上下文和事件协议。
- 底稿适配当前项目已有数据：实时/最近行情、估值分位、最新财务指标、近 60 日日 K、资金流、公告、研报、新闻。行情和 K 线优先使用本地仓库；公开洞察数据沿用当前服务的既有适配器。
- 外部数据按现有节流约束串行调用，单节失败不阻断其它节；必须数据全部缺失时不调用模型。

### 3. 现有 stock-analysis API 的窄接口扩展

- 在 `backend/app/api/stock_analysis.py` 新增 `POST /api/stock-analysis/debate`。
- 请求仅接受 `symbol` 和 `rounds`，不接受客户端 API Key、Base URL、模型或任意工具名。
- 返回 `status`、`dossier_progress`、`dossier`、`stage`、`delta`、`stage_done`、`error`、`done` NDJSON 事件；沿用当前服务端 AI provider。
- 不涉及数据库迁移、报告存储、权限模型变更或其它 API 删除。

### 4. 个股分析页隔离入口与弹窗

- 新增 `frontend/src/components/stock-analysis/DebateDialog.tsx`，只负责当前股票的辩论 UI、阶段输出、缺口提示和中止。
- 在 `frontend/src/lib/api.ts` 新增当前 API client 的 `stockDebateStream`，复用已有 POST+ReadableStream NDJSON 解析方式。
- 仅修改 `frontend/src/pages/StockAnalysis.tsx`：增加弹窗状态和“多空辩论”按钮，紧邻放在“点位提醒”右侧；股票切换时关闭并清理上一次请求。
- 不修改其它页面、导航、主题颜色、行情看板、点位提醒逻辑和现有报告存储。

### 5. 验证

- 运行后端新增测试、受影响的 stock-analysis/AI 流测试、Ruff 和前端测试/构建。
- 使用本地浏览器从个股分析选择一只股票，验证入口位置、弹窗、数据底稿进度、AI 未配置错误和中止路径；若未配置真实模型，不伪造真实模型成功结果，也不产生外部模型费用。
- 检查 `git diff --check`、工作区变更范围和服务健康状态。

## 预期修改文件

- `backend/app/services/stock_debate.py`（新增）
- `backend/app/api/stock_analysis.py`（新增同路由下的接口）
- `backend/tests/test_stock_debate.py`（新增）
- `frontend/src/components/stock-analysis/DebateDialog.tsx`（新增）
- `frontend/src/lib/api.ts`（新增 client 与类型）
- `frontend/src/pages/StockAnalysis.tsx`（仅入口/弹窗状态）
- `frontend/tests/stock-analysis-debate-entry.test.mjs`（新增）

## 回滚

删除上述新增组件/服务/测试并撤销 stock-analysis 路由与页面入口即可；没有数据库迁移、外部写操作或持久化数据，不需要数据回滚。
