# 金融数据口径与来源一致性实施计划

> **For agentic workers:** 本计划在当前工作区内按测试先行执行；不覆盖既有用户修改。

**目标：** 让行情截止日、TeaJoin 数据来源、单位转换和新鲜度状态在看板、策略、K 线和财务分析之间保持一致，避免静默使用过期、混源或单位错误的数据。

**架构：** 在现有 provider 边界增加校验与来源元数据，在市场时间服务增加交易日历适配；不改前端页面结构、不替换现有数据存储。TeaJoin 仍是主源，fallback 只能保留最后有效快照并明确来源状态。

**技术栈：** Python 3.11、FastAPI、Polars、DuckDB/Parquet、pytest。

## 全局约束

- 保留当前工作区已有修改，不执行 reset、checkout 或大范围格式化。
- 保持现有 provider 抽象、API 字段兼容和 TeaJoin 配置兼容。
- 金融内部口径：涨跌幅小数、成交量手、成交额人民币、价格人民币/股；复权和原始价格必须分开。
- 数据源失败、数据过期、字段缺失和解析失败不得统一伪装为空数组或零值。

### 任务 1：交易日历与截止日

**文件：** `backend/app/market_time.py`、`backend/tests/test_market_time.py`（若已存在则追加测试）。

- 先新增失败测试：节假日不应被 `previous_trading_day` 当成交易日，交易时段边界仍按北京时间处理。
- 实现一个可注入的交易日集合/回调，默认使用已有周末逻辑，配置交易日历后优先查询节假日；保持现有函数签名兼容。
- 让 `resolve_market_as_of` 和新鲜度判断使用同一日历解析路径。
- 运行定向 pytest，再运行所有受影响市场时间/看板新鲜度测试。

### 任务 2：TeaJoin 来源与快照状态

**文件：** `backend/app/services/market_overview_preloader.py`、`backend/app/services/quote_service.py`、`backend/tests/test_quote_provider_cutover.py`、`backend/tests/test_dashboard_preload.py`。

- 先新增失败测试：TeaJoin 失败时不得把新浪数据写成正式历史/策略快照；返回必须带来源和过期状态。
- 保留 TeaJoin 主源；fallback 只允许作为显示快照，或继续使用最近一次通过校验的 TeaJoin 快照。
- 为快照补充 `provider`、`data_as_of`、`fetched_at`、`is_stale`、`fallback_reason`，不删除已有响应字段。
- 运行 provider cutover、dashboard preload 和 freshness 测试。

### 任务 3：单位与数据质量校验

**文件：** `backend/app/data_providers/normalizer.py`、`backend/app/data_providers/custom/provider.py`、相关 provider 测试。

- 先新增失败测试：百分比、成交额、成交量、OHLC 越界或单位变化时必须拒绝快照并报告字段错误。
- 在 provider 输出进入计算层前执行显式类型、范围、日期、重复证券和单位契约校验；使用当前 TeaJoin/Tushare 兼容转换，不依赖数值大小猜测单位。
- 保持现有有效数据路径不变，失败时返回结构化数据质量错误，供上层显示过期或源失败状态。
- 运行所有 TeaJoin provider、normalizer、pipeline 和 API 相关测试。

### 任务 4：特殊涨跌停与财务分析口径

**文件：** `backend/app/price_limits.py`、`backend/app/services/financial_view.py`、`backend/app/services/financial_analyzer.py`、对应测试。

- 为 IPO、重新上市、停牌、ST 和无涨跌停状态增加回归用例。
- 财务分析输入只使用带单位的规范字段，并区分报告期与公告可获得时间；保留现有 API 兼容别名。
- 运行后端完整测试、ruff、前端构建和 `git diff --check`。

## 验证命令

```powershell
Set-Location backend
uv run pytest tests/test_market_time.py tests/test_market_overview_freshness.py tests/test_dashboard_preload.py tests/test_quote_provider_cutover.py tests/test_teajoin_provider.py -q
uv run ruff check app/market_time.py app/data_providers/normalizer.py app/data_providers/custom/provider.py app/services/market_overview_preloader.py app/services/quote_service.py
Set-Location ..
git diff --check
```
