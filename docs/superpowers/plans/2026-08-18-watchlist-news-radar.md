# 自选资讯雷达弹窗 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在自选页顶部增加“ A 股公告 / 公开新闻 / 今日要点”三个入口，按当前登录用户的自选股聚合 VibePublic API 资讯，点击后在弹窗内搜索、查看个股详情，并可跳转到已填入代码和名称的个股分析页。

**Architecture:** 只借鉴 Vibe-Research 的字段语义和展示交互，不迁移它的 Flask 路由、localStorage 自选或逐股票 N+1 请求。后端新增独立资讯 provider：优先使用用户提供的 VibePublic API，未提供配置时使用已经移植到当前项目 `stock_insight.py` 的 Vibe-Research 公告/个股新闻公开源；两条路径都进入共享的只读规范化缓存。每个用户的“今日要点”、已读/收藏和筛选结果只写入该用户 workspace，并在请求期按当前 session 的自选过滤。前端只通过统一 `api.ts` 和 TanStack Query 获取数据，用一个自选资讯弹窗承载三类内容，页面本体不增加下方滚动板块。

**Tech Stack:** FastAPI、Pydantic v2、Polars、现有 custom HTTP provider/VibePublic 配置、APScheduler、React 18、TypeScript、TanStack Query、现有 Mantine `Modal`。

> **命名说明：** 文档中的 `VibePublic` 只是本项目内部的可配置 provider/配置键名称，不代表仓库中已经存在同名外部服务。当前未配置时会使用 Vibe-Research 已有的公开 Eastmoney 源；如果后续提供自己的 API，真实请求地址、认证方式、参数名和响应字段以该契约为准。

## Global Constraints

- 必须继续使用 `F:\111\tickflow-stock-panel-main` 现有 provider、用户上下文和请求封装，不复制 Vibe-Research 的 `newsradar.py`、Flask API 或 localStorage 自选实现。
- 外部 VibePublic 公告/新闻/RSS 字段、请求参数和返回路径必须以你接入的实际 API 契约为准；内置公开源只复用当前项目已存在并可追溯的 `stock_insight` 数据边界，不写假数据。
- 缺少 VibePublic 能力、字段校验失败、数据过期或上游失败时返回明确状态，不返回默认标题、空字符串冒充真实内容或 TickFlow/TeaJoin 数据。
- 用户自选列表只从 `request.state.user_data_root` 读取；公共资讯缓存可以跨用户复用，但过滤、搜索和任何已读/收藏状态必须包含用户边界。
- 后台任务只能使用所有账户自选的去重并集拉取公共文章；禁止在没有绑定用户上下文时生成、保存或返回用户专属“今日要点”。用户专属任务必须显式 `set_current_user(user, user_root)`，结束后 `reset_current_user(tokens)`。
- 任何客户端传来的 `user_id`、workspace 路径或缓存键都不可信；服务端只从 HttpOnly session 解析账户。用户切换时必须取消旧请求、清空旧 QueryClient，并让所有新资讯 query key 包含当前 user id。
- 共享文章缓存不得存储用户自选列表、AI prompt、AI 输出、已读状态或收藏状态；用户专属 JSON/Parquet 必须位于 `data/users/<validated_uuid>/user_data/`，写入使用原子替换和跨进程锁。
- 查询必须批量化并有上限；禁止在 React 组件中对每个自选股各发一条请求。
- 公告按公告日期、新闻按发布时间、今日要点按生成时间排序，并保留 `published_at`、`fetched_at`、`source`、`data_version` 元数据。
- 每个工作包先写失败测试，再写最小实现；后端契约变更至少运行 API/service/provider 测试，前端改动至少运行 `pnpm build`。

## 当前实现审计

