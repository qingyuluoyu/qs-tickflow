from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import polars as pl
import pytest

from app.api import data as data_api
from app.indicators import pipeline
from app.services import financial_sync
from app.share_capital import apply_historical_float_shares
from app.tickflow.capabilities import CapabilitySet


def _write_instruments(data_dir, symbols: list[str]) -> None:
    path = data_dir / "instruments" / "instruments.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"symbol": symbols}).write_parquet(path)


def _write_daily_coverage(data_dir, symbol: str, *dates: str) -> None:
    for ds in dates:
        path = data_dir / "kline_daily" / f"date={ds}" / "part.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame({
            "symbol": [symbol],
            "date": [date.fromisoformat(ds)],
        }).write_parquet(path)


def test_first_share_sync_fetches_current_snapshot_without_daily_coverage(tmp_path, monkeypatch):
    _write_instruments(tmp_path, ["600000.SH"])
    calls: list[tuple[list[str], bool]] = []

    def fake_fetch(table, symbols, capset, latest_only=True):
        assert table == "shares"
        calls.append((symbols, latest_only))
        assert latest_only is True
        return pl.DataFrame({
            "symbol": ["600000.SH"],
            "period_end": ["2024-06-30"],
            "float_shares": [12.0],
        })

    monkeypatch.setattr(financial_sync, "_fetch_table", fake_fetch)

    rows = financial_sync.sync_shares(tmp_path, CapabilitySet())

    assert rows == 1
    assert calls == [(["600000.SH"], True)]
    stored = pl.read_parquet(tmp_path / "financials" / "shares" / "part.parquet")
    assert stored["period_end"].to_list() == ["2024-06-30"]


def test_custom_share_sync_merges_metric_snapshot_without_erasing_history(tmp_path, monkeypatch):
    _write_instruments(tmp_path, ["600000.SH"])
    shares_path = tmp_path / "financials" / "shares" / "part.parquet"
    shares_path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({
        "symbol": ["600000.SH"],
        "period_end": ["2024-06-30"],
        "announce_date": ["2024-07-01"],
        "total_shares": [1_000_000.0],
        "float_shares": [800_000.0],
    }).write_parquet(shares_path)
    metrics_path = tmp_path / "financials" / "metrics" / "part.parquet"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({
        "symbol": ["600000.SH"],
        "trade_date": ["2026-08-13"],
        "total_share": [110.0],
        "float_share": [90.0],
    }).write_parquet(metrics_path)
    monkeypatch.setattr(financial_sync, "_financial_is_custom", lambda: True)
    monkeypatch.setattr(
        financial_sync,
        "_fetch_table",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected full history request")),
    )

    rows = financial_sync.sync_shares(tmp_path, CapabilitySet())

    assert rows == 2
    stored = pl.read_parquet(shares_path).sort("period_end")
    assert stored.to_dicts() == [
        {
            "symbol": "600000.SH", "period_end": "2024-06-30", "announce_date": "2024-07-01",
            "total_shares": 1_000_000.0, "float_shares": 800_000.0,
        },
        {
            "symbol": "600000.SH", "period_end": "2026-08-13", "announce_date": "2026-08-13",
            "total_shares": 1_100_000.0, "float_shares": 900_000.0,
        },
    ]


def test_financial_report_write_keeps_latest_teajoin_revision(tmp_path):
    reports = pl.DataFrame({
        "symbol": ["600000.SH", "600000.SH"],
        "ann_date": ["20260814", "20260814"],
        "f_ann_date": ["20260814", "20260814"],
        "end_date": ["20260630", "20260630"],
        "report_type": [1.0, 1.0],
        "comp_type": [1.0, 1.0],
        "end_type": [2.0, 2.0],
        "update_flag": [0.0, 1.0],
        "revenue": [100.0, 120.0],
    })

    rows = financial_sync._write_table("income", reports, tmp_path)

    assert rows == 1
    stored = pl.read_parquet(tmp_path / "financials" / "income" / "part.parquet")
    assert stored.to_dicts() == [
        {
            "symbol": "600000.SH", "ann_date": "20260814", "f_ann_date": "20260814",
            "end_date": "20260630", "report_type": 1.0, "comp_type": 1.0, "end_type": 2.0,
            "update_flag": 1.0, "revenue": 120.0,
        },
    ]


