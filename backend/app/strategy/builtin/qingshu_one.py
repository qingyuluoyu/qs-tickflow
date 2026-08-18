"""清数一号 — A 股确定性研究候选筛选与盘后关注条件。"""

import polars as pl

META = {
    "id": "qingshu_one",
    "name": "清数一号",
    "description": "市值、连续年度 ROE、机构股东与 9 项量价/触发规则的确定性候选筛选(数据不足时不出候选)",
    "tags": ["基本面", "涨停", "量价", "研究候选"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "params": [
        {"id": "market_cap_min_yi", "label": "最低总市值(亿元)", "type": "float", "default": 150.0, "min": 0.0},
        {"id": "roe_min_pct", "label": "年度 ROE 下限(%)", "type": "float", "default": 10.0, "min": -100.0, "max": 1000.0},
        {"id": "required_annual_roe_years", "label": "连续完整年度数", "type": "int", "default": 5, "min": 1, "max": 10},
        {"id": "institution_holder_min_count", "label": "非自然人股东数", "type": "int", "default": 5, "min": 0, "max": 10},
        {"id": "annual_limit_up_min_count", "label": "近 240 日涨停次数", "type": "int", "default": 6, "min": 1, "max": 240},
        {"id": "volume_multiple", "label": "连续放量倍数", "type": "float", "default": 2.0, "min": 1.0, "max": 20.0},
        {"id": "gap_open_min_pct", "label": "最小高开幅度(%)", "type": "float", "default": 3.5, "min": 0.0, "max": 20.0},
        {"id": "amplitude_min_pct", "label": "最小振幅(%)", "type": "float", "default": 9.8, "min": 0.0, "max": 100.0},
    ],
    "basic_filter": {
        "price_min": 3,
        "price_max": 300,
        "market_cap_min": 150e8,
        "amount_min": None,
        "exclude_st": True,
        "exclude_new_days": 30,
    },
    "scoring": {"change_pct": 0.4, "vol_ratio_5d": 0.3, "momentum_20d": 0.3},
    "order_by": "score",
    "descending": True,
    "limit": 100,
    # These are the point-in-time fields produced by the future TeaJoin
    # fundamental/holder join.  Missing fields intentionally fail closed.
    "data_requirements": {
        "market": ["daily", "adj_factor", "stk_limit", "daily_basic"],
        "fundamental": ["qingshu_roe_complete_years", "qingshu_roe_min_pct"],
        "holder": ["qingshu_institution_holder_count"],
    },
    "data_policy": "missing_required_fields_fail_closed",
}

EXECUTION_BACKEND = "python_history_legacy"
LOOKBACK_DAYS = 380  # 360 日新高 + 20 日候选/放量基准
ENTRY_SIGNALS: list[str] = []
EXIT_SIGNALS: list[str] = []
STOP_LOSS = -0.08
MAX_HOLD_DAYS = 20
ALERTS: list[dict] = []

RULES = """
1. 总市值严格大于 150 亿元。
2. 连续五个完整年度 ROE ≥ 10%。
3. 非自然人股东至少 5 名。
4. 近 240 个交易日至少 6 次收盘涨停。
5. 近一年至少出现一次连续两日涨停。
6. 近 10 个交易日存在收盘涨停。
7. 近 10 个交易日无跌幅达到 5% 的阴线。
8. 近 20 个交易日出现 360 日复权新高。
9. 连续 3 日成交量达到此前 20 日均量的 2 倍。
10. 当日收盘真实涨停, 或高开 >= 3.5% 且收阳, 或振幅 > 9.8% 且收阳。

年度 ROE、公告日和机构股东快照必须由数据层先按 as-of 日 JOIN 为
qingshu_roe_complete_years, qingshu_roe_min_pct,
qingshu_institution_holder_count; 缺少任一字段时本策略不返回候选。
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
        "qingshu_roe_complete_years",
        "qingshu_roe_min_pct",
        "qingshu_institution_holder_count",
    }
    if df.is_empty() or not required <= set(df.columns):
        return _empty(df)

    roe_years = int(params.get("required_annual_roe_years", 5))
    roe_min = float(params.get("roe_min_pct", 10.0))
    holder_min = int(params.get("institution_holder_min_count", 5))
    cap_min_yi = float(params.get("market_cap_min_yi", 150.0))
    annual_limit_min = int(params.get("annual_limit_up_min_count", 6))
    volume_multiple = float(params.get("volume_multiple", 2.0))
    gap_min = float(params.get("gap_open_min_pct", 3.5)) / 100.0
    amplitude_min = float(params.get("amplitude_min_pct", 9.8)) / 100.0

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
            pl.col("_limit_up").rolling_sum(window_size=240, min_samples=240).over("symbol").alias("_limit_count_240"),
            pl.col("_limit_up").shift(1).over("symbol").alias("_prev_limit_up"),
            pl.col("_limit_up").rolling_sum(window_size=10, min_samples=10).over("symbol").alias("_limit_count_10"),
            (pl.col("volume") >= pl.col("_volume_base") * volume_multiple).cast(pl.Int8).alias("_volume_expanded"),
            ((pl.col("high") - pl.col("low")) / pl.col("_prev_close").abs()).alias("_amplitude"),
            (pl.col("open") / pl.col("_prev_close") - 1.0).alias("_gap_open"),
            (pl.col("close") / pl.col("_prev_close") - 1.0).alias("_change"),
            pl.col("high").rolling_max(window_size=360, min_samples=360).over("symbol").alias("_high_360"),
        )
        .with_columns(
            pl.col("_volume_expanded").rolling_sum(window_size=3, min_samples=3).over("symbol").alias("_expanded_3"),
            (pl.col("high") >= pl.col("_high_360")).cast(pl.Int8).alias("_new_high_hit"),
        )
        .with_columns(
            pl.col("_new_high_hit").rolling_max(window_size=20, min_samples=20).over("symbol").alias("_new_high_recent"),
            pl.col("_expanded_3").rolling_max(window_size=360, min_samples=1).over("symbol").alias("_expanded_360"),
        )
    )

    # Candidate rules: every field is checked explicitly.  Nulls are false,
    # so an incomplete row cannot pass through as a zero/default value.
    candidate = (
        (pl.col("close") * pl.col("total_shares") > cap_min_yi * 1e8)
        & (pl.col("qingshu_roe_complete_years") >= roe_years)
        & (pl.col("qingshu_roe_min_pct") >= roe_min)
        & (pl.col("qingshu_institution_holder_count") >= holder_min)
        & (pl.col("_bar_count") >= 380)
        & (pl.col("_limit_count_240") >= annual_limit_min)
        & ((pl.col("_limit_up") == 1) & (pl.col("_prev_limit_up") == 1)).rolling_max(window_size=240, min_samples=240).over("symbol").fill_null(0).cast(pl.Boolean)
        & (pl.col("_limit_count_10") >= 1)
        & ~((pl.col("close") < pl.col("open")) & (pl.col("_change") <= -0.05)).rolling_max(window_size=10, min_samples=10).over("symbol").fill_null(0).cast(pl.Boolean)
        & (pl.col("_new_high_recent") == 1).fill_null(False)
        & (pl.col("_expanded_360") >= 3).fill_null(False)
    )
    trigger = (
        (pl.col("_limit_up") == 1)
        | ((pl.col("_gap_open") >= gap_min) & (pl.col("close") > pl.col("open")))
        | ((pl.col("_amplitude") > amplitude_min) & (pl.col("close") > pl.col("open")))
    )
    return (
        work.with_columns(
            candidate.fill_null(False).alias("qingshu_candidate_qualified"),
            trigger.fill_null(False).alias("qingshu_triggered"),
        )
        .filter(candidate.fill_null(False))
        .with_columns(
            pl.when(pl.col("qingshu_triggered"))
            .then(pl.lit("triggered"))
            .otherwise(pl.lit("qualified"))
            .alias("qingshu_status")
        )
    )