- 压缩包 `backend/newsradar.py`：读取 `news_sources.json`，抓取 12 个赛道、108 个 RSS 源、近 7 天，40 线程抓取后写入单一 `backend/.cache/radar.json`；不包含股票代码，也没有登录用户隔离。
- 压缩包 `frontend/src/pages/Intel.tsx`：A 股公告和公开新闻通过 `loadWatch()` 读取浏览器 localStorage，再对每只股票调用一次公告/新闻接口，属于 N+1 请求；Investment News 的“今日要点”是浏览器侧把 RSS 文本临时交给 AI 生成，没有持久化来源链。
- 当前 `frontend/src/pages/Watchlist.tsx` 已在 PageHeader 之后统一放置搜索、筛选、视图控制，适合插入三个入口；当前已有 `frontend/src/components/Modal.tsx`、`StockPreviewDialog.tsx` 和 `StockFinancialSearch`，可复用弹窗、股票名称解析和跳转模式。
- 当前 `backend/app/services/user_context.py` 与 `backend/app/services/watchlist.py` 已按用户目录隔离自选；当前 `backend/app/api/stock_insight.py` 已有公告/新闻单股票接口，新的 watchlist 链路不让前端直接依赖它，而由独立 `VibeResearchProvider` 复用其数据边界并统一标准化。
- 当前项目已有 `app/services/stock_insight.py`，它是从原 Vibe-Research `astock.py` 移植的东财公告/个股新闻实现；此前新资讯路由没有调用它，只因 `news_registry` 仅等待外部 `vibe_public.yaml`，所以页面显示未配置。外部 API 仍可放在独立的 `data/data_sources/vibe_public.yaml`，不修改现有 TeaJoin 六类数据集。

## 第二轮隔离与影响审计

以下是对前期改动和上一版计划的补充结论，执行时必须作为阻断门槛：

| 检查项 | 当前事实 | 风险 | 修订要求 |
| --- | --- | --- | --- |
| HTTP 身份 | `backend/app/main.py` 的 auth middleware 会把 session 绑定到 `request.state.user_data_root` 和 `ContextVar` | 新 service 若直接读共享 `settings.data_dir` 会跨账户 | 所有私有读取必须使用 `request.state.user_data_root` 或已绑定 ContextVar；API 禁止接收 user_id |
| 自选存储 | `watchlist.py` 按用户 workspace 保存 Parquet，并有进程/文件锁 | 后台线程没有请求上下文 | 后台逐账户绑定 ContextVar；公共文章抓取与用户摘要生成分离 |
| 前端账户切换 | `AuthGate` 已 `cancelQueries()` + `queryClient.clear()` | 新 query 若使用无 user id 的 key，旧响应仍可能被复用 | 资讯 key 必须是 `['watchlist-news', user.id, category, symbol, q, cursor]`，queryFn 传入 abort signal |
| 现有 stock-insight 缓存 | `stock_insight.py` 有按 code 的进程内 TTL cache | 公共文章可共享，但不能缓存用户 prompt/摘要 | 新资讯 service 使用独立命名空间；不得把用户摘要写入 `_cache` |
| 后台预加载 | 现有行情/监控后台使用共享线程和账户 runtime | 把用户摘要写入共享快照会泄露账户内容 | 只把文章做共享预取；摘要按账户逐一生成并写入对应 workspace |
| provider 扩展 | custom loader 当前只认六类市场数据集 | 贸然加入 news 可能改变能力检测或数据页面 | 使用独立 `news_registry`/VibePublic provider；不修改 custom loader 的六类市场数据能力，旧 provider 回归必须不变 |
| API 路由 | 当前 watchlist router 有动态 `/{symbol}` 路由 | 新 `/api/watchlist/news` 可能产生路由歧义 | 使用独立 `watchlist_news` router，并增加路由解析回归测试 |
| 页面联动 | Screener 可添加/删除自选，Watchlist 自身也可变更 | 资讯弹窗可能继续显示旧自选结果 | 自选变更只精确失效当前用户资讯 query，不改看板/筛选业务 |
| 全局摘要语义 | Vibe-Research 的 Investment News 是全球 RSS 赛道资讯 | 直接改名后仍可能被误认为个股新闻 | “今日要点”第一版只基于当前用户自选关联文章；全球 RSS 若保留必须是独立数据源和独立 scope |

### 不会影响的页面和边界

- 看板、指数、筛选器、K 线、财务分析和连板梯队不改变其数据查询和计算逻辑；只新增资讯 provider 能力，不把新闻列加入行情 enriched 表。
- 个股分析仅复用现有 URL 参数初始化 `symbol/name`，不会修改 K 线、财务、AI 分析接口；新闻详情跳转失败时仍停留在弹窗并显示错误。
- 登录、退出、账户切换不新增 token 或 localStorage 认证状态；只在退出/切换时清理资讯查询和取消请求。
- TeaJoin 原有六类数据集配置不删除、不改字段口径；VibePublic 配置缺失时使用 Vibe-Research 内置公开源，不回退到 TickFlow 或 TeaJoin 行情数据；显式禁用配置才会关闭资讯。

### 必须先解决的上线阻碍

