from __future__ import annotations

from datetime import date

import polars as pl

from app.services import market_overview_builder as builder
from app.services.market_overview_preloader import DashboardSnapshot


class _FakeRepo:
    def __init__(self, data_dir):
        self.store = type("Store", (), {"data_dir": data_dir})()

    def execute_all(self, *_args, **_kwargs):
        return []

    def get_instruments_asset(self, _asset_type):
        return pl.DataFrame([
            {"symbol": "000001.SZ", "name": "平安银行"},
        ])

    def get_historical_shares(self):
        return pl.DataFrame()


class _FakeScreener:
    def __init__(self, _repo):
        pass

    def latest_date(self):
        return date(2026, 8, 13)

    def _load_enriched_for_date(self, _as_of):
        return pl.DataFrame(
            [
                {
                    "symbol": "000001.SZ",
                    "name": "平安银行",
                    "close": 11.25,
                    "change_pct": 0.0,
                    "amount": 848358.7,
                    "turnover_rate": 1.0,
                    "volume": 755980.0,
                    "ma5": 10.0,
                    "ma20": 10.0,
                    "ma60": 10.0,
                }
            ]
        )


class _FakeQuote:
    def status(self):
        return {
            "enabled": False,
            "running": False,
            "realtime_provider": "teajoin",
            "last_fetch_status": "empty",
            "last_fetch_rows": 0,
        }

    def get_index_quotes(self, _symbols):
        return pl.DataFrame()


class _LiveTeaJoinProvider:
    def get_latest_daily_snapshot(self):
        return pl.DataFrame([
            {
                "symbol": "000001.SZ",
                "date": date(2026, 8, 14),
                "close": 12.1,
                "high": 12.1,
                "low": 11.0,
                "prev_close": 11.0,
                "change_pct": 1.1 / 11,
                "change_amount": 1.1,
                "amount": 3000.0,
                "volume": 120.0,
            }
        ])

    def get_daily(self, symbols, start_time, end_time, asset_type="stock"):
        assert asset_type == "index"
        assert symbols == list(builder.CORE_INDEX_SYMBOLS)
        return pl.DataFrame([
            {"symbol": "000001.SH", "date": date(2026, 8, 13), "close": 13.0},
            {"symbol": "000001.SH", "date": date(2026, 8, 12), "close": 12.0},
        ])


def test_dashboard_prefers_latest_teajoin_daily_snapshot_over_local_enriched(monkeypatch, tmp_path):
    monkeypatch.setattr(builder, "ScreenerService", _FakeScreener)
    monkeypatch.setattr(builder, "cn_today", lambda: date(2026, 8, 17))
    monkeypatch.setattr(
        "app.services.preferences.get_daily_data_provider",
        lambda: "teajoin",
    )
    monkeypatch.setattr(
        "app.services.preferences.get_realtime_data_provider",
        lambda: "teajoin",
    )
    monkeypatch.setattr(
        "app.data_providers.custom.provider_has_dataset",
        lambda name, dataset: name == "teajoin" and dataset == "daily",
    )
    monkeypatch.setattr(
        "app.data_providers.custom.get_provider",
        lambda _name: _LiveTeaJoinProvider(),
    )

    result = builder.build_market_overview(
        _FakeRepo(tmp_path),
        quote_service=_FakeQuote(),
        dashboard_live=True,
    )

    assert result["as_of"] == "2026-08-14"
    assert result["breadth"]["total"] == 1
    assert result["top_gainers"][0]["close"] == 12.1
    assert result["data_freshness"]["snapshot_date"] == "2026-08-14"
    assert result["data_freshness"]["snapshot_kind"] == "teajoin.daily"
    assert result["data_freshness"]["is_stale"] is True
    assert result["trend"]["above_ma5"] == 1
    assert result["activity"]["avg_turnover"] == 1.0
    assert result["indices"][0]["last_price"] == 13.0
    assert result["indices"][0]["change_pct"] == 8.333333333333332
    assert result["limit"]["limit_up"] == 1


