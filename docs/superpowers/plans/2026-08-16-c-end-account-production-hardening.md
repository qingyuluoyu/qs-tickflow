# C 端账户服务与后台预处理生产化

## Goal

在现有“首页填写姓名、电话、密码即可进入”的基础上，把账户层提升到可以长期运行的 C 端产品形态：每个用户的个人数据、策略、监控、报告和回测产物严格隔离；`qingshu101` 作为仅运营者可访问的注册目录；账户元数据、TeaJoin 行情、日线/财务刷新和监控评估由服务器后台持续处理，不依赖用户打开某个页面才触发。保持已有 API 兼容，不让本次改动破坏看板、个股分析、财务分析、自选和策略页面。

## Architecture

保留现有模块化单体和 `MarketDataProvider` 插件边界，不引入新的外部数据库或消息队列。

1. **身份层**：本地 SQLite 继续保存用户、会话和登录防护状态；密码只保存 PBKDF2 哈希；HttpOnly 会话 Cookie 绑定一个明确的 `user_id`。
2. **个人数据层**：`data/users/<user_id>/` 是自选、偏好、策略、监控规则、告警、报告、扩展数据和回测产物的唯一写入根；公共行情/财务/指数 Parquet 继续放在共享数据根，只读复用。
3. **服务器配置层**：数据源选择、TeaJoin 运行状态、后台刷新间隔属于服务器级配置；个人展示偏好和自选仍属于账户级配置。旧的 `preferences.json` provider 字段只作为一次性兼容迁移来源。
4. **后台运行层**：账户目录缓存、账户监控运行时、QuoteService、盘前/盘后管道和财务同步都在 lifespan 启动；请求只读取已经准备好的快照/缓存，不在页面渲染时为每一行重新访问 SQLite 或 TeaJoin。
5. **运营层**：`qingshu101` 只返回无密码的注册元数据，使用明确的 host 约束、HttpOnly 签名 Cookie、限流和缓存健康状态；普通用户 API 永远只能看到自己的身份和自己的工作区。

## Tech Stack

- Backend: FastAPI、Pydantic、SQLite、ContextVar 用户上下文、APScheduler、线程后台任务、Polars/Parquet。
- Data: `MarketDataProvider` / `GenericHTTPProvider`，TeaJoin YAML 数据源配置，标准化 `daily`、`adj_factor`、`realtime`、`minute`、`financial` 契约。
- Frontend: React、React Router、TanStack Query、Vite；账户入口继续内嵌在 `AuthGate`，不新增独立登录页。
- Tests: pytest/TestClient、TeaJoin provider contract tests、账户隔离测试、前端 `pnpm build`。

## Global Constraints

- 先做加法迁移和双读兼容，不删除现有 `data/user_data`、旧 `auth.json`、旧个人文件或旧 API 字段。
- 不限制姓名、电话和密码的业务字符或长度；只保留请求体大小上限和防暴力登录保护，不截断用户输入。
- 所有数据源进入计算前必须校验字段、单位、日期、重复、空数据和新鲜度；TeaJoin 的 `change_pct`、`turnover_rate` 继续按小数制处理，日线 `amount` 继续按配置转换为元。
- 公共行情只拉取一次并共享；个人监控、冷却、策略结果和告警事件按 owner 隔离。任何 provider 失败不得静默回退到另一账户或旧的共享规则。
- 外部请求必须有超时、有限重试和退避；不把 API Key、密码、Cookie、完整登录信息写入日志。
- 每个列表接口必须有上限；监控评估、财务同步和历史数据任务不得阻塞普通 HTTP 请求。
- 任何接口字段修改先检查所有调用方；保持现有 `/api/auth/*`、`/api/qingshu101/*`、`/api/intraday/status` 和设置页字段兼容。

## 当前代码审查结论

已经存在并应保留的能力：

- `backend/app/services/account_store.py` 已有 SQLite v1 迁移、PBKDF2、随机会话令牌和首账户旧数据复制；`backend/app/services/user_context.py` 已有请求级工作区绑定。
- `backend/app/services/account_directory.py` 已有 30 秒后台预处理缓存；`backend/app/api/qingshu101.py` 已有 host 判断、签名 Cookie、分页且不返回密码材料。
- `backend/app/services/monitor_runtime.py` 已能为每个账户建立独立 `StrategyEngine`/`MonitorRuleEngine`；规则文件位于账户工作区。
- TeaJoin 已通过 `GenericHTTPProvider` 接入日线、除权、分钟、实时和财务，并有基础字段/单位/重试测试；盘后管道和 QuoteService 已有后台轮询。