1. 外部 VibePublic 资讯 endpoint、请求参数、分页方式、时间字段、证券代码字段和授权范围目前未出现在仓库配置中；这不再阻塞内置公告/个股新闻，但会阻塞切换到你的自有 API。
2. “今日要点”属于用户专属派生数据，不能使用“所有账户并集后共用摘要”的实现；必须按账户生成/持久化，或改成只展示可按 symbol 严格过滤的客观文章摘要。
3. 如果部署为多 worker，单纯 `os.replace` 不足以保护用户摘要的读改写；必须增加 sidecar 文件锁/数据库事务，或者明确单写者任务模型并在启动配置中强制。
4. 上游返回没有全局唯一文章 ID 时，必须使用 `sha256(provider|category|symbol|published_at|title|url)` 生成稳定 ID，否则详情和去重会错乱。
5. VibePublic 返回“成功但空数组”不能被统一当成“暂无新闻”；响应必须区分 `empty`、`invalid`、`unavailable` 和 `stale`，否则页面会掩盖数据源问题。

## 目标接口契约

后端统一返回以下结构，前端不再依赖 Vibe-Research 的中文字段名：

```python
NewsCategory = Literal["announcement", "public_news", "today_highlight"]

class WatchlistNewsItem(BaseModel):
    id: str
    category: NewsCategory
    symbol: str | None
    name: str | None
    title: str
    summary: str | None
    content: str | None
    url: str | None
    source: str
    published_at: datetime | None
    fetched_at: datetime
    data_version: str
    generated: bool
    source_ids: list[str]

class WatchlistNewsResponse(BaseModel):
    category: NewsCategory
    items: list[WatchlistNewsItem]
    selected_symbol: str | None
    query: str | None
    as_of: datetime | None
    stale: bool
    source_status: Literal["ok", "empty", "stale", "unavailable", "invalid"]
    source_message: str | None
    watchlist_count: int
    next_cursor: str | None
```

接口使用：

```text
GET /api/watchlist/news
  ?category=announcement|public_news|today_highlight
  &symbol=000001.SZ                 # 可选，必须属于当前用户自选
  &q=业绩                           # 可选，标题/摘要/来源检索
  &limit=30                         # 1..100，默认 30
  &cursor=...                       # 可选，稳定分页游标

GET /api/watchlist/news/{item_id}
  # 详情接口仍校验当前用户是否能访问 item.symbol；公共今日要点保留 source_ids
```

三类数据口径：

- `announcement` 映射 VibePublic 或 Vibe-Research 内置公开公告，按 `announcement_date` 排序，详情必须保留公告原文链接或稳定哈希 ID。
- `public_news` 映射 VibePublic 或 Vibe-Research 内置个股公开新闻，按 `published_at` 排序；无正文时只展示标题、摘要和来源，不把标题拼成正文。
- `today_highlight` 以当前用户自选股的公告/新闻为输入生成 3–5 条客观要点；每条必须携带 `source_ids`，没有 AI 配置时返回“无可生成要点/数据不可用”状态而不是固定演示文字。

---

### Task 0: 锁定现有工作区基线和兼容边界

**Files:**
- Read: `git status --short`, `git diff --name-only`, `backend/app/main.py`, `frontend/src/components/AuthGate.tsx`
- Create: `backend/tests/test_news_baseline_scope.py`

**Interfaces:**
- Consumes: 当前工作区所有未提交改动、现有认证/用户上下文和 provider 路由。
- Produces: 本轮允许修改文件清单、回归命令和不触碰的页面清单；不修改生产数据、不删除现有用户文件。

- [x] **Step 1: 保存工作区快照并分类已有修改**

Run: `git status --short; git diff --name-only`

将已有改动标记为“用户/前期工作”，本轮只新增资讯相关文件和必要的 `Watchlist.tsx`、`Screener.tsx`、`api.ts`、`queryKeys.ts`、VibePublic 配置扩展；不得使用 `git reset --hard`、`git checkout --` 或删除现有 `data/`。

- [x] **Step 2: 写不影响既有页面的契约测试**

```python
def test_news_capability_does_not_grant_market_data_capabilities():
    caps = capabilities_for_provider_with_news_only()
    assert caps.daily is False
    assert caps.realtime is False
    assert caps.news is True

def test_auth_context_is_reset_after_background_user_job():
    run_user_job_and_raise_after_binding(user_id="a")
    assert current_user() is None
```

- [x] **Step 3: 运行基线验证**

