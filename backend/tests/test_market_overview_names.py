from datetime import date

import polars as pl

from app.services import market_overview_builder as builder


class _Repo:
    def get_instruments(self):
        return pl.DataFrame([{"symbol": "000001.SZ", "name": "平安银行"}])


class _Provider:
    def get_latest_daily_snapshot(self):
        return pl.DataFrame([
            {
                "symbol": "000001.SZ",
                "date": date(2026, 8, 14),
                "name": None,
                "close": 12.1,
                "change_pct": 0.1,
            },
        ])


def test_dashboard_snapshot_fills_missing_stock_names(monkeypatch):
    monkeypatch.setattr(
        "app.services.preferences.get_daily_data_provider",
        lambda: "teajoin",
    )
    monkeypatch.setattr(
        "app.data_providers.custom.provider_has_dataset",
        lambda _name, dataset: dataset == "daily",
    )
    monkeypatch.setattr(
        "app.data_providers.custom.get_provider",
        lambda _name: _Provider(),
    )

    _date, snapshot = builder._dashboard_daily_snapshot(_Repo())

    assert snapshot is not None
    assert snapshot.get_column("name").to_list() == ["平安银行"]


def test_live_snapshot_uses_same_date_enriched_name_when_provider_name_is_null():
    snapshot = pl.DataFrame([
        {"symbol": "000001.SZ", "name": None, "close": 12.1},
    ])
    enriched = pl.DataFrame([
        {"symbol": "000001.SZ", "name": "平安银行", "date": date(2026, 8, 14)},
    ])

    result = builder._merge_live_snapshot_indicators(
        snapshot,
        enriched,
        date(2026, 8, 14),
    )

    assert result.get_column("name").to_list() == ["平安银行"]


def test_live_snapshot_replaces_symbol_echo_with_instrument_name():
    snapshot = pl.DataFrame([
        {"symbol": "000001.SZ", "name": "000001.SZ", "close": 12.1},
    ])

    result = builder._fill_live_snapshot_names(snapshot, _Repo())

    assert result.get_column("name").to_list() == ["平安银行"]


def test_ranking_rows_fill_missing_names_from_instrument_map():
    rows = [
        {"symbol": "300069.SZ", "name": None, "change_pct": 0.2},
        {"symbol": "603986.SH", "name": "603986.SH", "amount": 99.3},
    ]

    class _NameMapRepo:
        def get_name_map(self, symbols):
            assert symbols == ["300069.SZ", "603986.SH"]
            return {"300069.SZ": "金利华电", "603986.SH": "兆易创新"}

    result = builder._fill_ranking_names(rows, _NameMapRepo())

    assert [row["name"] for row in result] == ["金利华电", "兆易创新"]
