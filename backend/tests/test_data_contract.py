from __future__ import annotations

from datetime import date

import polars as pl

from app.data_providers.normalizer import normalize_daily, validate_daily_frame
from app.services import sina_snapshot
from app.tickflow.repository import DataStore, KlineRepository


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


def test_normalize_daily_records_authoritative_provider_provenance():
    frame = normalize_daily(
        pl.DataFrame({
            "symbol": ["000001.SZ"],
            "date": [date(2026, 9, 15)],
            "open": [10.0],
            "high": [10.5],
            "low": [9.8],
            "close": [10.2],
            "volume": [100.0],
            "amount": [100_000.0],
        }),
        source="teajoin",
    )

    assert frame.select("data_source", "is_provisional").row(0) == ("teajoin", False)


def test_sina_daily_snapshot_is_explicitly_provisional(monkeypatch):
    monkeypatch.setattr(
        sina_snapshot,
        "_fetch_spot",
        lambda *_args, **_kwargs: pl.DataFrame({
            "symbol": ["000001.SZ"],
            "date": ["2026-09-15"],
            "open": [10.0],
            "high": [10.5],
            "low": [9.8],
            "close": [10.2],
            "volume": [100.0],
            "amount": [100_000.0],
        }),
    )

    frame = sina_snapshot.fetch_spot_daily(["000001.SZ"])

    assert frame.select("data_source", "is_provisional").row(0) == ("sina", True)


def test_authoritative_daily_upsert_replaces_provisional_provenance(tmp_path):
    repo = KlineRepository(DataStore(tmp_path))
    trade_date = date(2026, 9, 15)
    base = {
        "symbol": ["000001.SZ"],
        "date": [trade_date],
        "open": [10.0],
        "high": [10.5],
        "low": [9.8],
        "volume": [100.0],
        "amount": [100_000.0],
    }
    repo.append_daily(pl.DataFrame({
        **base,
        "close": [10.1],
        "data_source": ["sina"],
        "is_provisional": [True],
    }))
    repo.append_daily(pl.DataFrame({
        **base,
        "close": [10.2],
        "data_source": ["teajoin"],
        "is_provisional": [False],
    }))

    stored = pl.read_parquet(
        tmp_path / "kline_daily" / f"date={trade_date.isoformat()}" / "part.parquet",
    )

    assert stored.select("close", "data_source", "is_provisional").row(0) == (
        10.2, "teajoin", False,
    )