Run: `cd backend; uv run pytest tests/test_user_data_isolation.py tests/test_ai_profile_isolation.py -q; cd ../frontend; pnpm build`

Expected: 基线测试/构建结果记录在实施报告中；如果基线已失败，先区分前期失败与本轮改动，不通过改资讯代码掩盖无关失败。

### Task 1: 确认 VibePublic API 契约并扩展独立资讯 provider

**Files:**
- Create: `data/data_sources/vibe_public.yaml`（仅写入你提供并验证过的公告、公开新闻、RSS/资讯 API 配置）
- Create: `backend/app/data_providers/vibe_public_config.py`（解析资讯 API、认证、分页、限流和字段映射配置）
- Create: `backend/app/data_providers/vibe_public_provider.py`（新增 `get_news(category, symbols, start_time, end_time, query, limit)` 批量方法）
- Create: `backend/app/data_providers/vibe_research_provider.py`（复用已移植的 Vibe-Research 公开公告/个股新闻源）
- Create: `backend/app/data_providers/news_registry.py`（独立加载/重载 VibePublic，不改变现有 custom/TeaJoin 数据 provider）
- Modify: `backend/app/data_providers/base.py`（定义 provider 的资讯能力协议，不改变日线/实时方法签名）
- Create: `backend/app/data_providers/news_contract.py`（标准字段、字段完整性和时间/代码校验）
- Test: `backend/tests/test_news_provider_contract.py`
- Test: `backend/tests/test_vibe_public_provider.py`

**Interfaces:**
- Consumes: 你接入的 VibePublic API 实际 HTTP 请求方式、认证方式、请求参数名、响应路径和字段映射。
- Produces: `NewsProvider.get_news(...) -> pl.DataFrame`，至少返回 `id/category/symbol/title/source/published_at/url/summary`；能力缺失时抛出可分类的 `ProviderCapabilityError`。

- [x] **Step 1: 写失败契约测试**

```python
def test_news_provider_normalizes_vibe_public_fields_without_guessing():
    provider = fake_provider_with_news_response({
        "article_id": "n-1", "ts_code": "000001.SZ", "headline": "公告标题",
        "pub_time": "2026-08-18 10:30:00", "media": "VibePublic",
        "url": "https://example.invalid/n-1",
    })
    frame = provider.get_news("announcement", ["000001.SZ"], limit=10)
    assert frame.select("id", "symbol", "title", "published_at").to_dicts() == [{
        "id": "n-1", "symbol": "000001.SZ", "title": "公告标题",
        "published_at": datetime(2026, 8, 18, 10, 30),
    }]

def test_news_provider_rejects_missing_title_and_symbol():
    provider = fake_provider_with_news_response({"article_id": "n-2", "pub_time": "2026-08-18"})
    with pytest.raises(ProviderContractError):
        provider.get_news("public_news", ["000001.SZ"], limit=10)
```

- [x] **Step 2: 运行测试确认当前失败**

Run: `cd backend; uv run pytest tests/test_news_provider_contract.py -q`

Expected: FAIL，因为当前 provider 没有资讯数据集和 `get_news` 方法。

- [x] **Step 3: 实现最小标准化边界**

新增 `normalize_news_rows`，只接受配置明确映射到标准字段的值；时间统一为带 Asia/Shanghai 语义的 UTC-aware `datetime`，代码统一为 `000001.SZ`，去重键为 `(category, id)`，缺少必填字段直接报告 `invalid`，不填默认值。

- [x] **Step 4: 运行 provider 测试**

Run: `cd backend; uv run pytest tests/test_news_provider_contract.py tests/test_vibe_public_provider.py -q`

Expected: PASS；无资讯能力的 provider 测试仍明确返回能力缺失，不影响 daily/kline/realtime。

- [x] **Step 5: 接入并验证原 Vibe-Research 公开源**

`news_registry` 在没有外部 `vibe_public.yaml` 时选择 `VibeResearchProvider`。其底层调用当前仓库已经移植的 `stock_insight.announcements` 和 `stock_insight.stock_news`，并做统一字段、时区、稳定 ID 和 15 分钟缓存。已用真实 `600519` 请求验证公告和新闻均返回 2026-08-15 数据。

- [ ] **Step 6: 写入并验证真实 VibePublic 配置**（等待实际 API 契约）

Run: `cd backend; uv run pytest tests/test_news_provider_contract.py tests/test_vibe_public_provider.py -q; uv run ruff check app/data_providers/news_contract.py app/data_providers/vibe_public_provider.py app/data_providers/vibe_public_config.py app/data_providers/news_registry.py`