def test_instruments_sync_backfills_shares_from_financials(tmp_path, monkeypatch):
    """自定义数据源重写 instruments(股本=None)后必须立即回填, 否则回测市值过滤团灭候选。"""
    from app.services import instrument_sync

    shares_path = tmp_path / "financials" / "shares" / "part.parquet"
    shares_path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({
        "symbol": ["600000.SH"],
        "period_end": ["2024-06-30"],
        "total_shares": [1_000_000.0],
        "float_shares": [800_000.0],
    }).write_parquet(shares_path)

    monkeypatch.setattr(instrument_sync, "_fetch_instruments_via_provider", lambda: [{
        "symbol": "600000.SH", "name": "浦发银行", "code": "600000",
        "exchange": "SH", "region": None, "type": "stock",
        "listing_date": None, "total_shares": None, "float_shares": None,
        "tick_size": None, "limit_up": None, "limit_down": None,
    }])

    rows = instrument_sync.sync_instruments(tmp_path)

    assert rows == 1
    stored = pl.read_parquet(tmp_path / "instruments" / "instruments.parquet")
    assert stored["total_shares"].to_list() == [1_000_000.0]
    assert stored["float_shares"].to_list() == [800_000.0]


def test_incremental_share_sync_updates_existing_and_backfills_new_symbols(tmp_path, monkeypatch):
    _write_instruments(tmp_path, ["600000.SH", "000001.SZ"])
    path = tmp_path / "financials" / "shares" / "part.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({
        "symbol": ["600000.SH"],
        "period_end": ["2024-06-30"],
        "float_shares": [10.0],
    }).write_parquet(path)
    calls: list[tuple[list[str], bool]] = []

    def fake_fetch(table, symbols, capset, latest_only=True):
        assert table == "shares"
        calls.append((symbols, latest_only))
        if latest_only:
            return pl.DataFrame({
                "symbol": ["600000.SH", "000001.SZ"],
                "period_end": ["2024-06-30", "2024-06-30"],
                "float_shares": [11.0, 21.0],
            })
        raise AssertionError("historical share sync must use the maintenance repair path")

    monkeypatch.setattr(financial_sync, "_fetch_table", fake_fetch)

    rows = financial_sync.sync_shares(tmp_path, CapabilitySet())

    assert rows == 2
    assert calls == [(["600000.SH", "000001.SZ"], True)]
    stored = pl.read_parquet(path).sort(["symbol", "period_end"])
    assert stored.filter(pl.col("symbol") == "600000.SH")["float_shares"].to_list() == [11.0]
    assert stored.filter(pl.col("symbol") == "000001.SZ")["float_shares"].to_list() == [21.0]


def test_rebuild_share_history_batch_merges_and_resumes(tmp_path, monkeypatch):
    _write_instruments(tmp_path, ["600000.SH", "000001.SZ"])
    _write_daily_coverage(tmp_path, "600000.SH", "2024-01-01")
    shares_path = tmp_path / "financials" / "shares" / "part.parquet"
    shares_path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({
        "symbol": ["600000.SH"],
        "period_end": ["2024-06-30"],
        "announce_date": ["2024-07-01"],
        "total_shares": [100.0],
        "float_shares": [80.0],
    }).write_parquet(shares_path)
    calls: list[list[str]] = []

    def fake_fetch(table, symbols, capset, latest_only=True):
        assert table == "shares"
        assert latest_only is False
        calls.append(symbols)
        return pl.DataFrame({
            "symbol": symbols,
            "period_end": ["2023-12-31"],
            "announce_date": ["2024-01-01"],
            "total_shares": [90.0],
            "float_shares": [70.0],
        })

    monkeypatch.setattr(financial_sync, "_fetch_table", fake_fetch)

    first = financial_sync.rebuild_share_history_batch(
        tmp_path, CapabilitySet(), batch_size=1,
    )
    second = financial_sync.rebuild_share_history_batch(
        tmp_path, CapabilitySet(), batch_size=1,
    )

    assert first == {
        "processed_symbols": 1,
        "remaining_symbols": 1,
        "complete": False,
        "rows": 2,
    }
    assert second == {
        "processed_symbols": 1,
        "remaining_symbols": 0,
        "complete": True,
        "rows": 3,
    }
    assert calls == [["600000.SH"], ["000001.SZ"]]
    state = json.loads(
        (tmp_path / "financials" / "shares" / "rebuild-state.json").read_text(encoding="utf-8")
    )
    assert state == {
        "completed_symbols": ["000001.SZ", "600000.SH"],
        "complete": True,
        "coverage_start": "2024-01-01",
    }
    assert pl.read_parquet(shares_path).sort(["symbol", "period_end"]).height == 3