本轮必须解决的实际风险：

1. QuoteService 后台线程没有请求 `ContextVar`，但 `preferences.get_realtime_*`、provider 选择和自选读取仍是账户态函数；多账户时后台可能只读取共享旧目录，不能保证把所有账户自选并入 TeaJoin 请求。
2. `AccountMonitorRuntime.refresh_if_due()` 在行情热路径同步扫描账户和规则；`QuoteService._evaluate_monitors()` 又逐账户串行计算，没有评估耗时、错误、积压或跳过指标。
3. `/api/auth/entry` 的会话 Cookie 固定 `secure=False`；登录失败计数仅存进程内，多 worker 部署时可被绕过。账户表没有记录最后登录时间/启用状态，登录成功也不会更新 `updated_at`。
4. qingshu101 目录后台刷新错误只保留旧快照，接口没有返回缓存是否过期；管理员入口没有登录限流、审计信息或明确的生产 host 配置。
5. 财务调度默认只初始化、不自动同步；服务器重启或用户不打开财务页时，TeaJoin 财务数据不一定被后台预处理。自定义数据源文档仍落后于当前已支持的数据集。

## 工作包 1：账户会话、登录防护和数据库演进

**目标**：让账户入口在单进程和多 worker 部署下都具备可追踪、可撤销、可限流的会话行为，同时保持现有姓名/电话/密码入口兼容。

### 文件与接口

- 新增 `backend/app/db/migrations/002_account_security.sql`：为 `users` 增加 `status`（默认 `active`）和 `last_login_at`；新增 `auth_attempts` 表（哈希 key、失败次数、锁定截止、更新时间）及索引。迁移只新增结构，不删除 v1 字段。
- 修改 `backend/app/services/account_store.py`：把 `_migrate()` 改为可重复执行的版本迁移；`enter()` 成功登录/创建后在同一事务内更新 `last_login_at`；新增 `check_login_lock(key)`、`record_login_failure(key)`、`clear_login_failures(key)`、`revoke_user_sessions(user_id)`，key 只接收 API 层生成的不可逆哈希；`list_users()` 保持不返回密码/盐/token。
- 修改 `backend/app/api/auth.py`：移除仅进程内失败计数作为主防线，改用 AccountStore 的持久化计数并保留短期内存缓存减轻 SQLite 写入；按 `request.url`/可信反代协议决定 Cookie `secure`，不再固定 `False`；成功登录返回结构不变，错误语义继续区分 400/401/409/410/429。
- 修改 `backend/app/main.py`：认证中间件继续绑定 `request.state.user_data_root` 和 ContextVar；增加可信 host/反代配置校验，防止公网伪造 `X-Forwarded-For` 绕过限流；启动/关闭时确保账户目录、QuoteService、监控运行时和 provider 资源成对释放。
- 更新 `backend/tests/test_account_store.py`，新增 `backend/tests/test_auth_api.py` 和 `backend/tests/test_auth_middleware.py`。

### 实现顺序

1. 先写 v1→v2 迁移和失败测试，确认旧数据库启动后能重复迁移，旧应用读取新增列不受影响。
2. 再接入 AccountStore 登录状态更新和持久化限流；不改变姓名、电话、密码的字符规则。
3. 最后切换 Cookie 安全属性和 middleware 的可信来源判断；对旧 session 仍允许自然过期/主动注销。

### 验收与回滚

- 两个账户同时登录时，注销 Alice 只撤销 Alice 当前 token；Bob token 仍有效。
- 同一失败 key 跨应用实例读取到相同锁定状态；成功登录清除失败计数；锁定期间不会修改 `last_login_at`。
- HTTP/HTTPS 下 Cookie 的 `HttpOnly`、`SameSite`、`Secure` 与部署协议一致；测试不读取任何密码材料。
- 回滚只回滚代码，不回滚 SQLite 结构；v2 的新增列/表对旧代码是兼容的，必要时用前向修复而不是手工降级数据库。

## 工作包 2：用户隔离审计与服务器级 TeaJoin 配置

**目标**：把“个人设置”和“服务器行情配置”分开，修复后台线程无法携带用户 ContextVar 导致的跨账户自选/数据源读取问题。

### 文件与接口