仅当你提供的 VibePublic 实际 endpoint、字段映射和授权边界已由接口测试证明后，才让它覆盖内置 provider；若某一类接口不可用，该类保持未启用并返回 `unavailable`，不得偷偷改用 TickFlow、TeaJoin 或未审计的数据源。

### Task 2: 建立批量资讯服务、共享缓存和用户自选过滤

**Files:**
- Create: `backend/app/services/watchlist_news.py`
- Create: `backend/app/api/watchlist_news.py`
- Modify: `backend/app/main.py`（注册新 router 和后台预加载器）
- Create: `backend/app/services/news_user_store.py`（用户专属今日要点/已读状态，workspace 路径和跨进程锁）
- Modify: `backend/app/services/user_context.py`（只复用现有上下文；必要时增加可测试的用户符号解析入口，不改变目录规则）
- Create: `backend/tests/test_watchlist_news_service.py`
- Create: `backend/tests/test_watchlist_news_api.py`
- Create: `backend/tests/test_news_user_store.py`

**Interfaces:**
- Consumes: `NewsProvider.get_news`、`watchlist.list_symbols()`、`repo.get_name_map()`、`current_user()`。
- Produces: `get_watchlist_news(request, category, symbol, query, limit, cursor) -> WatchlistNewsResponse`；公共文章缓存与用户过滤分离，缓存键包含 provider/category/date/data_version，不能用用户一份缓存覆盖另一用户的筛选结果。

- [x] **Step 1: 写用户隔离、批量请求和失败分类测试**

```python
def test_news_query_only_returns_symbols_from_current_user_watchlist(client, user_a, user_b):
    seed_news("000001.SZ", "A 股公告")
    with as_user(user_a):
        assert client.get("/api/watchlist/news?category=announcement").json()["watchlist_count"] == 1
    with as_user(user_b):
        body = client.get("/api/watchlist/news?category=announcement").json()
        assert body["items"] == []
        assert body["watchlist_count"] == 0

def test_news_query_uses_one_batched_provider_call():
    provider = RecordingNewsProvider(rows=[
        {"id": "n-1", "category": "public_news", "symbol": "000001.SZ", "title": "A"},
        {"id": "n-2", "category": "public_news", "symbol": "600000.SH", "title": "B"},
    ])
    response = get_watchlist_news_for_test(provider, ["000001.SZ", "600000.SH"], "public_news")
    assert provider.calls == [("public_news", ["000001.SZ", "600000.SH"])]
    assert response.source_status == "ok"

def test_stale_and_unavailable_are_distinct():
    assert get_response_with_provider_error("timeout").source_status == "unavailable"
    assert get_response_from_expired_cache().source_status == "stale"

def test_client_cannot_select_another_user_workspace():
    with as_user(user_a):
        response = client.get("/api/watchlist/news?category=announcement&user_id=" + user_b.id)
    assert response.status_code in (400, 403)
    assert "user_id" not in response.json().get("items", [{}])[0]
```

- [x] **Step 2: 运行测试确认失败**

Run: `cd backend; uv run pytest tests/test_watchlist_news_service.py tests/test_watchlist_news_api.py -q`

Expected: FAIL，因为当前不存在资讯 service/router。

- [x] **Step 3: 实现规范化查询服务**

先解析当前用户的 `symbols`，若传入 `symbol` 不属于该列表返回 403/400；对 provider 一次批量请求并在服务层按 category、published_at、symbol、query 过滤；详情页只读取规范化缓存中的 `id`，不再次直连外部源。

缓存采用“共享规范化文章 + 用户请求期过滤”：共享层只保存公开文章及来源元数据，用户层不保存其他账户的自选或搜索词。用户专属摘要/已读状态由 `news_user_store.py` 写入当前 `request.state.user_data_root / user_data / watchlist_news.json`；写入前先取得同路径 sidecar 锁，写临时文件并原子替换，失效时保留最后有效快照并标记 `stale`。服务层不得接受或拼接用户传入的 workspace 路径。

- [x] **Step 4: 实现 API 和错误响应**

`GET /api/watchlist/news` 只做参数校验、调用 service 和响应映射；`limit` 限制 1–100，`q` 统一 Unicode trim，`symbol` 校验标准格式；provider 能力缺失返回 503 且 `source_status=unavailable`，不要把 501/502 转成空数组。`GET /api/watchlist/news/{item_id}` 必须重新按当前账户过滤并校验文章 category/provider，不能仅凭公开 item_id 放行。

