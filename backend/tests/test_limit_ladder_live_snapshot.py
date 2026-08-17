from datetime import date
from types import SimpleNamespace

import polars as pl
from starlette.requests import Request

from app.api import screener as screener_api
from app.services import market_overview_builder as overview_builder


def _request(repo):
    app = SimpleNamespace(
        state=SimpleNamespace(
            repo=repo,
            depth_service=SimpleNamespace(
                get_sealed_map=lambda _as_of, is_down=False: {},
                is_sealed_ready=lambda _as_of: False,
                get_sealed_age=lambda _as_of: None,
            ),
        )
    )
    return Request({"type": "http", "app": app})


def test_limit_ladder_uses_latest_teajoin_snapshot_for_current_date(monkeypatch):
    live_date = date(2026, 8, 14)
    live_snapshot = pl.DataFrame([{
        "symbol": "000001.SZ",
        "name": "平安银行",
        "date": live_date,
        "open": 12.1,
        "high": 12.1,
        "low": 12.1,
        "close": 12.1,
        "prev_close": 11.0,
        "change_pct": 0.1,
        "volume": 100.0,
        "amount": 1210.0,
    }])

    class Repo:
        def get_instruments_asset(self, _asset_type):
            return pl.DataFrame([{"symbol": "000001.SZ", "name": "平安银行"}])

        def get_historical_shares(self):
            return pl.DataFrame()

    class Service:
        def __init__(self, _repo):
            pass

        def latest_date(self):
            return date(2026, 8, 13)

        def _load_enriched_for_date(self, _as_of):
            return pl.DataFrame()

        def load_prior_consecutive(self, _as_of, _column):
            return pl.DataFrame({"symbol": ["000001.SZ"], "prev_consec": [2]})

    monkeypatch.setattr(screener_api, "ScreenerService", Service)
    monkeypatch.setattr(
        overview_builder,
        "_dashboard_daily_snapshot",
        lambda _repo: (live_date, live_snapshot),
    )
    monkeypatch.setattr(
        overview_builder,
        "_derive_dashboard_limit_indicators",
        lambda snapshot, _repo: snapshot.with_columns(
            pl.lit(True).alias("signal_limit_up"),
            pl.lit(False).alias("signal_broken_limit_up"),
            pl.lit(1).alias("consecutive_limit_ups"),
        ),
    )

    result = screener_api.limit_ladder(
        _request(Repo()),
        as_of=None,
        direction="up",
        ext_columns=None,
    )

    stock = result["tiers"][0]["stocks"][0]
    assert result["as_of"] == "2026-08-14"
    assert stock["symbol"] == "000001.SZ"
    assert stock["close"] == 12.1
    assert stock["boards"] == 3
    assert stock["status"] == "limit_up"
    assert stock["consecutive_limit_ups"] == 3