def test_rebuild_share_history_does_not_advance_after_empty_batch(tmp_path, monkeypatch):
    _write_instruments(tmp_path, ["600000.SH"])
    _write_daily_coverage(tmp_path, "600000.SH", "2024-01-01")
    monkeypatch.setattr(financial_sync, "_fetch_table", lambda *_args, **_kwargs: pl.DataFrame())

    with pytest.raises(RuntimeError, match="share history batch returned no rows"):
        financial_sync.rebuild_share_history_batch(tmp_path, CapabilitySet(), batch_size=1)

    assert not (tmp_path / "financials" / "shares" / "rebuild-state.json").exists()


def test_rebuild_share_history_keeps_daily_coverage_and_one_prior_record(tmp_path, monkeypatch):
    _write_instruments(tmp_path, ["600000.SH"])
    _write_daily_coverage(tmp_path, "600000.SH", "2026-08-11", "2026-08-12")
    monkeypatch.setattr(
        financial_sync,
        "_fetch_table",
        lambda *_args, **_kwargs: pl.DataFrame({
            "symbol": ["600000.SH"] * 4,
            "period_end": ["2025-01-01", "2026-08-10", "2026-08-11", "2026-08-12"],
            "announce_date": ["2025-01-01", "2026-08-10", "2026-08-11", "2026-08-12"],
            "float_shares": [10.0, 20.0, 30.0, 40.0],
        }),
    )

    result = financial_sync.rebuild_share_history_batch(
        tmp_path, CapabilitySet(), batch_size=1,
    )

    assert result["rows"] == 3
    stored = pl.read_parquet(tmp_path / "financials" / "shares" / "part.parquet")
    assert stored.sort("period_end")["period_end"].to_list() == [
        "2026-08-10", "2026-08-11", "2026-08-12",
    ]


def test_rebuild_share_history_restarts_when_daily_coverage_moves_back(tmp_path, monkeypatch):
    _write_instruments(tmp_path, ["600000.SH"])
    _write_daily_coverage(tmp_path, "600000.SH", "2026-08-10", "2026-08-11")
    state = tmp_path / "financials" / "shares" / "rebuild-state.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps({
            "completed_symbols": ["600000.SH"],
            "complete": True,
            "coverage_start": "2026-08-11",
        }),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_fetch(_table, symbols, _capset, latest_only=True):
        assert latest_only is False
        calls.append(symbols)
        return pl.DataFrame({
            "symbol": symbols,
            "period_end": ["2026-08-10"],
            "announce_date": ["2026-08-10"],
            "float_shares": [20.0],
        })

    monkeypatch.setattr(financial_sync, "_fetch_table", fake_fetch)

    result = financial_sync.rebuild_share_history_batch(
        tmp_path, CapabilitySet(), batch_size=1,
    )

    assert result["processed_symbols"] == 1
    assert calls == [["600000.SH"]]