- [x] **Step 5: 运行后端链路验证**

Run: `cd backend; uv run pytest tests/test_watchlist_news_service.py tests/test_watchlist_news_api.py tests/test_user_data_isolation.py -q; uv run ruff check app/services/watchlist_news.py app/api/watchlist_news.py`

Expected: PASS；确认两个账户相同自选代码和不同自选代码的响应不会交叉，且批量 provider 调用次数为 1（按受限批次计）。

### Task 3: 后台预加载与“今日要点”生成链路

**Files:**
- Create: `backend/app/services/news_preloader.py`
- Modify: `backend/app/main.py`（启动/停止预加载线程或 APScheduler job）
- Modify: `backend/app/jobs/daily_pipeline.py`（仅接入交易日/盘后触发，不改行情计算）
- Create: `backend/tests/test_news_preloader.py`

**Interfaces:**
- Consumes: `AccountStore.list_users()`、每个账户的 `ensure_workspace()`、VibePublic news provider、现有 AI provider 的结构化生成入口。
- Produces: `news_preloader_status()`、规范化公告/新闻共享缓存，以及每个账户 workspace 内带 `source_ids` 的 `today_highlight` 结果；预加载器不得返回另一个账户的摘要文本。

- [x] **Step 1: 写预加载节奏和失败保留测试**

```python
def test_preloader_deduplicates_symbols_across_accounts():
    accounts = [["000001.SZ", "600000.SH"], ["600000.SH", "300750.SZ"]]
    assert collect_symbol_union(accounts) == ["000001.SZ", "600000.SH", "300750.SZ"]

def test_preloader_keeps_last_valid_snapshot_on_provider_failure():
    cache = CacheSnapshot(items=[{"id": "n-1"}], fetched_at=utc_now())
    result = refresh_cache(cache, provider=FailingProvider())
    assert result.items == cache.items
    assert result.source_status == "stale"

def test_highlight_is_written_under_the_bound_account_workspace():
    run_preloader_for_user(user_a, ["000001.SZ"])
    run_preloader_for_user(user_b, ["600000.SH"])
    assert read_highlight(user_a).symbols == ["000001.SZ"]
    assert read_highlight(user_b).symbols == ["600000.SH"]
```

- [x] **Step 2: 运行测试确认失败**

Run: `cd backend; uv run pytest tests/test_news_preloader.py -q`

Expected: FAIL，因为当前没有资讯预加载器。

- [x] **Step 3: 实现有边界的后台刷新**

交易时段公告/新闻按 5–10 分钟刷新，盘后至少刷新一次；任务不在 HTTP 请求中执行，不在持锁期间请求网络，设置单次超时、有限重试和退避。第一阶段只把所有账户自选的去重并集用于一次公共文章抓取；抓取完成后，逐账户绑定 `set_current_user`，读取该账户自选并生成其摘要，写入该账户 workspace。任何异常都必须在 `finally` 中 reset ContextVar。

- [x] **Step 4: 实现今日要点的可追溯结果**

先以确定性规则按时间、来源和 symbol 选取当前账户输入，再调用该账户解析出的 AI profile；模型输出必须通过 Pydantic schema 校验为 `{title, summary, symbol, source_ids[]}`，且 `source_ids` 必须全部属于当前账户自选文章。没有 AI 或输入为空时返回明确状态，不写入演示文本；生成结果记录 `user_id`（仅存储在用户 workspace，不回传给其他账户）、`model_version/prompt_version/data_version/generated_at`。不能把多个账户的文章拼成一个共享摘要。

- [x] **Step 5: 运行预加载与调度测试**

Run: `cd backend; uv run pytest tests/test_news_account_isolation.py tests/test_dashboard_preload.py -q`

Expected: PASS；停止应用时任务可退出，provider 超时不会阻塞普通 API。

### Task 4: 自选页三个入口与弹窗内搜索/详情

**Files:**
- Create: `frontend/src/components/WatchlistNewsModal.tsx`
- Modify: `frontend/src/pages/Watchlist.tsx`（PageHeader 下方插入入口；只挂载一个 modal，并在自选变更后失效当前账户资讯 query）
- Modify: `frontend/src/pages/Screener.tsx`（自选添加/删除成功后只失效当前账户资讯 query，不改变筛选结果逻辑）
- Modify: `frontend/src/lib/api.ts`（新增资讯类型和 `watchlistNews`/`watchlistNewsDetail`）
- Modify: `frontend/src/lib/queryKeys.ts`（新增用户、category、symbol、q、cursor 全维度查询键）
- Modify: `frontend/src/pages/StockAnalysis.tsx`（确认 URL `symbol`/`name` 初始化链路保持兼容，不改变分析业务）
- Test: 当前仓库没有前端组件测试运行器；使用 TypeScript 构建、ESLint 和人工冒烟覆盖

