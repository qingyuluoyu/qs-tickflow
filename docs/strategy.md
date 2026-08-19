# 策略指南

策略是选股引擎、回测、监控的基础。本文介绍策略体系与三种扩展方式。

完整策略开发规范(AI 生成与手写)见 [`backend/app/strategy/prompts/strategy-guide.md`](../backend/app/strategy/prompts/strategy-guide.md)。

---

## 内置策略

**19 个内置策略**,每个策略一个独立 Python 文件,基于统一策略契约实现(`backend/app/strategy/builtin/`):

| 类型        | 代表策略                                                 |
| :---------- | :------------------------------------------------------- |
| 趋势 / 形态 | 趋势突破 · 均线多头 · MA 金叉 · MACD 金叉放量 · 布林突破 |
| 量价 / 涨停 | 量价齐升 · 高换手强势 · 连板股 · 断板反包 · 涨停动量 · 接近涨停 |
| 反转 / 波动 | 超跌反弹 · 超卖反转 · 新低反转 · 低波动龙头 · 回踩 MA20 · 回踩支撑 · 强势开盘 |
| 确定性研究 | 清数一号（6 项市值/量价/触发规则中至少命中 4 项） |

内置目录 `backend/app/strategy/builtin/` 由项目维护,**AI 生成的策略不会落入此目录**。

---

## 扩展策略的三种方式

### 🎛️ 方式一:自定义信号(不写代码)

在选股页 UI 上用 `字段 + 操作符 + 阈值` 组合,编译成 Polars 表达式热加载。适合:

- 快速验证一个简单的筛选思路(如 `RSI < 30 AND 量比 > 2`)
- 不熟悉 Python 但想自定义筛选条件

底层实现在 `backend/app/strategy/custom_signals.py`。

### 🤖 方式二:AI 生成

一句话描述思路,LLM 读取精简运行时指南生成完整策略文件:

1. **配置 AI 接口**(留空即关闭,见 [configuration.md → AI](./configuration.md#ai可选)):
   ```ini
   AI_PROVIDER=openai_compat
   AI_BASE_URL=https://api.deepseek.com
   AI_API_KEY=sk-...
   AI_MODEL=deepseek-v4-flash
   ```
2. 在选股页打开「AI 策略生成器」,用自然语言描述你的策略思路
3. 前端流式接收生成代码,后端经 `ast` 安全校验(禁止 import os/sys/subprocess 等危险模块)后返回结果
4. 保存后落入 `data/strategies/ai/`,文件名/ID 用 `ai_` 前缀

生成策略相关提示词位于 `backend/app/strategy/prompts/`:

- `strategy-guide-compact.md` — AI 运行时精简指南(用于降低长请求超时概率)
- `strategy-guide.md` — 完整策略开发规范(供人工开发和详细参考)
- `strategy-builder-step2.md` — 步骤 2 提示词模板(修改已有策略)
- `strategy-example.md` — 从零创建强势反包策略的三步演示

> 💡 **文件与范围铁律**:AI 生成的策略只生成一个 `.py` 文件,只 `import polars as pl`,绝不修改 `backend/`、`docs/`、`frontend/` 等现有文件。

### 📝 方式三:自定义编写 / 代码迁移

可以在选股页「自定义编写」中直接编辑策略代码并保存,新建自定义策略会落入 `data/strategies/custom/`,文件名/ID 用 `custom_` 前缀。也可以手动把已有策略改写为 Polars 文件后放入该目录,引擎会自动发现。

手写策略需遵循 [`strategy-guide.md`](../backend/app/strategy/prompts/strategy-guide.md) 的文件结构(META / basic_filter / scoring / ENTRY_SIGNALS / filter 等),完整规范见该文档。

## 策略管理与恢复

选股页右上角「管理策略」可以查看当前账户的内置、自定义、AI 和叠加策略。内置策略由平台维护,不能删除;其余策略可以在确认后删除,同时清理当前账户的策略配置和关联监控。

「回退初始版本」会清除当前账户的自定义/AI/叠加策略及策略覆盖配置,恢复为打包的 19 个内置策略,并把策略池恢复为这 19 个内置策略的顺序。该操作不影响自选股、账户、行情和其他页面数据。

「清数一号」的候选过滤只依赖按目标交易日可获得的行情、复权、涨跌停和市值字段。6 项市值/量价/触发规则中默认满足至少 4 项即可入选；历史覆盖、价格、ST 与上市天数仍按基础过滤执行。原先连续年度 ROE、机构股东数以及长期涨停次数/连板条件等过于严格或重复的门槛已移除，避免数据源未提供对应字段时整策略归零；若数据层提供这些字段，可作为扩展展示字段，但不会被默认值替代。

策略仍保留 240/360 日量价窗口，因此生产环境首次使用前必须通过 TeaJoin 扩展至少 380 个交易日的日 K 和复权数据。若本地历史不足，返回 0 个候选是数据覆盖不足的真实结果，不会用短窗口或模拟行伪造命中。

---

## 策略文件结构(简述)

一个策略 `.py` 文件通常包含:

| 部分 | 作用 |
| :--- | :--- |
| `META` | 策略元信息(名称、参数、方向等),用户可在 UI 调整阈值 |
| `basic_filter(df, params)` | 模式 A:单日过滤,返回 `pl.Expr` |
| `filter_history(df, params)` | 模式 B:历史窗口过滤,返回 `pl.DataFrame`(配 `LOOKBACK_DAYS`) |
| `scoring` | 评分权重,总和 = 1.0 |
| `ENTRY_SIGNALS` / `EXIT_SIGNALS` | 进出场信号列(回测用) |

完整字段说明与示例见 [`strategy-guide.md`](../backend/app/strategy/prompts/strategy-guide.md)。

---

## 新增内置策略(贡献者)

如果你想为项目贡献一个内置策略:在 `backend/app/strategy/builtin/` 参照现有文件实现 `StrategyDef`,引擎会自动发现并加载。欢迎提交 PR。