- 新增 `backend/app/services/server_preferences.py`：提供 `load()`、`save(updates)`、`get_provider(dataset)`、`get_quote_interval()`、`get_financial_schedule()`；使用 `data/server_config.json`，临时文件写入后原子替换，并使用进程锁避免并发覆盖。
- 修改 `backend/app/services/preferences.py`：保留个人 UI 偏好和自选读取；provider/后台刷新字段增加兼容包装，优先读 server config，server config 不存在时只从旧共享 `data/user_data/preferences.json` 迁移一次，不从任意用户工作区选择 provider。
- 修改 `backend/app/api/settings.py` 和 `frontend/src/pages/settings/DataSources.tsx`：响应字段名称保持不变，但数据源选择写入服务器配置；页面明确显示“服务器级 TeaJoin 数据源”，不再让不同账户误以为各自拥有独立实时源。
- 修改 `backend/app/services/monitor_runtime.py`：增加 `watchlist_symbols(limit_per_account=5)`，在服务器线程中按账户工作区读取并去重，限制单账户和总量；增加只读的账户快照接口供 QuoteService 使用。
- 修改 `backend/app/services/quote_service.py`：后台全市场/自选轮询使用 server provider；自选模式请求 `monitor_runtime.watchlist_symbols()` 的账户并集，不使用请求 ContextVar；响应仍按当前登录账户过滤展示。保留原 `/api/intraday/status` 字段并补充 provider scope。
- 对 `backend/app/api/watchlist.py`、`backend/app/services/watchlist.py`、`backend/app/services/strategy_runtime.py`、`backend/app/services/json_report_store.py`、`backend/app/services/backtest.py`、`backend/app/api/ext_data.py`、`backend/app/api/monitor_rules.py`、`backend/app/api/alerts.py`、`backend/app/api/settings.py` 做一次路径审计：个人写入必须走 `request_data_root()`/`personal_user_data_dir()`，公共行情只能走 repo。
- 新增/更新 `backend/tests/test_server_preferences.py`、`backend/tests/test_background_watchlist_union.py`、`backend/tests/test_user_data_isolation.py`、受影响 API 测试。

### 实现顺序

1. 先写 server config 的读写、一次性兼容迁移和并发覆盖测试。
2. 再改 QuoteService 的后台读取，验证两个账户各有自选时 TeaJoin 请求只发一次且包含并集，页面接口仍只返回当前账户。
3. 最后接入设置页兼容字段和全量路径审计；没有证据需要改的页面不做顺便重构。

### 验收与回滚

- Alice/Bob 的 watchlist、preferences、strategy、alerts、reports、backtest 文件物理路径不同；共享 repo 数据只有一份。
- 后台轮询在没有任何浏览器请求时仍能读取 TeaJoin server provider；用户切换账户不会改变正在运行的全市场快照。
- 删除/改名旧 provider 字段不会发生；移除 `server_config.json` 时回退旧共享配置并记录迁移日志。

## 工作包 3：qingshu101 运营目录与服务器预处理

**目标**：保留隐藏子域名语义，但把它变成可上线的运营入口：不暴露密码，只读服务端预处理快照，并能发现刷新失败和陈旧状态。

### 文件与接口

- 修改 `backend/app/config.py`：增加显式 `qingshu101_host`、`qingshu101_cookie_ttl`、`account_directory_refresh_interval` 配置；默认仍只允许本地开发 host，生产必须显式配置子域名。
- 修改 `backend/app/services/account_directory.py`：增加 `status()` 返回 `refreshed_at`、`last_success_at`、`last_error`、`refresh_duration_ms`、`total`、`complete`、`stale`；后台刷新保留最后成功快照但不再静默丢失错误；刷新依然分页、上限 10,000、只保存非敏感元数据。
- 修改 `backend/app/api/qingshu101.py`：统一使用配置 host 检查；`/status` 增加目录健康字段但不增加 PII；`/users` 增加 `Cache-Control: no-store` 和健康时间；管理员 session 增加按 IP 的有限失败锁定，密钥比较继续使用 constant-time；非指定 host 返回 404。
- 修改 `frontend/src/router.tsx` 和 `frontend/src/pages/Qingshu101Admin.tsx`：生产只在 qingshu101 host 渲染管理入口，本地 `/qingshu101` 仍可用；管理员页面每 30 秒刷新服务端缓存，不触发逐账户 SQLite 查询；显示目录快照时间/陈旧状态和退出按钮。
- 更新 `docs/qingshu101-admin.md`、部署样例和 `docs/custom-data-source.md`，说明 host、HTTPS、Cookie、TeaJoin 五类数据集、缓存刷新和密钥轮换。
- 更新 `backend/tests/test_account_directory.py`、`backend/tests/test_qingshu101_admin.py`，新增 host、限流、缓存陈旧和响应不含密码材料的 API 测试；新增前端管理页构建冒烟。

### 验收与回滚