**Interfaces:**
- Consumes: `WatchlistNewsResponse`、当前用户 `QK.watchlistFor(user.id)`、现有 `Modal`、`useNavigate`、`api.instrumentSearch`。
- Produces: `onOpen(category)`；弹窗状态包括 `category`、`selectedSymbol`、`query`、`selectedItem`，关闭后清空临时搜索和详情状态。

- [x] **Step 1: 写前端行为测试/验收清单**

```text
1. 自选页 PageHeader 下出现“ A 股公告 / 公开新闻 / 今日要点 ”三个按钮。
2. 点击按钮只打开居中的 Modal，页面下方没有新增资讯长列表。
3. Modal 内搜索标题/来源，切换自选股票过滤，loading/empty/error/stale 状态可见。
4. 点击条目显示标题、来源、发布时间、摘要、原文链接和关联股票。
5. 点击关联股票关闭弹窗并跳转 `/stock-analysis?symbol=000001.SZ&name=平安银行`。
6. 切换账户后 query key 不复用上一账户的资讯响应。
```

- [x] **Step 2: 运行现有前端验证确认缺失接口**

Run: `cd frontend; pnpm build`

Expected: 当前代码可构建，但新组件/API 尚不存在；该步骤用于保存未修改基线。

- [x] **Step 3: 实现 API 类型与查询键**

`api.watchlistNews({ category, symbol, q, limit, cursor, signal })` 必须把所有影响结果的参数编码到 URL，并把 TanStack Query 的 `signal` 传给 fetch；`QK.watchlistNewsFor(user.id, category, symbol, q, cursor)` 必须包含 user id，避免账户切换时旧请求写入新账户缓存。禁止在 API 客户端或组件中读取/拼接 workspace 路径。

- [x] **Step 4: 实现 Tab 与 Modal**

Tab 仅负责打开 modal；Modal 内部采用“顶部分类 + 搜索按钮/输入框 + 自选股票选择 + 列表 + 当前条目详情”布局，内部内容区 `overflow-y-auto`，不改变页面主滚动。搜索请求使用 250–300ms debounce，股票候选先从当前用户 watchlist 过滤；不属于当前自选的代码不可作为详情查询参数。切换 category、symbol、账户或关闭 Modal 时重置 selectedItem，避免把上一股票详情显示在下一账户/下一类别下。

- [x] **Step 5: 接通股票分析跳转并构建**

详情中的关联股票按钮执行：

```tsx
const navigate = useNavigate()
const openStock = (item: WatchlistNewsItem) => {
  if (!item.symbol) return
  navigate(`/stock-analysis?symbol=${encodeURIComponent(item.symbol)}&name=${encodeURIComponent(item.name ?? '')}`)
  onClose()
}
```

Run: `cd frontend; pnpm build; cd ..; git diff --check`

Expected: PASS，且弹窗在桌面、窄屏下文字不被遮挡，内部列表可滚动、页面主体不出现额外资讯长列表。

### Task 5: 联调、回归和灰度发布

**Files:**
- Create: `docs/vibe-public-news.md`（新增资讯 API 契约、字段单位、授权边界和接入/测试方式；不改 TeaJoin 市场数据文档）
- Create: `backend/tests/test_news_router_registration.py`
- Create: `backend/tests/test_news_account_isolation.py`
- Modify: `frontend/src/lib/queryKeys.ts`（资讯查询键保持用户维度，不加入高频 SSE 失效前缀）

**Interfaces:**
- Consumes: Tasks 1–4 的 provider、service、API、preloader、UI。
- Produces: 可关闭的 `watchlist_news_radar_enabled` feature flag、健康检查状态、人工联调路径。

- [x] **Step 1: 写关键链路回归测试**

