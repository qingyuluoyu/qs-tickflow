"""清数一号 — A 股确定性研究候选筛选与盘后关注条件。"""

import polars as pl

META = {
    "id": "qingshu_one",
    "name": "清数一号",
    "description": "从原规则池中保留实测最容易通过的 6 项量价规则,默认命中 4 项即入选",
    "tags": ["基本面", "涨停", "量价", "研究候选"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "params": [
        {"id": "market_cap_min_yi", "label": "最低总市值(亿元)", "type": "float", "default": 150.0, "min": 0.0},
        {"id": "recent_limit_up_min_count", "label": "近 120 日涨停次数", "type": "int", "default": 3, "min": 1, "max": 120},
        {"id": "volume_multiple", "label": "连续放量倍数", "type": "float", "default": 2.0, "min": 1.0, "max": 20.0},
        {"id": "gap_open_min_pct", "label": "最小高开幅度(%)", "type": "float", "default": 3.5, "min": 0.0, "max": 20.0},
        {"id": "amplitude_min_pct", "label": "最小振幅(%)", "type": "float", "default": 9.8, "min": 0.0, "max": 100.0},
        {"id": "min_rule_matches", "label": "6 项规则最少命中数", "type": "int", "default": 4, "min": 1, "max": 6},
    ],
    "basic_filter": {
        "price_min": 3,
        "price_max": 300,
        "market_cap_min": None,
        "amount_min": None,
        "exclude_st": True,
        "exclude_new_days": 30,
    },
    "scoring": {"change_pct": 0.4, "vol_ratio_5d": 0.3, "momentum_20d": 0.3},
    "order_by": "score",
    "descending": True,
    "limit": 100,
    # 量价规则只依赖按交易日可获得的行情字段;财务/股东快照不再作为
    # 硬门槛,避免数据源尚未提供这两个极端指标时整策略归零。
    "data_requirements": {
        "market": ["daily", "adj_factor", "stk_limit", "daily_basic"],
    },
    "data_policy": "market_fields_required_optional_fundamentals",
}

EXECUTION_BACKEND = "python_history_legacy"
LOOKBACK_DAYS = 130  # 120 日涨停/放量窗口 + 10 日候选基准; 受选股历史加载窗口限制
ENTRY_SIGNALS: list[str] = []
EXIT_SIGNALS: list[str] = []
STOP_LOSS = -0.08
MAX_HOLD_DAYS = 20
ALERTS: list[dict] = []

RULES = """
历史数据至少覆盖 125 个交易日;价格、ST 和上市天数仍按基础过滤执行。

以下 6 项规则中默认至少满足 4 项即可入选 (按真实行情实测通过率从高到低保留):
1. 近 120 个交易日内出现过连续 3 日成交量达到此前 20 日均量的 2 倍。
2. 近 10 个交易日无跌幅达到 5% 的阴线。
3. 近 120 个交易日至少 3 次收盘涨停。
4. 总市值严格大于 150 亿元。
5. 近 10 个交易日存在收盘涨停。
6. 当日收盘真实涨停, 或高开 >= 3.5% 且收阳, 或振幅 > 9.8% 且收阳。

原规则池中的"360 日新高"(通过率仅 2.8%)与"一年内连板"(0.2%)因过于苛刻被移除;
年度 ROE 和机构股东数因数据经常缺失早已移除,不再作为门槛。
"""


def _empty(df: pl.DataFrame) -> pl.DataFrame:
    return df.head(0)


def filter_history(df: pl.DataFrame, params: dict) -> pl.DataFrame:
    """按交易日计算清数一号规则, 数据不足时 fail-closed。

    基本面字段是 point-in-time 预计算值, 不从当前日期之后的数据回填。
    这里不使用 demo.py 或外部模块的模拟数据。
    """
    required = {
        "symbol",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "total_shares",
        "signal_limit_up",
    }
    if df.is_empty() or not required <= set(df.columns):
        return _empty(df)

    cap_min_yi = float(params.get("market_cap_min_yi", 150.0))
    recent_lu_min = int(params.get("recent_limit_up_min_count", 3))
    volume_multiple = float(params.get("volume_multiple", 2.0))
    gap_min = float(params.get("gap_open_min_pct", 3.5)) / 100.0
    amplitude_min = float(params.get("amplitude_min_pct", 9.8)) / 100.0
    min_rule_matches = max(1, min(6, int(params.get("min_rule_matches", 4))))

    work = (
        df.sort(["symbol", "date"])
        .with_columns(
            pl.col("date").cast(pl.Date, strict=False),
            pl.col("signal_limit_up").fill_null(False).cast(pl.Int8).alias("_limit_up"),
            pl.col("close").shift(1).over("symbol").alias("_prev_close"),
            pl.col("volume").shift(1).rolling_mean(window_size=20, min_samples=20).over("symbol").alias("_volume_base"),
            pl.col("date").cum_count().over("symbol").alias("_bar_count"),
        )
        .with_columns(
            pl.col("_limit_up").rolling_sum(window_size=10, min_samples=10).over("symbol").alias("_limit_count_10"),
            pl.col("_limit_up").rolling_sum(window_size=120, min_samples=120).over("symbol").alias("_limit_count_120"),
            (pl.col("volume") >= pl.col("_volume_base") * volume_multiple).cast(pl.Int8).alias("_volume_expanded"),
            ((pl.col("high") - pl.col("low")) / pl.col("_prev_close").abs()).alias("_amplitude"),
            (pl.col("open") / pl.col("_prev_close") - 1.0).alias("_gap_open"),
            (pl.col("close") / pl.col("_prev_close") - 1.0).alias("_change"),
        )
        .with_columns(
            pl.col("_volume_expanded").rolling_sum(window_size=3, min_samples=3).over("symbol").alias("_expanded_3"),
        )
        .with_columns(
            pl.col("_expanded_3").rolling_max(window_size=120, min_samples=1).over("symbol").alias("_expanded_120"),
        )
    )

    # Each business rule is counted independently. Nulls are false, so an
    # incomplete row cannot pass through as a zero/default value.
    trigger = (
        (pl.col("_limit_up") == 1)
        | ((pl.col("_gap_open") >= gap_min) & (pl.col("close") > pl.col("open")))
        | ((pl.col("_amplitude") > amplitude_min) & (pl.col("close") > pl.col("open")))
    )
    rules = [
        (pl.col("_expanded_120") >= 3).fill_null(False),
        ~((pl.col("close") < pl.col("open")) & (pl.col("_change") <= -0.05))
        .rolling_max(window_size=10, min_samples=10)
        .over("symbol")
        .fill_null(0)
        .cast(pl.Boolean),
        pl.col("_limit_count_120") >= recent_lu_min,
        pl.col("close") * pl.col("total_shares") > cap_min_yi * 1e8,
        pl.col("_limit_count_10") >= 1,
        trigger,
    ]
    scored = work.with_columns(
        pl.sum_horizontal(*(rule.fill_null(False).cast(pl.Int8) for rule in rules))
        .alias("qingshu_rule_matches"),
        trigger.fill_null(False).alias("qingshu_triggered"),
    )
    candidate = (
        (pl.col("_bar_count") >= 125)
        & (pl.col("qingshu_rule_matches") >= min_rule_matches)
    )
    return (
        scored.with_columns(
            candidate.fill_null(False).alias("qingshu_candidate_qualified"),
        )
        .filter(candidate.fill_null(False))
        .with_columns(
            pl.when(pl.col("qingshu_triggered"))
            .then(pl.lit("triggered"))
            .otherwise(pl.lit("qualified"))
            .alias("qingshu_status")
        )
    )