def test_custom_financial_provider_receives_shares_contract(monkeypatch):
    received: list[tuple[str, list[str], bool]] = []

    class Provider:
        def get_financials(self, table, symbols, latest_only=True):
            received.append((table, symbols, latest_only))
            return pl.DataFrame({
                "symbol": symbols,
                "period_end": ["2024-06-30"],
                "float_shares": [10.0],
            })

    from app.data_providers import custom as custom_sources
    from app.services import preferences

    monkeypatch.setattr(financial_sync, "_financial_is_custom", lambda: True)
    monkeypatch.setattr(preferences, "get_financial_provider", lambda: "custom-test")
    monkeypatch.setattr(custom_sources, "get_provider", lambda _name: Provider())

    result = financial_sync._fetch_table(
        "shares",
        ["600000.SH"],
        CapabilitySet(),
        latest_only=False,
    )

    assert result.height == 1
    assert received == [("shares", ["600000.SH"], False)]


def test_historical_turnover_uses_only_available_share_capital(monkeypatch):
    monkeypatch.setattr(pipeline, "cn_today", lambda: date(2026, 7, 18))
    bars = pl.DataFrame({
        "symbol": ["600000.SH"] * 5,
        "date": [
            date(2024, 3, 31),
            date(2024, 4, 14),
            date(2024, 4, 15),
            date(2024, 6, 30),
            date(2026, 7, 18),
        ],
        "volume": [10_000.0] * 5,
    })
    instruments = pl.DataFrame({
        "symbol": ["600000.SH"],
        "float_shares": [200_000_000.0],
    })
    shares = pl.DataFrame({
        "symbol": ["600000.SH", "600000.SH"],
        "period_end": ["2023-12-31", "2024-06-30"],
        "announce_date": ["2024-04-15", None],
        "float_shares": [100_000_000.0, 50_000_000.0],
    })

    result = pipeline.compute_limit_signals(
        bars,
        instruments,
        needed={"turnover_rate"},
        historical_shares=shares,
    )

    assert result["turnover_rate"].to_list() == [None, None, 1.0, 2.0, 0.5]


def test_historical_share_capital_accepts_teajoin_compact_dates():
    rows = pl.DataFrame({
        "symbol": ["600000.SH", "600000.SH"],
        "date": [date(2026, 8, 12), date(2026, 8, 13)],
        "float_shares": [200.0, 200.0],
    })
    shares = pl.DataFrame({
        "symbol": ["600000.SH"],
        "period_end": ["20260812"],
        "announce_date": ["20260812"],
        "float_shares": [80.0],
    })

    result = apply_historical_float_shares(rows, shares, today=date(2026, 8, 13))

    assert result["float_shares"].to_list() == [80.0, 200.0]


def test_current_day_uses_historical_share_capital_when_instrument_is_invalid():
    rows = pl.DataFrame({
        "symbol": ["600000.SH"],
        "date": [date(2026, 8, 13)],
        "float_shares": [0.0],
    })
    shares = pl.DataFrame({
        "symbol": ["600000.SH"],
        "period_end": ["20260812"],
        "announce_date": ["20260812"],
        "float_shares": [80.0],
    })

    result = apply_historical_float_shares(rows, shares, today=date(2026, 8, 13))

    assert result["float_shares"].to_list() == [80.0]


def test_historical_turnover_without_asof_share_capital_is_null(monkeypatch):
    monkeypatch.setattr(pipeline, "cn_today", lambda: date(2026, 7, 18))
    bars = pl.DataFrame({
        "symbol": ["600000.SH"],
        "date": [date(2024, 4, 15)],
        "volume": [10_000.0],
    })
    instruments = pl.DataFrame({
        "symbol": ["600000.SH"],
        "float_shares": [200_000_000.0],
    })

    result = pipeline.compute_limit_signals(
        bars,
        instruments,
        needed={"turnover_rate"},
    )

    assert result["turnover_rate"][0] is None


def test_data_status_includes_share_history(tmp_path):
    path = tmp_path / "financials" / "shares" / "part.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({
        "symbol": ["600000.SH", "600000.SH", "000001.SZ"],
        "period_end": ["2023-12-31", "2024-06-30", "2024-06-30"],
    }).write_parquet(path)

    repo = SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))
    result = data_api._safe_aggregate_financials(repo)

    assert result is not None
    assert result["rows"] == 3
    assert result["tables"]["shares"] == {"rows": 3, "symbols": 2}