```python
def test_news_end_to_end_has_no_cross_account_leakage(api_client, provider):
    create_user("a", watchlist=["000001.SZ"])
    create_user("b", watchlist=["600000.SH"])
    assert get_news_as("a", "announcement").symbols == ["000001.SZ"]
    assert get_news_as("b", "announcement").symbols == ["600000.SH"]
    assert provider.batch_call_count == 1

def test_user_highlight_files_and_ai_profiles_are_separate():
    save_highlight_as("a", symbols=["000001.SZ"], source_ids=["a-1"])
    save_highlight_as("b", symbols=["600000.SH"], source_ids=["b-1"])
    assert read_highlight_as("a").source_ids == ["a-1"]
    assert read_highlight_as("b").source_ids == ["b-1"]

def test_foreign_symbol_and_foreign_item_id_are_denied():
    assert get_news_as("a", "announcement", symbol="600000.SH").status_code == 403
    assert get_detail_as("a", item_id="b-1").status_code in (403, 404)
```

- [x] **Step 2: 运行后端、前端和格式验证**

Run:

```bash
cd backend
uv run pytest tests/test_news_provider_contract.py tests/test_vibe_public_provider.py tests/test_news_account_isolation.py tests/test_watchlist_news_api.py tests/test_news_router_registration.py -q
uv run ruff check app/data_providers/news_contract.py app/data_providers/vibe_public_config.py app/data_providers/vibe_public_provider.py app/data_providers/news_registry.py app/services/news_user_store.py app/services/watchlist_news.py app/services/watchlist_news_preloader.py app/api/watchlist_news.py

cd ../frontend
pnpm build

cd ..
git diff --check
```

Expected: 受影响后端测试、Ruff、前端构建全部 PASS；任何失败都不能标记为上线完成。还需运行不涉及资讯的关键回归页面测试，确认 provider 扩展没有改变 dashboard、screener、kline、financials 和 stock-analysis 的既有返回结构。

- [x] **Step 3: 内置源灰度启用**

当前默认使用已验证的 Vibe-Research 公开源；外部配置仍需单独灰度。健康检查展示 provider、capabilities、preloader 状态和接口返回的 `source_status`。

- [ ] **Step 4: 人工验收**（等待真实 API 配置）

1. 账户 A 添加两只股票，账户 B 添加不同股票；分别打开三个入口，确认列表、搜索结果和股票详情不交叉。
2. 在公告/新闻条目点关联股票，确认进入 `/stock-analysis` 且代码和名称已填入。
3. 断开当前公开源或外部 VibePublic 接口，确认弹窗显示“数据源不可用/陈旧”，不出现固定演示内容；恢复后点击刷新或等待预加载恢复。
4. 在交易时段观察预加载日志和 provider 状态，确认页面打开不会触发逐股票 N+1 请求。
5. 退出账户 A 后立刻进入账户 B，确认旧请求取消、弹窗关闭、旧文章和旧摘要不残留；直接修改 URL 的 `user_id` 或 workspace 参数必须无效。
6. 重启后端/启动两个 worker，确认共享文章缓存不损坏，两个账户的摘要文件仍分别可读，重复预加载不会覆盖另一账户。

- [x] **Step 5: 回滚准备**

在 `vibe_public.yaml` 中设置 `enabled: false` 或移除新增 router 即可关闭资讯入口；资讯缓存是新增数据，不删除现有 watchlist、K 线或财务文件；若外部 provider 配置不兼容，只撤回 VibePublic dataset 配置，不回滚现有 TeaJoin 数据集。

## 自审结论

- 需求覆盖：三个入口、Investment News 改名、弹窗而非页面下方板块、搜索、选股详情、个股分析跳转、VibePublic 接入、用户隔离、预加载、失败状态和回滚均有对应任务。
- 未复制旧项目的 N+1、localStorage 自选、单文件全局缓存或浏览器侧无来源 AI 文本。
- 第二轮审计已补齐：用户摘要不能共享、后台必须绑定账户上下文、客户端不能指定 user_id/workspace、账户切换必须取消请求、provider news 能力不能污染行情能力、多 worker 需要跨进程写锁、路由和自选变更失效都有回归测试。
- 原先项目之所以有数据，是因为它的 `astock.py` 直接调用东财公告接口和个股新闻搜索接口，并由 `newsradar.py` 单独抓 RSS；当前项目此前只完成了 `stock_insight.py` 的移植，却没有把它接入新的 watchlist-news registry。本轮已补上内置 provider，并用真实 600519 公告/新闻请求验证；后续切换到你的自有 VibePublic API 仍需提供接口契约。
- 没有删除或修改现有用户数据、策略、行情、财务和 K 线结构，回滚路径为关闭开关或移除新增资讯路由/配置。
