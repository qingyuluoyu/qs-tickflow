"""历史股本解析。"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl


def load_share_history(data_dir: Path) -> pl.DataFrame:
    """读取本地财务股本表；未同步或损坏时返回空表。"""
    path = data_dir / "financials" / "shares" / "part.parquet"
    if not path.exists():
        return pl.DataFrame()
    try:
        shares = pl.read_parquet(path)
        if not {"symbol", "period_end", "float_shares"} <= set(shares.columns):
            return pl.DataFrame()
        return shares
    except Exception:
        return pl.DataFrame()


def apply_historical_float_shares(
    rows: pl.DataFrame,
    shares: pl.DataFrame | None,
    *,
    today: date,
) -> pl.DataFrame:
    """Resolve usable float shares without leaking current capital into history.

    The current day may use the instrument snapshot. Earlier bars use only a
    share record announced on or before their trade date; unavailable history
    stays null so turnover cannot look valid when it is not.
    """
    required = {"symbol", "date", "float_shares"}
    if rows.is_empty() or not required <= set(rows.columns):
        return rows

    def current_day_only(frame: pl.DataFrame) -> pl.DataFrame:
        return frame.with_columns(
            pl.when(pl.col("date").cast(pl.Date, strict=False) == pl.lit(today))
            .then(pl.col("float_shares"))
            .otherwise(pl.lit(None).cast(pl.Float64))
            .alias("float_shares")
        )

    if (
        shares is None
        or shares.is_empty()
        or not {"symbol", "period_end", "float_shares"} <= set(shares.columns)
    ):
        return current_day_only(rows)

    def as_date_expr(column: str) -> pl.Expr:
        dtype = shares.schema[column]
        if dtype == pl.Utf8:
            value = pl.col(column).str.strip_chars()
            return (
                value.str.strptime(pl.Date, format="%Y-%m-%d", strict=False)
                .fill_null(value.str.strptime(pl.Date, format="%Y%m%d", strict=False))
            )
        return pl.col(column).cast(pl.Date, strict=False)

    available_date = as_date_expr("period_end")
    if "announce_date" in shares.columns:
        available_date = as_date_expr("announce_date").fill_null(available_date)

    history = (
        shares
        .select(
            pl.col("symbol").cast(pl.Utf8),
            available_date.alias("_share_available_date"),
            pl.col("period_end").cast(pl.Utf8).alias("_share_period_end"),
            pl.col("float_shares").cast(pl.Float64, strict=False).alias("_historical_float_shares"),
        )
        .filter(
            pl.col("symbol").is_not_null()
            & pl.col("_share_available_date").is_not_null()
            & (pl.col("_historical_float_shares") > 0)
        )
        .sort(["symbol", "_share_available_date", "_share_period_end"])
        .unique(subset=["symbol", "_share_available_date"], keep="last")
        .sort(["symbol", "_share_available_date"])
    )
    if history.is_empty():
        return current_day_only(rows)

    resolved = (
        rows
        .with_row_index("_share_row_order")
        .with_columns(
            pl.col("symbol").cast(pl.Utf8),
            pl.col("date").cast(pl.Date, strict=False).alias("_share_trade_date"),
        )
        .sort(["symbol", "_share_trade_date"])
        .join_asof(
            history,
            left_on="_share_trade_date",
            right_on="_share_available_date",
            by="symbol",
            strategy="backward",
            check_sortedness=False,
        )
        .with_columns(
            pl.when(
                pl.col("_share_trade_date") == pl.lit(today)
            )
            .then(
                pl.when(pl.col("float_shares") > 0)
                .then(pl.col("float_shares"))
                .otherwise(pl.col("_historical_float_shares"))
            )
            .otherwise(
                pl.col("_historical_float_shares")
            )
            .alias("float_shares")
        )
        .sort("_share_row_order")
    )
    return resolved.drop(
        "_share_row_order",
        "_share_trade_date",
        "_share_available_date",
        "_share_period_end",
        "_historical_float_shares",
    )
