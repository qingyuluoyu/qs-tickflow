"""指数日 K 新鲜度回归测试。"""
from __future__ import annotations

from datetime import date, datetime

import polars as pl

from app.jobs import daily_pipeline
from app.tickflow.repository import DataStore, KlineRepository


def _index_row(trade_date: date, close: float) -> dict:
    return {
        "symbol": "000001.SH",
        "date": trade_date,
        "open": close - 1,
        "high": close + 1,
        "low": close - 2,
        "close": close,
        "volume": 1000.0,
        "amount": 100000.0,
    }


def test_index_daily_uses_newer_raw_partition_when_enriched_lags(tmp_path):
    repo = KlineRepository(DataStore(tmp_path))
    enriched = tmp_path / "kline_index_enriched" / "date=2026-08-14"
    raw = tmp_path / "kline_index_daily" / "date=2026-08-17"
    enriched.mkdir(parents=True)
    raw.mkdir(parents=True)
    pl.DataFrame([_index_row(date(2026, 8, 14), 3000.0)]).write_parquet(enriched / "part.parquet")
    pl.DataFrame([_index_row(date(2026, 8, 17), 3010.0)]).write_parquet(raw / "part.parquet")

    rows = repo.get_index_daily(
        "000001.SH",
        date(2026, 8, 1),
        date(2026, 8, 17),
    )

    assert rows["date"].to_list()[-1] == date(2026, 8, 17)
    assert rows["close"].to_list()[-1] == 3010.0


def test_pipeline_snapshot_readiness_requires_index_daily_when_enabled():
    target = date(2026, 8, 17)

    class Repo:
        def latest_daily_date(self):
            return target

        def latest_daily_dates_asset(self, asset_type, symbols):
            assert asset_type == "index"
            assert symbols == [
                "000001.SH",
                "399001.SZ",
                "399006.SZ",
                "000680.SH",
            ]
            return {symbol: date(2026, 7, 31) for symbol in symbols}

        def latest_enriched_date(self, asset_type="stock"):
            return target if asset_type == "stock" else date(2026, 7, 31)

    repo = Repo()
    assert not daily_pipeline._is_pipeline_snapshot_ready(repo, target, pull_index=True)
    assert daily_pipeline._is_pipeline_snapshot_ready(repo, target, pull_index=False)


def test_index_snapshot_gap_fill_does_not_require_batch_capability(tmp_path, monkeypatch):
    repo = KlineRepository(DataStore(tmp_path))
    raw = tmp_path / "kline_index_daily" / "date=2026-08-17"
    raw.mkdir(parents=True)
    pl.DataFrame([_index_row(date(2026, 8, 17), 3010.0)]).write_parquet(raw / "part.parquet")
    monkeypatch.setattr(daily_pipeline, "_invalidate", lambda *_args: None)
    monkeypatch.setattr(
        repo,
        "get_index_instruments",
        lambda: pl.DataFrame({"symbol": ["000001.SH"]}),
    )
    monkeypatch.setattr(repo, "refresh_index_views", lambda: None)
    written: list[pl.DataFrame] = []
    monkeypatch.setattr(repo, "flush_live_daily_asset", lambda _asset, frame: written.append(frame))

    from app.services import sina_snapshot

    monkeypatch.setattr(
        sina_snapshot,
        "fetch_spot_daily",
        lambda symbols, asset_type="stock": pl.DataFrame([
            {**_index_row(date(2026, 8, 18), 3020.0), "date": "2026-08-18"},
        ]),
    )

    count = daily_pipeline._gap_fill_index_snapshot(
        repo,
        date(2026, 8, 18),
        datetime(2026, 8, 18, 15, 30, tzinfo=daily_pipeline.BEIJING_TZ),
        pull_index=True,
        emit=lambda *_args, **_kwargs: None,
        stage_errors=[],
    )

    assert count == 1
    assert len(written) == 1
    assert written[0].get_column("date").to_list() == [date(2026, 8, 18)]
