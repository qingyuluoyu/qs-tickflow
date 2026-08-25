"""Normalize provider responses into internal Polars schemas."""
from __future__ import annotations

import polars as pl

from app.indicators.pipeline import filter_halt_days

DAILY_COLS = ["symbol", "date", "open", "high", "low", "close", "volume", "amount", "quote_ts"]
ADJ_FACTOR_COLS = ["symbol", "trade_date", "ex_factor"]
INSTRUMENT_COLS = ["symbol", "name", "code", "exchange", "asset_type", "source"]


def validate_daily_frame(
    frame: pl.DataFrame,
    *,
    expected_date=None,
) -> list[str]:
    """Validate the canonical daily OHLCV contract before calculations.

    Values are already converted by the provider boundary: prices are yuan,
    volume is lots and amount is yuan.  This function deliberately validates
    shape/ranges instead of guessing units from magnitude.
    """
    if frame is None or frame.is_empty():
        return ["empty"]
    required = {"symbol", "date", "open", "high", "low", "close", "volume", "amount"}
    missing = sorted(required - set(frame.columns))
    if missing:
        return ["missing_fields"]
    working = frame
    if working.schema.get("date") != pl.Date:
        working = working.with_columns(pl.col("date").cast(pl.Date, strict=False).alias("date"))
    numeric = ["open", "high", "low", "close", "volume", "amount"]
    working = working.with_columns(
        [pl.col(column).cast(pl.Float64, strict=False).alias(column) for column in numeric]
    )
    if any(working.get_column(column).null_count() for column in required):
        return ["null_fields"]
    if expected_date is not None and working.filter(pl.col("date") != pl.lit(expected_date).cast(pl.Date)).height:
        return ["mixed_dates"]
    if working.height != working.select(["symbol", "date"]).unique().height:
        return ["duplicate_rows"]
    invalid = working.filter(
        (pl.col("open") < 0)
        | (pl.col("high") < 0)
        | (pl.col("low") < 0)
        | (pl.col("close") < 0)
        | (pl.col("high") < pl.max_horizontal("open", "close", "low"))
        | (pl.col("low") > pl.min_horizontal("open", "close", "high"))
        | (pl.col("volume") < 0)
        | (pl.col("amount") < 0)
    )
    return ["invalid_ohlc"] if not invalid.is_empty() else []


def to_polars(data) -> pl.DataFrame:
    if data is None:
        return pl.DataFrame()
    if isinstance(data, pl.DataFrame):
        return data
    if isinstance(data, dict):
        rows: list[dict] = []
        for sym, values in data.items():
            for item in values or []:
                row = dict(item or {})
                row.setdefault("symbol", sym)
                rows.append(row)
        return pl.DataFrame(rows) if rows else pl.DataFrame()
    if hasattr(data, "reset_index"):
        return pl.from_pandas(data.reset_index())
    try:
        return pl.DataFrame(data)
    except Exception:  # noqa: BLE001
        return pl.DataFrame()


def normalize_daily(data, default_symbol: str | None = None, source: str = "tickflow") -> pl.DataFrame:  # noqa: ARG001
    df = to_polars(data)
    if df.is_empty():
        return df
    rename_map = {
        "ts_code": "symbol",
        "trade_date": "date",
        "datetime": "date",
        "vol": "volume",
        "amt": "amount",
        "timestamp": "quote_ts",
    }
    df = df.rename({k: v for k, v in rename_map.items() if k in df.columns})
    if "symbol" not in df.columns and default_symbol:
        df = df.with_columns(pl.lit(default_symbol).alias("symbol"))
    if "date" in df.columns and df.schema["date"] != pl.Date:
        df = df.with_columns(pl.col("date").cast(pl.Date, strict=False))
    # quote_ts: 毫秒级行情时间戳, 用于盘后校验/量比折算。保留为 Int64, 缺失则置 null。
    if "quote_ts" in df.columns:
        df = df.with_columns(pl.col("quote_ts").cast(pl.Int64, strict=False))
    for col in ("open", "high", "low", "close", "volume", "amount"):
        if col in df.columns:
            df = df.with_columns(pl.col(col).cast(pl.Float64, strict=False))
    df = filter_halt_days(df)
    keep = [c for c in DAILY_COLS if c in df.columns]
    return df.select(keep) if keep else pl.DataFrame()


def normalize_adj_factors(data, source: str = "tickflow") -> pl.DataFrame:  # noqa: ARG001
    df = to_polars(data)
    if df.is_empty():
        return df
    rename_map = {
        "timestamp": "trade_date",
        "date": "trade_date",
        "adj_factor": "ex_factor",
    }
    df = df.rename({k: v for k, v in rename_map.items() if k in df.columns})
    if "trade_date" in df.columns:
        if df.schema["trade_date"] in {pl.Int64, pl.Int32, pl.UInt64, pl.UInt32, pl.Float64, pl.Float32}:
            df = df.with_columns(
                pl.from_epoch(pl.col("trade_date").cast(pl.Int64), time_unit="ms").dt.date().alias("trade_date")
            )
        else:
            df = df.with_columns(pl.col("trade_date").cast(pl.Date, strict=False))
    if "ex_factor" in df.columns:
        df = df.with_columns(pl.col("ex_factor").cast(pl.Float64, strict=False))
    keep = [c for c in ADJ_FACTOR_COLS if c in df.columns]
    return df.select(keep).drop_nulls() if len(keep) == len(ADJ_FACTOR_COLS) else pl.DataFrame()


def normalize_instruments(rows: list[dict], asset_type: str, source: str = "tickflow") -> pl.DataFrame:
    if not rows:
        return pl.DataFrame()
    out: list[dict] = []
    for item in rows:
        symbol = item.get("symbol")
        if not symbol:
            continue
        out.append({
            "symbol": str(symbol),
            "name": item.get("name") or str(symbol),
            "code": item.get("code") or str(symbol).split(".")[0],
            "exchange": item.get("exchange"),
            "asset_type": asset_type,
            "source": source,
        })
    if not out:
        return pl.DataFrame()
    return pl.DataFrame(out).select(INSTRUMENT_COLS).unique(subset=["symbol"], keep="last").sort("symbol")