def test_dashboard_uses_warmed_realtime_snapshot_without_provider_call(monkeypatch, tmp_path):
    monkeypatch.setattr(builder, "ScreenerService", _FakeScreener)
    monkeypatch.setattr(
        "app.services.preferences.get_daily_data_provider",
        lambda: "teajoin",
    )
    snapshot = DashboardSnapshot(
        provider="teajoin",
        kind="teajoin.realtime",
        status="success",
        snapshot_date=date(2026, 8, 17),
        frame=pl.DataFrame([{
            "symbol": "000001.SZ",
            "date": date(2026, 8, 17),
            "close": 13.2,
            "prev_close": 11.0,
            "change_pct": 0.2,
            "change_amount": 2.2,
            "volume": 100.0,
            "amount": 3000.0,
        }]),
        fetched_at_ms=1.0,
        error=None,
    )

    def fail_if_provider_called(*_args, **_kwargs):
        raise AssertionError("warmed dashboard snapshot must avoid provider I/O")

    monkeypatch.setattr("app.data_providers.custom.get_provider", fail_if_provider_called)
    result = builder.build_market_overview(
        _FakeRepo(tmp_path),
        quote_service=_FakeQuote(),
        dashboard_live=True,
        dashboard_snapshot=snapshot,
    )

    assert result["as_of"] == "2026-08-17"
    assert result["top_gainers"][0]["close"] == 13.2
    assert result["data_freshness"]["snapshot_kind"] == "teajoin.realtime"
    assert result["data_freshness"]["is_stale"] is False


def test_dashboard_index_snapshot_converts_provider_decimal_change_pct():
    rows = builder._index_quotes(
        _FakeRepo("."),
        quote_service=None,
        dashboard_snapshot=pl.DataFrame([{
            "symbol": "000001.SH",
            "date": date(2026, 8, 17),
            "close": 101.0,
            "prev_close": 100.0,
            "change_pct": 0.01,
        }]),
    )

    assert rows[0]["change_pct"] == 1.0


def test_dashboard_derives_turnover_and_extends_live_limit_ladder(monkeypatch, tmp_path):
    class _MetricsScreener:
        def __init__(self, _repo):
            pass

        def latest_date(self):
            return date(2026, 8, 13)

        def _load_enriched_for_date(self, _as_of):
            # The existing local partition predates the turnover/limit signal
            # columns.  It still contains the same-date float share base used
            # by the canonical turnover formula.
            return pl.DataFrame([{
                "symbol": "000001.SZ",
                "name": "平安银行",
                "float_shares": 1_000_000.0,
                "ma5": 10.0,
                "ma20": 10.0,
                "ma60": 10.0,
            }])

        def load_prior_consecutive(self, _as_of, column):
            assert column == "consecutive_limit_ups"
            return pl.DataFrame([{"symbol": "000001.SZ", "prev_consec": 2}])

    snapshot = DashboardSnapshot(
        provider="teajoin",
        kind="teajoin.daily",
        status="success",
        snapshot_date=date(2026, 8, 14),
        frame=pl.DataFrame([{
            "symbol": "000001.SZ",
            "date": date(2026, 8, 14),
            "name": "平安银行",
            "close": 12.1,
            "prev_close": 11.0,
            "change_pct": 0.1,
            "amount": 3000.0,
            "volume": 100.0,
        }]),
        fetched_at_ms=1.0,
        error=None,
    )

    monkeypatch.setattr(builder, "ScreenerService", _MetricsScreener)
    monkeypatch.setattr(
        builder,
        "_derive_dashboard_limit_indicators",
        lambda frame, _repo: frame.with_columns([
            pl.lit(True).alias("signal_limit_up"),
            pl.lit(False).alias("signal_broken_limit_up"),
            pl.lit(False).alias("signal_limit_down"),
            pl.lit(1).cast(pl.UInt32).alias("consecutive_limit_ups"),
        ]),
    )
    monkeypatch.setattr(builder, "cn_today", lambda: date(2026, 8, 17))
    monkeypatch.setattr(
        "app.services.preferences.get_daily_data_provider",
        lambda: "teajoin",
    )

    result = builder.build_market_overview(
        _FakeRepo(tmp_path),
        quote_service=_FakeQuote(),
        dashboard_live=True,
        dashboard_snapshot=snapshot,
    )

    # 100 lots / 1,000,000 shares = 1% (the internal enriched unit).
    assert result["activity"]["avg_turnover"] == 1.0
    assert result["active_leaders"][0]["turnover_rate"] == 1.0
    # The provider only contains today's signal; the persisted prior run makes
    # this a three-board stock, matching the limit-ladder API contract.
    assert result["limit"]["max_boards"] == 3
    assert result["limit"]["tiers"] == [{
        "boards": 3,
        "count": 1,
        "stocks": [{"symbol": "000001.SZ", "name": "平安银行", "amount": 3000.0}],
    }]