- qingshu101 页面加载不触发数据库全量查询；显示的 `refreshed_at` 来自后台缓存，后台 SQLite 暂时不可用时明确显示旧快照/错误。
- 任意普通用户 session、普通主域名和猜测路径均不能访问 `/api/qingshu101/users`。
- 轮换 `QINGSHU101_ADMIN_KEY` 后旧 Cookie 立即失效；管理员接口不返回密码、盐、哈希、token 或用户工作区路径。
- 前端继续支持本地开发路径，但生产 host 不满足配置时不渲染有效目录。

## 工作包 4：后台 TeaJoin 刷新、账户监控调度与背压

**目标**：服务器启动后自行刷新数据和监控，不把账户数量线性成本放进行情请求；在 provider 过期、网络失败或账户增长时可观测且不雪崩。

### 文件与接口

- 修改 `backend/app/services/monitor_runtime.py`：增加 `start()`/`stop()` 后台刷新线程，原子替换账户 handle 快照；增加 `status()`（账户总数、启用规则账户、最近刷新、刷新错误、评估排队/运行/跳过计数）和 `watchlist_symbols()`；`refresh_if_due()` 仅作为兼容入口，不再由 QuoteService 热路径承担全量扫描。
- 为 `AccountMonitorHandle` 增加评估锁、最近评估时间、耗时、错误计数和账户级信号缓存；禁止不同账户共享 minute signal bucket 或 IntradaySignalEvaluator 状态。
- 修改 `backend/app/services/quote_service.py`：把网络拉取、快照落盘和监控评估分开；TeaJoin HTTP 请求使用 bounded timeout/retry，写入 `last_fetch_status`、provider source timestamp、snapshot age、rows 和 error class；监控评估使用有上限的 `ThreadPoolExecutor`（默认 4 个 worker，可配置），每轮有最大积压数，超出只记录 skipped，不无限提交；事件发布在结果收集后按 owner 写入。
- 调整 `backend/app/main.py` lifespan 顺序：先加载 custom providers、构建 monitor runtime 并启动后台任务，再启动 QuoteService；shutdown 依次停止 QuoteService、monitor runtime、account directory、scheduler，并调用 custom loader 的 `close_all()`。
- 修改 `backend/app/jobs/daily_pipeline.py`、`backend/app/services/financial_sync.py`：统一使用 server provider；启动后执行一次受限 freshness check；继续保留 09:10 instruments、15:30 daily/enriched 及 30/60/120 分钟重试；TeaJoin 有 financial 数据集时启用可配置的非阻塞周期同步，默认不在 HTTP 请求线程执行。
- 修改 `backend/app/api/intraday.py`、`backend/app/api/data.py`：在现有响应中增加 `provider_health`、`snapshot_age_ms`、`monitor_runtime`、`next_background_refresh`，不改变原字段含义；区分 `never`、`success`、`empty`、`stale`、`provider_unavailable`、`error`。
- 新增 `backend/tests/test_monitor_runtime_scheduler.py`、`backend/tests/test_quote_service_account_union.py`、`backend/tests/test_provider_health.py`、`backend/tests/test_background_refresh.py`；补充 TeaJoin provider 对缺字段、重复、日期落后、空批次、超时重试和 fail-closed 的契约测试。

### 实现顺序

1. 先把 monitor runtime 的刷新从 QuoteService 热路径移到后台线程，并用现有串行评估保持结果不变。
2. 增加账户级统计和测试后，再启用有界评估池；保留账户锁和 owner 过滤，先验证事件顺序/冷却状态。
3. 接入 server provider、TeaJoin freshness 状态和财务后台调度；任何 provider 失败只保留上次快照并标记陈旧，不填零、不伪造新时间。
4. 最后调整 lifespan 启停和资源关闭，做断电/重启/后台异常链路测试。

### 验收与回滚

- 不打开看板、自选或财务页面，服务器仍按计划刷新 TeaJoin；页面只读取共享快照和账户过滤结果。
- 账户评估耗时不会阻塞下一次行情网络拉取；队列达到上限时有计数和日志，不会无限增长。
- TeaJoin 返回空、HTTP 超时、字段缺失或日期过期时，状态接口能区分原因；旧快照不被错误覆盖。
- 停止服务后所有后台线程、HTTP client、scheduler 都退出；重新启动不会重复创建 worker 或重复迁移。
- 如有问题，可先关闭有界评估池 feature flag，退回后台串行评估；公共数据格式和个人文件不迁移、不删除。

## 工作包 5：可观测性、回归验证和上线门槛

