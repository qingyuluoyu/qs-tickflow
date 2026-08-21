<div align="center">

# 清数智算 · A 股智能投研工作台

**TickFlow Stock Panel**

面向 A 股研究、选股、回测、监控和资产配置教育的自托管工作台

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/Python-%E2%89%A53.11-blue.svg)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev/)
[![Data](https://img.shields.io/badge/Data-TickFlow%20%2B%20TeaJoin-00b386.svg)](https://tickflow.org/)
[![Deploy](https://img.shields.io/badge/Deploy-Docker-2496ed.svg)](./Dockerfile)
[![Live site](https://img.shields.io/badge/Live-qszscloud.online-8b5cf6.svg)](https://www.qszscloud.online/)

[线上入口](https://www.qszscloud.online/) · [核心功能](#核心功能) · [快速开始](#快速开始) · [配置](#配置) · [完整文档](#完整文档)

</div>

> 本项目用于金融研究、数据分析和投资教育，不构成任何投资建议。回测结果不代表未来收益，历史数据不代表未来表现，A 股及其他金融资产均存在本金损失风险。

## 项目简介

TickFlow Stock Panel 是一个本地优先、可自托管的 A 股智能投研工作台。项目把行情数据、指标计算、策略筛选、历史回测、板块分析、市场环境、实时监控、盘后复盘、可选 AI 能力和资产配置教育整合到同一套 React + FastAPI 应用中。

它解决的不是“再做一个行情展示页”，而是把研究过程组织成一条可追溯链路：

```text
数据源 / provider
  → 字段、代码、单位和时间标准化
  → 本地 DataStore / DuckDB / Parquet
  → 指标与 enriched 数据
  → 选股 / 回测 / 监控 / 分析 / 复盘
  → FastAPI API、SSE、NDJSON
  → React 工作台
```

当前版本的主要特点：

- **数据源可替换**：支持 TickFlow 官方 SDK、TeaJoin 服务器级 provider 和自定义数据源，不把供应商响应直接暴露给页面。
- **确定性计算**：指标、选股、回测、涨跌停和风险结果由程序计算；AI 只负责解释、总结、研究编排和问答。
- **A 股规则明确**：回测和数据处理区分交易日、交易时间、T+1、复权、涨跌停、手续费、滑点和公告可获得时间。
- **账户数据隔离**：不同账户的自选、策略、监控规则、报告、AI Key 和偏好相互隔离。
- **本地优先部署**：运行数据保存在部署者自己的 `data/` 目录，可通过 Docker 单容器部署，也可以直接源码运行。
- **桌面端优先**：工作台采用固定侧边导航、图表卡片和大屏布局，适合桌面浏览器和服务器内网使用。

## 核心功能

| 模块 | 当前能力 | 详细说明 |
| :--- | :--- | :--- |
| 🔍 **选股引擎** | 内置策略 + 自定义信号 + AI 辅助生成 | 以标准化 enriched 数据为输入，按条件、评分和排序扫描股票池。 |
| 📊 **指标流水线** | MA、EMA、MACD、RSI、KDJ、布林带、量比等 | 统一计算并落盘为 enriched 数据，供选股、监控和回测复用。 |
| 🧪 **回测工作台** | 因子回测、策略回测、参数优化、步进优化 | 展示收益、回撤、胜率、交易明细和资金曲线，支持 SSE 进度。 |
| 📡 **监控中心** | 策略、个股信号、价格/涨跌、市场异动 | 支持规则组合、触发记录、实时提示、语音和通知扩展。 |
| 📈 **个股分析** | 日 K、关键价位、技术形态、AI 四维分析 | 从技术面、基本面、财务和消息面组织个股研究结果。 |
| 🧾 **财务分析** | 利润表、资产负债表、现金流、关键指标、股本 | 只展示 provider 实际提供并经过标准化的数据，不用默认值伪造缺失指标。 |
| 🧭 **概念/行业分析** | 热度、涨跌、成交、领涨领跌、成分股穿透 | 用板块维度观察轮动和主线，并可继续查看成分股。 |
| 🏆 **连板梯队** | 涨停、炸板、断板、跌停、翘板和封单观察 | 用于观察短线情绪结构，不等同于交易信号。 |
| 🌡️ **市场环境** | 强弱、赚钱、投机、抗跌、趋势等维度 | 展示市场状态、状态时间轴、分布和综合趋势图。 |
| 📝 **复盘** | 盘后市场复盘、报告保存和推送扩展 | 可生成 Markdown 等研究结果，具体能力取决于数据和 AI 配置。 |
| 🤖 **问 AI** | 页面数据解释、研究问答、工具调用 | AI 不能绕过权限、直接执行数据库或交易操作。 |
| 🎓 **资产配置教育** | 4321 法则、美林周期、财商训练、iframe 小游戏 | 教学型子页面，帮助理解目标、期限、流动性和风险承受，不提供个性化投资建议。 |
| 🧰 **数据扩展** | 快照/时间序列 provider、自定义分析菜单 | 可将扩展数据映射成分析页面，与内置数据保持统一展示方式。 |

## 主要页面

### 行情与观察

- **看板 Dashboard**：市场指数、涨跌分布、成交额、涨跌停、情绪雷达、趋势强度、概念热度、行业热度和盘中异动汇总。
- **自选 Watchlist**：账户自己的标的池，支持表格/卡片视图、指标列、K 线预览、批量操作和自选资讯雷达。
- **指数 Indices**：查看主要指数历史行情和指标，和个股、板块研究使用同一数据仓库。
- **市场环境 Regime**：用市场宽度、赚钱效应、投机、抗跌和趋势等维度观察环境变化，并展示状态时间轴。

### 选股、回测与分析

- **策略 Screener**：按内置策略、自定义条件、AI 生成策略或策略组合筛选股票；策略结果必须建立在当前数据覆盖范围上。
- **回测 Backtest**：包含因子回测、策略回测、参数优化和步进优化。回测结果包含收益、风险、回撤、交易次数、胜率和明细。
- **个股分析 Stock Analysis**：查看日 K、关键价位、技术形态和四维研究结果，可继续发起 AI 分析或多空讨论。
- **财务分析 Financials**：按报表类型查看利润表、资产负债表、现金流、关键指标和股本数据，并保留报告期与公告日期。
- **概念分析 Concept Analysis**：按概念观察涨幅、强度、成交、领涨/领跌主线和成分股。
- **行业分析 Industry Analysis**：按行业观察强弱、轮动、成交和成分股。
- **连板梯队 Limit Up Ladder**：观察涨停梯队、炸板和断板，也支持跌停、翘板等反向情绪状态。

### 监控、复盘与教育

- **监控中心 Monitor**：配置策略、个股信号、价格/涨跌、市场异动和板块监控规则，保留触发记录并支持通知扩展。
- **复盘 Review**：盘后整理市场结构和重要事件，支持报告保存、下载及按部署配置推送。
- **问 AI**：工作台右下角的常驻研究入口，使用后端授权的数据和工具回答当前页面问题。
- **资产配置 Asset Allocation**：React 路由 `/asset-allocation` 复用 `frontend/public/asset-allocation.html`，兼容入口 `/asset-allocation.html`；页面使用固定比例布局，包含 01 配置总览、02 4321 法则、03 美林周期、04 财商训练，并在页面内嵌财商小游戏 iframe。

### 数据与系统

- **数据 Data**：查看维表、日 K、除权因子、Enriched、指数、ETF、分钟 K 和财务数据的存储与同步状态。
- **扩展分析 Analysis**：将自定义数据字段配置成分析菜单，支持快照和时间序列数据。
- **设置 Settings**：管理账户、数据源、AI、实时行情、信号库、扩展页面、菜单顺序和系统参数。

## 界面预览

线上入口：**<https://www.qszscloud.online/>**

公网入口当前先显示账户注册/登录页，登录后进入个人隔离的智能投研工作台。以下图片是当前版本的线上入口和主要工作台页面。

<table>
  <tr>
    <td width="50%" align="center"><b>线上入口 · 账户隔离</b></td>
    <td width="50%" align="center"><b>行情总览 · Dashboard</b></td>
  </tr>
  <tr>
    <td width="50%"><img src="./screenshots/qszscloud-home.png" alt="清数智算线上登录入口"></td>
    <td width="50%"><img src="./screenshots/dashboard-current.png" alt="当前行情总览页面"></td>
  </tr>
  <tr>
    <td width="50%" align="center"><b>历史回测 · Backtest</b></td>
    <td width="50%" align="center"><b>概念分析 · Concept Analysis</b></td>
  </tr>
  <tr>
    <td width="50%"><img src="./screenshots/backtest-current.png" alt="当前历史回测页面"></td>
    <td width="50%"><img src="./screenshots/concept-analysis-current.png" alt="当前概念分析页面"></td>
  </tr>
  <tr>
    <td width="50%" align="center"><b>监控中心 · Monitor</b></td>
    <td width="50%" align="center"><b>市场环境 · Market Regime</b></td>
  </tr>
  <tr>
    <td width="50%"><img src="./screenshots/monitor-current.png" alt="当前监控中心页面"></td>
    <td width="50%"><img src="./screenshots/market-regime-current.png" alt="当前市场环境页面"></td>
  </tr>
  <tr>
    <td colspan="2" align="center"><b>资产配置 · Asset Allocation / 财商训练</b></td>
  </tr>
  <tr>
    <td colspan="2" align="center"><img src="./screenshots/asset-allocation-current.png" alt="当前资产配置与财商训练页面"></td>
  </tr>
</table>

更多财务分析、个股分析、策略、连板梯队、复盘和推送效果见[完整截图目录](./screenshots/README.md)。

## 数据源与数据口径

### 数据源

项目通过 `MarketDataProvider` 统一接入数据源，页面和业务服务不直接拼接某个供应商的响应格式。当前主要数据来源包括：

| 数据源 | 角色 | 说明 |
| :--- | :--- | :--- |
| **TickFlow** | 官方 SDK 数据源 | 支持日 K、分钟 K、指数、财务、实时行情等能力，具体权限由账户档位决定。 |
| **TeaJoin** | 服务器级 custom provider | 可为日 K、复权因子、分钟、实时和财务数据提供生产数据；Key 只放服务器环境，不暴露给浏览器。 |
| **自定义 provider** | 扩展数据源 | 通过 YAML 契约接入 HTTP、CSV、JSON 或内部服务，并在进入核心计算前完成标准化。 |

数据源按数据集分别路由，常见数据集包括 `daily`、`adj_factor`、`minute`、`realtime` 和 `financial`。配置 provider 后，系统会记录来源、市场、证券标识、数据日期、采集时间、状态和新鲜度。

数据源异常必须区分为：

- `empty`：请求成功但没有可用数据；
- `stale`：有数据，但不是允许展示为最新的数据；
- `provider_unavailable`：provider 未配置或不具备所需能力；
- `error`：网络、解析或服务端错误；
- `success`：字段、日期和数据覆盖均通过校验。

系统不会把错误统一伪装成空数组，也不会用零值或旧值冒充最新行情。TeaJoin 被选为某个数据集的生产 provider 后，也不会在页面层悄悄改用另一套供应商数据。

### 金融数据口径

进入计算链路前，数据需要完成字段类型、代码、重复行、日期、单位、币种、时区和异常值校验。涉及历史研究时，还要记录目标时点真实可获得的数据版本。

项目特别区分以下口径：

- **价格**：enriched 技术指标使用前复权价格；涨跌停、一字板、炸板等交易规则使用原始价格及对应交易日规则。
- **涨跌幅和换手率**：不同接口可能使用小数制或百分数值，跨 provider 边界时必须显式转换，不能根据数值大小猜测单位。
- **日期**：自然日、交易日、交易时段、报告期、公告日期和采集时间不是同一个字段。
- **历史数据**：回测不得使用目标日期之后才公开的数据，不得产生未来函数、数据泄漏或幸存者偏差。
- **A 股交易规则**：策略回测需要考虑 T+1、手续费、滑点、涨跌停不可成交、停牌和调仓时点；数据不足时必须明确返回数据覆盖不足。

## 快速开始

### 前置依赖

- Python **3.11+**
- Node.js **20+**
- [`uv`](https://docs.astral.sh/uv/)
- [`pnpm`](https://pnpm.io/)，可通过 `npm i -g pnpm` 安装
- 生产部署可选 Docker Engine / Docker Desktop

### 方式 A：开发模式

Windows PowerShell：

```powershell
Copy-Item .env.example .env
.\dev.ps1
```

macOS / Linux：

```bash
cp .env.example .env
./dev.sh
```

启动脚本会检查依赖、释放占用端口并同时启动前后端：

- 前端开发服务：<http://localhost:3011>
- 后端 API：<http://localhost:3018>

如果需要手动分别启动：

```bash
# 后端
cd backend
uv sync --extra backtest
uv run uvicorn app.main:app --reload --port 3018

# 另开终端启动前端
cd frontend
pnpm install
pnpm dev
```

老 CPU 如果不支持 AVX2/FMA，可使用兼容 extras：

```bash
cd backend
uv sync --extra legacy-cpu
# 同时需要回测依赖时：
uv sync --extra legacy-cpu --extra backtest
```

### 方式 B：Docker 部署

Docker 使用两阶段构建，先生成前端 `dist`，再把静态资源复制到 FastAPI 运行镜像，由一个服务同时提供前端页面和 API：

```bash
cp .env.example .env
docker compose up --build -d
```

部署后：

- 工作台：<http://localhost:3018>
- 存活检查：<http://localhost:3018/health>
- 就绪检查：<http://localhost:3018/api/health>

`docker-compose.yml` 会把 `./data` 挂载到 `/app/data`，因此行情、财务、自选、策略、回测、监控和报告会保留在主机。不要把 `data/`、`.env`、用户 Key 或日志提交到 Git。

#### Docker 中的可选能力

- **stock-sdk 默认不打包**：它涉及第三方财经网站接口抓取、服务条款、反爬和行情版权边界。只有在确认拥有合法授权并愿意承担合规责任时，才显式构建：

  ```bash
  docker compose build --build-arg INCLUDE_STOCKSDK=1
  docker compose up -d
  ```

- **Codex / AI**：AI 是可选能力。若部署需要复用主机 Codex 登录态，按 `docs/deployment.md` 配置只读挂载；不使用时可以移除相应挂载和配置。
- **反向代理**：SSE 和 NDJSON 接口必须关闭代理缓冲、关闭缓存并放宽读取超时，否则实时进度和 AI 流式结果可能被代理截留。

## 第一次使用

部署完成后建议按以下顺序检查：

1. **配置数据源**：在设置页确认 TickFlow/TeaJoin 的能力和当前 provider 状态。`TEAJOIN_API_KEY` 只能放在服务器 `.env`、密钥管理器或受限文件中。
2. **检查数据覆盖**：查看“数据”页面，确认维表、日 K、除权因子和 enriched 数据的日期、行数和状态；策略没有命中时，先排除历史覆盖不足。
3. **运行数据管道**：同步日 K、指数和必要扩展数据，完成指标/enriched 计算后再使用策略和回测。
4. **建立自选池**：在“自选”页添加标准证券代码，检查名称、交易所、最新日期和数据源状态。
5. **运行策略**：在“策略”页选择内置策略或配置自定义条件，查看筛选结果的日期、数据覆盖和命中数量。
6. **验证回测**：选择策略和区间，检查收益、回撤、交易明细、T+1、费用、滑点和不可成交条件，不要只看最终收益率。
7. **配置监控**：在“监控中心”设置策略、价格、异动或板块规则，确认触发记录、实时开关和通知配置。
8. **使用教育页面**：从左侧“资产配置”进入 4321 法则、美林周期和财商训练。该页面用于理解资产配置概念，不读取用户资产，也不产生交易指令。

## 配置

所有配置从根目录 `.env` 读取，也可以在工作台“设置”页修改允许用户修改的配置。先复制 `.env.example`，不要直接创建或提交包含真实 Key 的文件。

### 数据与服务

```ini
# TickFlow 官方 SDK Key，可留空以使用部署允许的免费/本地能力
TICKFLOW_API_KEY=

# TeaJoin 服务器级 provider Key，只在后端读取
TEAJOIN_API_KEY=

HOST=0.0.0.0
PORT=3018
LOG_LEVEL=INFO
DATA_DIR=./data
CORS_ORIGINS=
```

### AI 配置

```ini
AI_PROVIDER=openai_compat       # openai_compat | ollama
AI_BASE_URL=https://api.deepseek.com
AI_API_KEY=
AI_MODEL=deepseek-v4-flash
AI_DAILY_TOKEN_BUDGET=500000
```

如果允许用户在设置页填写自己的 OpenAI 兼容 API Key，生产环境必须设置稳定的 `USER_SECRETS_MASTER_KEY`。它用于加密数据库中的用户私有 Key，不能写入镜像、前端代码、Git 或公开日志。

### 账户与公网部署

```ini
# 旧版单实例访问密码兼容项，仅在首次初始化时生效
AUTH_PASSWORD=

# qingshu101 运维子域名的可选配置
QINGSHU101_ADMIN_KEY=
QINGSHU101_HOST=
```

当前 C 端入口使用“姓名 + 电话 + 密码”和 HttpOnly 会话 Cookie。`AUTH_PASSWORD` 是旧版单实例部署的兼容初始化方式，不代替 C 端用户注册密码。公网第一次初始化密码时，必须通过本机/内网访问或 SSH 端口转发，详细步骤见 [`docs/deployment.md`](./docs/deployment.md)。

### 可选构建参数

```ini
# 老 CPU 兼容：legacy-cpu
# 回测依赖：backtest
BACKEND_EXTRAS=
UV_VERSION=0.8.24
```

完整配置项和优先级见 [`docs/configuration.md`](./docs/configuration.md)。

## 技术栈

| 层 | 当前选型 |
| :--- | :--- |
| **后端 Web** | Python 3.11+ · FastAPI · Pydantic v2 · Uvicorn · python-multipart |
| **数据处理** | Polars · DuckDB · PyArrow · Parquet |
| **回测** | pandas 仅作为回测边界依赖；vectorbt 作为可选 `backtest` extra，主流程不依赖它才能启动 |
| **数据源** | TickFlow 官方 SDK · TeaJoin custom provider · 自定义 provider/plugin |
| **任务与实时** | APScheduler · SSE · NDJSON · 有界并发与状态记录 |
| **AI** | OpenAI 兼容接口、DeepSeek、Ollama 等可配置 provider |
| **前端** | React 19 · TypeScript · Vite · Tailwind CSS · Mantine · TanStack Query |
| **图表与交互** | ECharts · lightweight-charts · dnd-kit · Framer Motion · lucide-react |
| **部署** | Docker 两阶段构建，单容器托管前端静态资源与 FastAPI |

## 目录结构

```text
backend/app/
├─ api/             HTTP、SSE、参数校验和响应映射
├─ services/        数据同步、实时行情、通知和业务编排
├─ data_providers/  数据源接口、标准化模型和自定义 provider
├─ tickflow/        数据仓库、能力检测和 TickFlow 接入
├─ indicators/     指标计算与 enriched 流水线
├─ strategy/        策略注册、执行、监控和 AI 策略
└─ backtest/        回测、优化、步进优化与 worker

frontend/src/
├─ components/      布局、图表、弹窗和跨页面组件
├─ pages/           页面级编排
├─ lib/api.ts       前后端 API 类型契约
└─ lib/queryKeys.ts TanStack Query 查询键

frontend/public/asset-allocation.html  资产配置静态子页面
data/data_sources/                     provider YAML 配置
data/                                   运行时数据，不提交到 Git
docs/                                   部署、配置、数据源和功能文档
screenshots/                            页面与报告截图
```

## 测试、验证与发布

### 快速验证

```bash
# 后端全量测试
cd backend
uv run pytest

# 后端静态检查
uv run ruff check app tests

# 前端构建和 lint
cd ../frontend
pnpm build
pnpm lint

# 仓库差异检查
cd ..
git diff --check
```

### 发布前检查

涉及数据源、权限、金融计算、Agent、数据库、Docker 或核心接口时，不能只以页面能打开作为完成标准。发布前至少确认：

1. 后端测试、前端构建和受影响模块测试通过。
2. `/health` 和 `/api/health` 返回正确状态。
3. 数据源 Key、账户隔离、日志脱敏和用户 AI Key 加密配置完整。
4. SSE/NDJSON 反向代理配置正确，实时行情和流式 AI 不被缓存。
5. `data/` 已做备份，更新代码不会覆盖现有用户数据。
6. 回滚时旧版本仍能读取新版本产生的兼容数据；不可逆迁移必须有前向修复方案。

低风险的纯文档修改可以只执行 Markdown、路径和差异检查；业务代码修改按 [`CONTRIBUTING.md`](./CONTRIBUTING.md) 的验证矩阵执行。

## 完整文档

| 文档 | 内容 |
| :--- | :--- |
| [`docs/deployment.md`](./docs/deployment.md) | Dev、Docker、反向代理、健康检查、更新、密码和公网部署 |
| [`docs/configuration.md`](./docs/configuration.md) | 数据源、AI、服务、账户、密码、数据目录和配置优先级 |
| [`docs/features.md`](./docs/features.md) | 选股、指标、回测、监控、分析和数据扩展 |
| [`docs/strategy.md`](./docs/strategy.md) | 策略体系、参数、数据覆盖要求和扩展方式 |
| [`docs/custom-data-source.md`](./docs/custom-data-source.md) | TeaJoin、HTTP/CSV/JSON provider 和字段标准化契约 |
| [`docs/plugin-development.md`](./docs/plugin-development.md) | provider/plugin 目录结构、生命周期和能力声明 |
| [`docs/qingshu101-admin.md`](./docs/qingshu101-admin.md) | qingshu101 运维子域名、服务器级 provider 和健康状态 |
| [`docs/vibe-public-news.md`](./docs/vibe-public-news.md) | 资讯 provider、时间窗口、去重和账户隔离 |
| [`backend/app/strategy/prompts/strategy-guide.md`](./backend/app/strategy/prompts/strategy-guide.md) | AI 生成与手写策略的开发规范 |
| [`screenshots/README.md`](./screenshots/README.md) | 当前版本和历史页面截图 |
| [`CONTRIBUTING.md`](./CONTRIBUTING.md) | 架构边界、数据口径、安全、测试和发布要求 |

## 持续维护方向

当前版本已覆盖工作台核心链路，后续迭代重点保持在数据质量和生产稳定性，而不是添加无法验证的展示功能：

- 增加 provider 数据覆盖、字段校验和新鲜度监控。
- 持续完善资讯去重、公告时间口径和用户级缓存隔离。
- 扩展回测边界测试、压力场景和历史数据可获得性校验。
- 完善通知渠道、后台任务观测、备份恢复和公网部署检查。
- 继续补充资产配置教育内容，但不将教育页面包装成荐股或收益承诺工具。

## 参与贡献

请先阅读 [`CONTRIBUTING.md`](./CONTRIBUTING.md)。新增数据能力必须通过 provider 标准化契约接入，不能在页面或 API 中直接拼接供应商响应；涉及金融计算时要补充单位、时间、复权、缺失值和边界条件测试；涉及用户数据时要保持账户隔离、权限校验、日志脱敏和可回滚路径。

## 免责声明

本项目仅供学习、金融研究和量化分析使用，不构成任何投资、交易或资产配置建议。数据源可能存在延迟、缺失、调整或服务中断；回测存在样本、幸存者、未来函数、流动性和费用假设风险。使用者应自行核验数据、规则和结果，并承担使用本项目产生的全部决策风险。

## License

[MIT](./LICENSE) © tickflow-stock-panel contributors

本项目可接入 [TickFlow](https://tickflow.org/)、TeaJoin 或其他数据服务。使用任何数据源、插件和 AI 服务前，请遵守相应许可、服务条款、数据授权和适用法律法规。
