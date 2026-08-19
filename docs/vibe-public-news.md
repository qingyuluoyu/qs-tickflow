# VibePublic 资讯接入说明

`VibePublic` 是本项目内部的可配置资讯 provider 名称，不是一个写死的外部地址。部署时可以把真实 API 契约写入 `DATA_DIR/data_sources/vibe_public.yaml`；没有该文件时，系统会使用已经移植并验证过的 Vibe-Research 公告/个股新闻公开源（当前实现位于 `backend/app/services/stock_insight.py`）。只有显式存在且 `enabled: false` 的配置才会关闭资讯；无论哪条路径都不会回退到 TickFlow 或 TeaJoin 行情数据。

## 必须提供的接口契约

每个 `announcement`、`public_news` 数据集都需要确认：

- URL 和 HTTP 方法；
- 认证方式（无认证、Bearer、请求头、查询参数或 JSON body）；
- 股票代码参数的名称、列表格式（数组或逗号分隔）；
- 起止时间、搜索词、分页游标和数量参数的名称及格式；
- 响应中资讯数组的 dot-path；
- 外部字段到内部字段的映射：`id`、`symbol`、`name`、`title`、`summary`、`content`、`url`、`source`、`published_at`；
- 下一页游标字段（如有）和时间/时区口径；
- 允许的调用频率和授权范围。

`title` 是必需字段。没有稳定文章 ID 时，provider 会基于 provider、分类、股票、发布时间、标题和 URL 生成稳定哈希 ID；不会把标题伪装成正文。

## 数据流

```text
VibePublic API（如配置）或 Vibe-Research 内置公开源
  -> provider（请求、限流/缓存、字段校验、时间标准化）
  -> 共享只读 public article cache
  -> 当前 session 的自选股过滤
  -> /api/watchlist/news 弹窗
```

“今日要点”不是共享摘要：后台先用所有账户自选的去重并集预取公共文章，再逐个绑定账户上下文，把来源文章转换成该账户 workspace 下的 `news_highlights.json`。每个要点保留 `source_ids`，便于追溯；未配置 AI 时不生成虚构结论。
用户首次打开“今日要点”且后台预加载尚未完成时，服务会先读取当前账户自选范围内的共享公开资讯缓存；缓存为空才按公开新闻、公告各请求一次真实源，并把结果写入当前账户工作区。该回退不会读取其他账户摘要，也不会生成无来源文本。

原项目的 `newsradar.py` 另有一条 12 赛道 RSS（108 个公开源）链路，但 RSS 条目没有股票代码。为避免把行业资讯错误标成某只自选股的消息，当前“今日要点”只使用公告/个股新闻等可追溯的自选股来源；全局 RSS 若要保留，应作为不带股票归属的独立资讯范围接入。

## API

- `GET /api/watchlist/news?category=announcement|public_news|today_highlight&symbol=&q=&limit=&cursor=`
- `GET /api/watchlist/news/{item_id}?category=...`

接口不接受 `user_id` 或 workspace 路径。服务端从 HttpOnly session 获取用户，并校验 `symbol` 属于当前账户自选；详情接口也执行同一校验。

## 配置与验证

真实配置写入后执行：

```text
cd backend
uv run pytest tests/test_news_provider_contract.py tests/test_vibe_public_provider.py tests/test_news_account_isolation.py tests/test_watchlist_news_api.py -q
uv run ruff check app/data_providers/news_contract.py app/data_providers/vibe_public_config.py app/data_providers/vibe_public_provider.py app/data_providers/news_registry.py app/services/news_user_store.py app/services/watchlist_news.py app/services/watchlist_news_preloader.py app/api/watchlist_news.py
```

上线前必须人工验证：两个账户分别添加不同自选，确认公告、新闻和今日要点互不出现；伪造 `user_id`、symbol 或 workspace 参数应被忽略或拒绝；断开上游时页面显示明确的不可用/陈旧状态；恢复接口后后台预加载能更新各账户摘要。
