# 历史股本与换手率修复

维护命令通过当前财务 provider 获取标准股本，不接受密钥命令行参数。
成交量沿用“手”，股本为“股”，enriched 换手率为百分数值：
`volume * 10000 / float_shares`，`1` 表示 `1%`。
历史交易日只使用当时已公告的股本；缺失保持 null，不使用今天的股本回填历史。

## 1. 断点补齐股本

在实际运行容器中执行：

```bash
docker exec -e POLARS_MAX_THREADS=2 TickFlow_Stock_Panel \
  /app/.venv/bin/python -m app.maintenance.rebuild_share_history \
  --batch-size 1 --until-complete
```

- 修复范围是证券维表与已有股票日线证券的并集，包含不在当前维表中的历史证券。
- 仅保存已有日线时间窗口及每只证券窗口前的一条可用股本记录。
- 检查点位于 `financials/shares/rebuild-state.json`。只有完整请求批次成功写入才推进；部分证券响应、空数据、权限错误不算完成。
- 可恢复网络错误有限重试；不可恢复错误停止，不伪造数据。
- 单机维护任务应使用同一文件锁，禁止同时启动两个股本修复写入进程。

## 2. 隔离重算与校验

股本检查点覆盖完整证券范围、历史窗口且标记 complete 后执行：

```bash
docker exec -e POLARS_MAX_THREADS=2 TickFlow_Stock_Panel \
  /app/.venv/bin/python -m app.maintenance.rebuild_enriched_stage --batch-size 100
```

命令复制日线、股本、证券维表和可用复权因子到独立目录，调用原 enriched
管道按显式证券批次计算，不修改线上 enriched、不改全局分批偏好。
复制前后校验完整文件集合和 SHA-256，并重新校验副本内的股本完成状态。

逐日期检查证券/日期键、停牌过滤、原始价、复权价、成交量、成交额及按公告日
解析的历史换手率。缺少维表信息的证券可以用标准历史股本计算换手率；
依赖证券元数据的涨跌停信号、连板计数保持 null，不因相邻批次证券改变。
异常或重复的复权因子、不可解析日期及数值冲突会停止校验。

产物在 `maintenance/enriched-stage-*/manifest.json`，包含输入/输出指纹和：

- `status`: running / validated / failed。
- `rows`、`partitions`、`symbols`、`batches`。
- `missing_turnover_rows`、`missing_turnover_symbols` 及有限样本。
- `ready_for_publication`: 始终 false，表示这个命令不执行发布验收或覆盖。

validated 只表示隔离副本符合数据契约，**不是已部署**。真实不可用的股本仍会
产生缺失计数，依赖这些字段的回测必须明确拒绝，不能呈现为成功零收益。

## 3. 发布门槛与回退

发布前运行真实正常/缺失数据回测，核验股票覆盖与缺失原因。重新检查 live
输入及 enriched 指纹；发生变化时中止，不覆盖新的盘后或盘中数据。
备份已有 enriched，暂停并发写入，在短窗口内原子替换已验收的历史分区，
保持当日实时分区不变。失败时恢复服务和兼容备份；成功后刷新仓库缓存、
检查内外健康状态并通过已登录页面验收。不要删除用户策略、回测结果或私有缓存。

隔离目录和检查点不是数据库结构迁移。复权方式、API 和 Parquet 字段保持兼容。
重算不调用 AI 或数据源；成本主要来自一次性股本补齐请求及本地 CPU/磁盘，
避免在实时线程、启动路径或普通 HTTP 请求中执行。