**目标**：在真正部署前用可重复的测试和人工路径确认身份隔离、TeaJoin 数据口径、后台刷新和 qingshu101 权限边界。

### 文件与接口

- 新增轻量 request/trace id 中间件或在现有日志上下文中补充 `request_id`、`user_id`（仅记录 UUID，不记录姓名/电话/密码）；关键日志覆盖 auth、provider、scheduler、monitor。
- 增加 `backend/tests/test_account_e2e.py`：TestClient 临时 `DATA_DIR` 创建 Alice/Bob，分别写入 watchlist/preferences/strategy/alert/report/backtest，验证互不可见；检查 qingshu101 只读元数据。
- 增加 `backend/tests/test_server_lifecycle.py`：启动/关闭 lifespan，确认目录缓存、monitor runtime、QuoteService、custom provider client 均成对启停；临时目录可删除，避免 Windows 文件句柄残留。
- 更新 `docs/qingshu101-admin.md`、`docs/custom-data-source.md`、部署说明，列出 `DATA_DIR`、`TEAJOIN_API_KEY`、`QINGSHU101_ADMIN_KEY`、qingshu101 DNS/HTTPS/反代 host 配置和回滚方式。

### 必跑命令与通过标准

```powershell
cd F:\111\tickflow-stock-panel-main\backend
uv run pytest tests/test_account_store.py tests/test_account_directory.py tests/test_user_data_isolation.py tests/test_qingshu101_admin.py tests/test_account_e2e.py tests/test_server_lifecycle.py -q
uv run pytest tests/test_teajoin_provider.py tests/test_default_data_provider.py tests/test_market_overview_freshness.py tests/test_minute_routing.py tests/test_provider_health.py tests/test_background_refresh.py -q
uv run pytest -q
uv run ruff check app/services/account_store.py app/services/account_directory.py app/services/server_preferences.py app/services/monitor_runtime.py app/services/quote_service.py app/data_providers/custom app/api/auth.py app/api/qingshu101.py app/api/intraday.py app/main.py
cd ..\frontend
pnpm build
```

预期：受影响测试全部通过、全量 pytest 无回归、受影响 Ruff 无新增错误、前端构建成功。全量历史 Ruff 问题若仍存在，必须单独列出，不得用“全绿”表述。

### 人工验收路径

1. 使用临时数据目录启动后端，创建 Alice 和 Bob；两边分别添加自选、策略、监控和报告，切换 Cookie 后确认页面/接口完全隔离。
2. 不打开任何业务页面，观察 QuoteService、daily pipeline、financial scheduler 和 account directory 日志/状态，确认 TeaJoin 请求按服务器计划发生。
3. 让 mock TeaJoin 返回空数组、旧日期、缺字段和超时，确认状态分别为 `empty`、`stale`、`error`/`provider_unavailable`，且旧快照不被覆盖。
4. 在主域名、错误子域名和 qingshu101 子域名分别访问管理接口；只有配置 host + 正确密钥能看到分页目录，普通账户不能越权。
5. 停止并重启服务，确认 session 按 TTL 规则恢复/失效、后台线程数量不增长、临时数据目录可删除。

## 迁移、兼容与成本影响

- 数据库采用 v1→v2 expand-only；不删除旧表，不移动旧个人文件。首次账户迁移和 server config 迁移都保留原文件作为回滚副本。
- API 响应只新增字段，不删除现有字段；前端旧版本可继续读取原字段。数据源选择接口仍保留原字段名，后台改为 server scope。
- TeaJoin 请求从“用户访问触发”改为“服务器按计划批量触发”，能减少重复请求和页面延迟，但会稳定消耗 API 配额；批量、RPM、超时和财务周期必须遵守 YAML 配置并在状态中显示。
- 账户监控增加有界 worker 和统计内存；不引入 Redis/消息队列。达到容量边界时以跳过计数、陈旧状态和日志告警为准，不无限扩容。
- 任何迁移失败都在启动阶段阻断假启动；后台单个账户或单个 provider 失败不得阻断其他账户和数据集。

## 执行顺序与检查点

1. 先执行工作包 1，跑账户/认证定向测试并检查迁移。
2. 执行工作包 2，完成 server provider 与多账户后台自选并集，跑隔离和 TeaJoin provider 测试。
3. 执行工作包 3，接通 qingshu101 缓存健康与生产 host，跑前后端管理页联调。
4. 执行工作包 4，启动后台监控/数据刷新和背压，跑生命周期、状态和故障注入测试。
5. 执行工作包 5，跑全量验证、人工双账户路径和发布前健康检查；任何失败只报告“部分完成”，不宣称上线就绪。