def test_dashboard_rejects_provider_snapshot_from_the_future(monkeypatch, tmp_path):
    class _FutureProvider:
        def get_latest_daily_snapshot(self):
            return pl.DataFrame([
                {"symbol": "000001.SZ", "date": date(2026, 8, 15), "close": 99.0}
            ])

    monkeypatch.setattr(builder, "ScreenerService", _FakeScreener)
    monkeypatch.setattr(builder, "cn_today", lambda: date(2026, 8, 14))
    monkeypatch.setattr(
        "app.services.preferences.get_daily_data_provider",
        lambda: "teajoin",
    )
    monkeypatch.setattr(
        "app.data_providers.custom.provider_has_dataset",
        lambda name, dataset: name == "teajoin" and dataset == "daily",
    )
    monkeypatch.setattr(
        "app.data_providers.custom.get_provider",
        lambda _name: _FutureProvider(),
    )

    result = builder.build_market_overview(
        _FakeRepo(tmp_path),
        quote_service=_FakeQuote(),
        dashboard_live=True,
    )

    assert result["as_of"] == "2026-08-13"
    assert result["data_freshness"]["snapshot_kind"] == "persisted.enriched"


def test_overview_reports_teajoin_snapshot_freshness(monkeypatch, tmp_path):
    monkeypatch.setattr(builder, "ScreenerService", _FakeScreener)
    monkeypatch.setattr(
        "app.services.preferences.get_daily_data_provider",
        lambda: "teajoin",
    )
    monkeypatch.setattr(
        "app.services.preferences.get_realtime_data_provider",
        lambda: "teajoin",
    )

    result = builder.build_market_overview(
        _FakeRepo(tmp_path),
        quote_service=_FakeQuote(),
    )

    freshness = result["data_freshness"]
    assert freshness["source"] == "teajoin"
    assert freshness["snapshot_date"] == "2026-08-13"
    assert freshness["is_stale"] is True
    assert freshness["realtime_provider"] == "teajoin"
    assert freshness["realtime_status"] == "empty"
    assert freshness["snapshot_kind"] == "persisted.enriched"
    assert freshness["snapshot_rows"] is None


def test_weekend_uses_last_weekday_snapshot_without_false_stale_flag(monkeypatch):
    monkeypatch.setattr(builder, "cn_today", lambda: date(2026, 8, 16))

    freshness = builder._data_freshness(
        date(2026, 8, 14),
        explicit_as_of=False,
        quote_status={
            "realtime_provider": "teajoin",
            "last_fetch_status": "empty",
            "last_fetch_rows": 0,
        },
    )

    assert freshness["is_stale"] is False


def test_provider_snapshot_confirms_weekday_exchange_holiday(monkeypatch):
    # 2026-08-17 is treated as a weekday by the generic fallback. A provider
    # snapshot is the exchange-calendar authority when the market is closed.
    monkeypatch.setattr(builder, "cn_today", lambda: date(2026, 8, 17))

    freshness = builder._data_freshness(
        date(2026, 8, 14),
        explicit_as_of=False,
        provider_confirmed=True,
        quote_status={
            "realtime_provider": "teajoin",
            "last_fetch_status": "empty",
            "last_fetch_rows": 0,
        },
    )

    assert freshness["is_stale"] is False
    assert freshness["calendar_basis"] == "provider_snapshot"


def test_explicit_historical_overview_date_is_not_marked_as_current_stale(monkeypatch, tmp_path):
    monkeypatch.setattr(builder, "ScreenerService", _FakeScreener)
    monkeypatch.setattr(
        "app.services.preferences.get_daily_data_provider",
        lambda: "teajoin",
    )
    monkeypatch.setattr(
        "app.services.preferences.get_realtime_data_provider",
        lambda: "teajoin",
    )

    result = builder.build_market_overview(
        _FakeRepo(tmp_path),
        quote_service=_FakeQuote(),
        as_of=date(2026, 8, 12),
    )

    assert result["data_freshness"]["is_stale"] is False
