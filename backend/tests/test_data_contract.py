from __future__ import annotations

from datetime import date

import polars as pl

from app.data_providers.normalizer import validate_daily_frame


def test_validate_daily_frame_rejects_invalid_ohlc_and_negative_amount():
    frame = pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "date": [date(2026, 8, 24)],
            "open": [10.0],
            "high": [9.0],
            "low": [8.0],
            "close": [10.0],
            "volume": [100.0],
            "amount": [-1.0],
        }
    )

    assert validate_daily_frame(frame) == ["invalid_ohlc"]


def test_validate_daily_frame_accepts_canonical_yuan_and_lots_units():
    frame = pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "date": [date(2026, 8, 24)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [100.0],
            "amount": [100_000.0],
        }
    )

    assert validate_daily_frame(frame) == []


def test_validate_daily_frame_rejects_null_symbol_and_date():
    frame = pl.DataFrame(
        {
            "symbol": [None],
            "date": [None],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [100.0],
            "amount": [100_000.0],
        }
    )

    assert validate_daily_frame(frame) == ["null_fields"]
