from __future__ import annotations

from datetime import date, datetime

import polars as pl

from app.market_time import MarketAsOf, MarketSession
from app.services import market_overview_preloader as overview_preloader
from app.services.market_overview_preloader import (
    DashboardSnapshot,
    MarketOverviewPreloader,
    _normalise_realtime_frame,
    make_dashboard_failover_fetcher,
    make_dashboard_snapshot_fetcher,
    make_sina_intraday_snapshot_fetcher,
)


def _snapshot(kind: str, status: str, value: float) -> DashboardSnapshot:
    return DashboardSnapshot(
        provider="teajoin",
        kind=kind,
        status=status,
        snapshot_date=date(2026, 8, 17),
        frame=pl.DataFrame([{"symbol": "000001.SZ", "close": value}]),
        fetched_at_ms=float(value),
        error=None,
        realtime_rows=1 if kind.endswith(".realtime") else 0,
    )


def test_preloader_keeps_last_valid_snapshot_and_records_empty_refresh():
    calls = []

    def fetch():
        calls.append(len(calls))
        return (
            _snapshot("teajoin.realtime", "success", 12.3)
            if len(calls) == 1
            else DashboardSnapshot.empty("teajoin", "empty")
        )

    preloader = MarketOverviewPreloader(fetch, interval_s=30)

    first = preloader.refresh_once()
    second = preloader.refresh_once()

    assert first.status == "success"
    assert second.status == "empty"
    cached = preloader.snapshot()
    assert cached is not None
    assert cached.frame["close"].item() == 12.3
    assert cached.kind == "teajoin.realtime"
    assert cached.status == "empty"
    assert cached.fetched_at_ms == 12.3
    assert cached.realtime_rows == 0


def test_preloader_clears_realtime_rows_when_refresh_raises():
    calls = 0

    def fetch():
        nonlocal calls
        calls += 1
        if calls == 1:
            return _snapshot("teajoin.realtime", "success", 12.3)
        raise RuntimeError("provider unavailable")

    preloader = MarketOverviewPreloader(fetch, interval_s=30)

    assert preloader.refresh_once().status == "success"
    cached = preloader.refresh_once()

    assert cached is not None
    assert cached.status == "error"
    assert cached.realtime_rows == 0


def test_preloader_refresh_is_single_flight():
    calls = 0

    def fetch():
        nonlocal calls
        calls += 1
        return _snapshot("teajoin.daily", "success", 12.3)

    preloader = MarketOverviewPreloader(fetch, interval_s=30)
    assert preloader.refresh_once().status == "success"
    assert calls == 1


def test_preloader_generation_changes_only_for_material_snapshot_changes():
    value = {"close": 12.3}

    def fetch():
        return _snapshot("teajoin.daily", "success", value["close"])

    preloader = MarketOverviewPreloader(fetch, interval_s=30)
    preloader.refresh_once()
    first = preloader.status()
    preloader.refresh_once()
    unchanged = preloader.status()
    value["close"] = 12.4
    preloader.refresh_once()
    changed = preloader.status()

    assert first["snapshot_generation"] == 1
    assert unchanged["snapshot_generation"] == 1
    assert changed["snapshot_generation"] == 2
    assert changed["snapshot_date"] == "2026-08-17"


def test_dashboard_failover_uses_sina_when_custom_realtime_snapshot_is_empty(monkeypatch):
    trade_date = date(2026, 8, 19)
    monkeypatch.setattr("app.services.market_overview_preloader.cn_today", lambda: trade_date)
    primary = DashboardSnapshot(
        provider="teajoin",
        kind="teajoin.daily",
        status="empty",
        snapshot_date=date(2026, 8, 18),
        frame=pl.DataFrame([{"symbol": "000001.SZ", "close": 12.3}]),
        fetched_at_ms=1.0,
        error=None,
        realtime_rows=0,
    )
    fallback = DashboardSnapshot(
        provider="sina",
        kind="sina.realtime",
        status="success",
        snapshot_date=trade_date,
        frame=pl.DataFrame([{"symbol": "000001.SZ", "close": 12.5}]),
        fetched_at_ms=2.0,
        error=None,
        realtime_rows=1,
    )

    result = make_dashboard_failover_fetcher(lambda: primary, lambda: fallback)()

    assert result is fallback


def test_dashboard_failover_can_be_strictly_primary_source_only(monkeypatch):
    monkeypatch.setattr("app.services.market_overview_preloader.cn_today", lambda: date(2026, 8, 19))
    primary = _snapshot("teajoin.daily", "empty", 12.3)
    fallback = DashboardSnapshot(
        provider="sina",
        kind="sina.realtime",
        status="success",
        snapshot_date=date(2026, 8, 19),
        frame=pl.DataFrame([{"symbol": "000001.SZ", "close": 12.5}]),
        fetched_at_ms=2.0,
        error=None,
        realtime_rows=1,
    )

    result = make_dashboard_failover_fetcher(
        lambda: primary,
        lambda: fallback,
        allow_cross_source_fallback=False,
    )()

    assert result is primary


def test_dashboard_failover_preserves_primary_when_sina_is_not_current(monkeypatch):
    monkeypatch.setattr("app.services.market_overview_preloader.cn_today", lambda: date(2026, 8, 19))
    primary = _snapshot("teajoin.daily", "empty", 12.3)
    fallback = DashboardSnapshot.empty("sina", "empty")

    result = make_dashboard_failover_fetcher(lambda: primary, lambda: fallback)()

    assert result is primary


def test_dashboard_snapshot_fetcher_is_callable_when_provider_has_no_realtime(monkeypatch):
    monkeypatch.setattr("app.services.preferences.get_realtime_data_provider", lambda: "tickflow")
    monkeypatch.setattr("app.services.preferences.get_daily_data_provider", lambda: "tickflow")
    fetch = make_dashboard_snapshot_fetcher()

    result = fetch()

    assert result.status == "provider_unavailable"
    assert result.frame.is_empty()


def test_dashboard_realtime_rates_are_normalized_to_percent():
    frame = _normalise_realtime_frame([{
        "symbol": "000001.SZ",
        "last_price": 12.3,
        "turnover_rate": 0.0315,
    }])

    assert frame["close"].item() == 12.3
    assert frame["turnover_rate"].item() == 3.15


def test_dashboard_realtime_rows_without_close_are_rejected():
    frame = _normalise_realtime_frame([{
        "symbol": "000001.SZ",
        "last": 12.3,
        "change_pct": 0.01,
    }])

    assert frame.is_empty()


def test_dashboard_daily_quality_rejects_duplicate_or_partial_universe():
    target = date(2026, 8, 24)
    valid_row = {
        "symbol": "000001.SZ", "date": target,
        "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5,
        "volume": 100.0, "amount": 1000.0,
    }
    duplicate = pl.DataFrame([valid_row, valid_row])
    partial = pl.DataFrame([valid_row])

    assert overview_preloader._daily_snapshot_rejection(
        duplicate, target, {"000001.SZ"},
    ) == "duplicate_symbols"
    assert overview_preloader._daily_snapshot_rejection(
        partial, target, {"000001.SZ", "000002.SZ"}, min_coverage=0.9,
    ) == "partial_universe"


def test_dashboard_realtime_quality_rejects_mixed_null_dates(monkeypatch):
    target = date(2026, 8, 24)
    monkeypatch.setattr("app.services.market_overview_preloader.cn_today", lambda: target)

    frame = _normalise_realtime_frame([
        {"symbol": "000001.SZ", "date": target, "last_price": 10.0},
        {"symbol": "000002.SZ", "date": None, "last_price": 20.0},
    ])

    assert frame.is_empty()


def test_dashboard_index_quality_requires_every_core_symbol():
    target = date(2026, 8, 24)
    partial = pl.DataFrame([
        {"symbol": symbol, "date": target, "close": 100.0}
        for symbol in ("000001.SH", "399001.SZ", "399006.SZ")
    ])

    assert overview_preloader._complete_core_index_frame(partial, target).is_empty()


def test_dashboard_fetcher_caches_index_snapshot_with_stock_snapshot(monkeypatch):
    monkeypatch.setattr("app.services.preferences.get_realtime_data_provider", lambda: "tickflow")
    monkeypatch.setattr("app.services.preferences.get_daily_data_provider", lambda: "teajoin")
    monkeypatch.setattr(
        "app.data_providers.custom.provider_has_dataset",
        lambda name, dataset: name == "teajoin" and dataset == "daily",
    )

    class _Provider:
        def __init__(self):
            self.calls = []

        def get_latest_daily_snapshot(self, asset_type="stock"):
            self.calls.append(asset_type)
            symbol = "000001.SH" if asset_type == "index" else "000001.SZ"
            return pl.DataFrame([{
                "symbol": symbol,
                "date": date(2026, 8, 14),
                "close": 100.0,
                "prev_close": 99.0,
            }])

        def get_daily(self, symbols, start_time, end_time, asset_type="stock"):
            assert asset_type == "index"
            self.calls.append(asset_type)
            return pl.DataFrame([
                {"symbol": "000001.SH", "date": date(2026, 8, 14), "close": 101.0},
                {"symbol": "000001.SH", "date": date(2026, 8, 13), "close": 100.0},
            ])

    provider = _Provider()
    monkeypatch.setattr("app.data_providers.custom.get_provider", lambda _name: provider)
    monkeypatch.setattr("app.services.market_overview_preloader.cn_today", lambda: date(2026, 8, 17))

    result = make_dashboard_snapshot_fetcher(daily_refresh_s=300)()

    assert result.kind == "teajoin.daily"
    assert result.index_frame.height == 2
    assert provider.calls == ["stock", "index"]


def test_dashboard_fetcher_rechecks_daily_after_short_freshness_window(monkeypatch):
    monkeypatch.setattr("app.services.preferences.get_realtime_data_provider", lambda: "tickflow")
    monkeypatch.setattr("app.services.preferences.get_daily_data_provider", lambda: "teajoin")
    monkeypatch.setattr(
        "app.data_providers.custom.provider_has_dataset",
        lambda name, dataset: name == "teajoin" and dataset == "daily",
    )
    monkeypatch.setattr("app.services.market_overview_preloader.cn_today", lambda: date(2026, 8, 17))

    class _Provider:
        def __init__(self):
            self.calls = 0

        def get_latest_daily_snapshot(self, asset_type="stock"):
            assert asset_type == "stock"
            self.calls += 1
            snapshot_date = date(2026, 8, 14) if self.calls == 1 else date(2026, 8, 17)
            return pl.DataFrame([{
                "symbol": "000001.SZ",
                "date": snapshot_date,
                "close": float(self.calls),
            }])

        def get_daily(self, symbols, start_time, end_time, asset_type="stock"):
            if asset_type == "index":
                return pl.DataFrame([
                    {"symbol": "000001.SH", "date": date(2026, 8, 14), "close": 100.0},
                    {"symbol": "000001.SH", "date": date(2026, 8, 13), "close": 99.0},
                ])
            return pl.DataFrame()

    provider = _Provider()
    monkeypatch.setattr("app.data_providers.custom.get_provider", lambda _name: provider)
    clock = {"value": 100.0}
    monkeypatch.setattr("app.services.market_overview_preloader.time.time", lambda: clock["value"])

    fetch = make_dashboard_snapshot_fetcher()
    first = fetch()
    clock["value"] = 131.0
    second = fetch()

    assert first.snapshot_date == date(2026, 8, 14)
    assert second.snapshot_date == date(2026, 8, 17)
    assert provider.calls == 2


def test_dashboard_fetcher_passes_today_to_exact_daily_filter(monkeypatch):
    monkeypatch.setattr("app.services.preferences.get_realtime_data_provider", lambda: "tickflow")
    monkeypatch.setattr("app.services.preferences.get_daily_data_provider", lambda: "teajoin")
    monkeypatch.setattr(
        "app.data_providers.custom.provider_has_dataset",
        lambda name, dataset: name == "teajoin" and dataset == "daily",
    )
    monkeypatch.setattr("app.services.market_overview_preloader.cn_today", lambda: date(2026, 8, 17))

    class _Provider:
        def __init__(self):
            self.as_of = None

        def get_latest_daily_snapshot(self, asset_type="stock", as_of=None):
            assert asset_type == "stock"
            self.as_of = as_of
            return pl.DataFrame([{
                "symbol": "000001.SZ",
                "date": date(2026, 8, 17),
                "close": 100.0,
            }])

        def get_daily(self, symbols, start_time, end_time, asset_type="stock"):
            if asset_type == "index":
                return pl.DataFrame([
                    {"symbol": "000001.SH", "date": date(2026, 8, 17), "close": 101.0},
                    {"symbol": "000001.SH", "date": date(2026, 8, 16), "close": 100.0},
                ])
            return pl.DataFrame()

    provider = _Provider()
    monkeypatch.setattr("app.data_providers.custom.get_provider", lambda _name: provider)

    result = make_dashboard_snapshot_fetcher()()

    assert result.snapshot_date == date(2026, 8, 17)
    assert provider.as_of == datetime(2026, 8, 17)


def test_dashboard_fetcher_drops_index_rows_older_than_stock_snapshot(monkeypatch):
    """A current stock snapshot must not be paired with stale index rows."""
    trade_date = date(2026, 8, 24)
    monkeypatch.setattr("app.services.preferences.get_realtime_data_provider", lambda: "tickflow")
    monkeypatch.setattr("app.services.preferences.get_daily_data_provider", lambda: "teajoin")
    monkeypatch.setattr(
        "app.data_providers.custom.provider_has_dataset",
        lambda name, dataset: name == "teajoin" and dataset == "daily",
    )
    monkeypatch.setattr("app.services.market_overview_preloader.cn_today", lambda: trade_date)

    class _Provider:
        def get_latest_daily_snapshot(self, asset_type="stock", as_of=None):
            assert asset_type == "stock"
            assert as_of == datetime(2026, 8, 24)
            return pl.DataFrame([{
                "symbol": "000001.SZ",
                "date": trade_date,
                "close": 12.3,
            }])

        def get_daily(self, symbols, start_time, end_time, asset_type="stock"):
            assert asset_type == "index"
            return pl.DataFrame([{
                "symbol": "000001.SH",
                "date": date(2026, 8, 21),
                "close": 3905.2,
            }])

    monkeypatch.setattr("app.data_providers.custom.get_provider", lambda _name: _Provider())

    result = make_dashboard_snapshot_fetcher()()

    assert result.snapshot_date == trade_date
    assert result.frame.get_column("date").unique().to_list() == [trade_date]
    assert result.index_frame.is_empty()


def test_sina_intraday_fetcher_returns_current_day_snapshot_without_persisting(monkeypatch):
    trade_date = date(2026, 8, 18)
    monkeypatch.setattr(
        "app.services.market_overview_preloader.resolve_market_as_of",
        lambda: MarketAsOf(
            current_date=trade_date,
            daily_date=date(2026, 8, 17),
            intraday_date=trade_date,
            session=MarketSession.MORNING,
            cutoff_time="10:00:00",
            is_partial=True,
            observed_at=datetime(2026, 8, 18, 10, 0),
        ),
    )

    class _Repo:
        def get_enriched_latest(self):
            return (
                pl.DataFrame([{
                    "symbol": "000001.SZ",
                    "date": date(2026, 8, 17),
                    "raw_close": 10.0,
                }]),
                date(2026, 8, 17),
            )

        def get_instruments(self):
            return pl.DataFrame([{
                "symbol": "000001.SZ",
                "name": "测试股份",
                "float_shares": 1000000.0,
            }])

        def execute_all(self, *_args, **_kwargs):
            return [("000001.SH", 3000.0)]

    from app.services import sina_snapshot

    def fake_fetch(symbols, asset_type="stock"):
        if asset_type == "index":
            return pl.DataFrame([{
                "symbol": "000001.SH", "date": "2026-08-18", "close": 3030.0,
                "open": 3005.0, "high": 3035.0, "low": 3000.0,
                "volume": 1.0, "amount": 2.0,
            }])
        return pl.DataFrame([{
            "symbol": "000001.SZ", "date": "2026-08-18", "close": 11.0,
            "open": 10.0, "high": 11.0, "low": 10.0,
            "volume": 100.0, "amount": 1000.0,
        }])

    monkeypatch.setattr(sina_snapshot, "fetch_market_spot", fake_fetch)
    fetch = make_sina_intraday_snapshot_fetcher(
        lambda: ["000001.SZ"],
        lambda: ["000001.SH"],
        _Repo(),
    )

    result = fetch()

    assert result.kind == "sina.realtime"
    assert result.snapshot_date == trade_date
    assert result.frame["date"].item() == trade_date
    assert result.frame["change_pct"].item() == 0.1
    assert result.index_frame["prev_close"].item() == 3000.0


def test_sina_intraday_fetcher_does_not_fetch_before_open_or_after_close(monkeypatch):
    closed = MarketAsOf(
        current_date=date(2026, 8, 18),
        daily_date=date(2026, 8, 17),
        intraday_date=None,
        session=MarketSession.PREOPEN,
        cutoff_time="09:30:00",
        is_partial=False,
        observed_at=datetime(2026, 8, 18, 9, 0),
    )
    monkeypatch.setattr(
        "app.services.market_overview_preloader.resolve_market_as_of",
        lambda: closed,
    )
    fetch_calls = []
    from app.services import sina_snapshot
    monkeypatch.setattr(
        sina_snapshot,
        "fetch_market_spot",
        lambda *args, **kwargs: fetch_calls.append((args, kwargs)) or pl.DataFrame(),
    )

    result = make_sina_intraday_snapshot_fetcher(lambda: ["000001.SZ"], lambda: [], object())()

    assert result.status == "preopen"
    assert result.frame.is_empty()
    assert fetch_calls == []


def test_sina_intraday_fetcher_does_not_fetch_during_lunch(monkeypatch):
    lunch = MarketAsOf(
        current_date=date(2026, 8, 18),
        daily_date=date(2026, 8, 17),
        intraday_date=date(2026, 8, 18),
        session=MarketSession.LUNCH,
        cutoff_time="11:30:00",
        is_partial=True,
        observed_at=datetime(2026, 8, 18, 12, 0),
    )
    monkeypatch.setattr(
        "app.services.market_overview_preloader.resolve_market_as_of",
        lambda: lunch,
    )
    fetch_calls = []
    from app.services import sina_snapshot
    monkeypatch.setattr(
        sina_snapshot,
        "fetch_market_spot",
        lambda *args, **kwargs: fetch_calls.append((args, kwargs)) or pl.DataFrame(),
    )

    result = make_sina_intraday_snapshot_fetcher(lambda: ["000001.SZ"], lambda: [], object())()

    assert result.status == "lunch"
    assert result.frame.is_empty()
    assert fetch_calls == []


def _morning_asof(trade_date: date) -> MarketAsOf:
    return MarketAsOf(
        current_date=trade_date,
        daily_date=date(2026, 8, 17),
        intraday_date=trade_date,
        session=MarketSession.MORNING,
        cutoff_time="10:00:00",
        is_partial=True,
        observed_at=datetime(2026, 8, 18, 10, 0),
    )


class _SinaRepo:
    def get_enriched_latest(self):
        return (
            pl.DataFrame([{
                "symbol": "000001.SZ",
                "date": date(2026, 8, 17),
                "raw_close": 10.0,
            }]),
            date(2026, 8, 17),
        )

    def get_instruments(self):
        return pl.DataFrame([{
            "symbol": "000001.SZ",
            "name": "测试股份",
            "float_shares": 1000000.0,
        }])

    def execute_all(self, *_args, **_kwargs):
        return []


def test_sina_intraday_fetcher_filters_rows_not_from_today(monkeypatch):
    # 快照源混入非当日行(隔夜残留/缓存)时必须只保留 date == 当天的行。
    trade_date = date(2026, 8, 18)
    monkeypatch.setattr(
        "app.services.market_overview_preloader.resolve_market_as_of",
        lambda: _morning_asof(trade_date),
    )

    from app.services import sina_snapshot

    def fake_fetch(symbols, asset_type="stock"):
        return pl.DataFrame([
            {"symbol": "000001.SZ", "date": "2026-08-18", "close": 11.0,
             "open": 10.0, "high": 11.0, "low": 10.0, "volume": 100.0, "amount": 1000.0},
            {"symbol": "000002.SZ", "date": "2026-08-17", "close": 20.0,
             "open": 20.0, "high": 20.0, "low": 20.0, "volume": 50.0, "amount": 500.0},
        ])

    monkeypatch.setattr(sina_snapshot, "fetch_market_spot", fake_fetch)
    fetch = make_sina_intraday_snapshot_fetcher(
        lambda: ["000001.SZ", "000002.SZ"], lambda: [], _SinaRepo(),
    )

    result = fetch()

    assert result.status == "success"
    assert result.snapshot_date == trade_date
    assert result.frame["symbol"].to_list() == ["000001.SZ"]
    assert result.frame["date"].item() == trade_date


def test_sina_intraday_fetcher_prefers_snapshot_prev_close_and_guards_halts(monkeypatch):
    # 除权日新浪昨收是交易所调整后的基准价, 必须优先于本地未调整 raw_close;
    # 停牌行(close=0)不得派生 -100% 的假涨跌幅。
    trade_date = date(2026, 8, 18)
    monkeypatch.setattr(
        "app.services.market_overview_preloader.resolve_market_as_of",
        lambda: _morning_asof(trade_date),
    )

    from app.services import sina_snapshot

    def fake_fetch(symbols, asset_type="stock"):
        return pl.DataFrame([
            # 除权: 本地 raw_close=10.0, 新浪调整后昨收=11.0 → 涨跌幅 0
            {"symbol": "000001.SZ", "date": "2026-08-18", "close": 11.0,
             "prev_close": 11.0, "open": 11.0, "high": 11.0, "low": 11.0,
             "volume": 100.0, "amount": 1000.0, "name": "测试股份"},
            # 停牌: 全 0 行
            {"symbol": "000002.SZ", "date": "2026-08-18", "close": 0.0,
             "prev_close": 0.0, "open": 0.0, "high": 0.0, "low": 0.0,
             "volume": 0.0, "amount": 0.0, "name": "停牌股"},
        ])

    monkeypatch.setattr(sina_snapshot, "fetch_market_spot", fake_fetch)
    fetch = make_sina_intraday_snapshot_fetcher(
        lambda: ["000001.SZ", "000002.SZ"], lambda: [], _SinaRepo(),
    )

    result = fetch()

    rows = {r["symbol"]: r for r in result.frame.to_dicts()}
    assert rows["000001.SZ"]["change_pct"] == 0.0
    assert rows["000002.SZ"]["change_pct"] is None


def test_sina_intraday_fetcher_empty_snapshot_falls_back(monkeypatch):
    # 新浪整源不可用/全空时返回 empty, 由 preloader 保留上一份有效快照,
    # builder 回落本地 enriched, 不得造出当日假数据。
    trade_date = date(2026, 8, 18)
    monkeypatch.setattr(
        "app.services.market_overview_preloader.resolve_market_as_of",
        lambda: _morning_asof(trade_date),
    )

    from app.services import sina_snapshot
    monkeypatch.setattr(
        sina_snapshot, "fetch_market_spot", lambda *args, **kwargs: pl.DataFrame(),
    )
    fetch = make_sina_intraday_snapshot_fetcher(
        lambda: ["000001.SZ"], lambda: [], _SinaRepo(),
    )

    result = fetch()

    assert result.provider == "sina"
    assert result.status == "empty"
    assert result.frame.is_empty()


def test_dashboard_fetcher_does_not_call_realtime_after_close(monkeypatch):
    trade_date = date(2026, 8, 18)
    # 与文件内其他用例一致: 把 preloader 的时钟钉在 trade_date,
    # 否则隔天运行时代码会把 target_date 换成真实今天, 用例变成时间炸弹。
    monkeypatch.setattr("app.services.market_overview_preloader.cn_today", lambda: trade_date)
    monkeypatch.setattr(
        "app.services.market_overview_preloader.resolve_market_as_of",
        lambda: MarketAsOf(
            current_date=trade_date,
            daily_date=trade_date,
            intraday_date=trade_date,
            session=MarketSession.POST_CLOSE,
            cutoff_time="15:00:00",
            is_partial=False,
            observed_at=datetime(2026, 8, 18, 15, 5),
        ),
    )
    monkeypatch.setattr("app.services.preferences.get_realtime_data_provider", lambda: "teajoin")
    monkeypatch.setattr("app.services.preferences.get_daily_data_provider", lambda: "teajoin")
    monkeypatch.setattr(
        "app.data_providers.custom.provider_has_dataset",
        lambda _name, dataset: dataset in {"realtime", "daily"},
    )

    class _Provider:
        def __init__(self):
            self.realtime_calls = 0
            self.daily_calls = 0

        def get_realtime(self):
            self.realtime_calls += 1
            return [{"symbol": "000001.SZ", "last_price": 99.0}]

        def get_latest_daily_snapshot(self, asset_type="stock", as_of=None):
            assert asset_type == "stock"
            assert as_of == datetime(2026, 8, 18)
            self.daily_calls += 1
            return pl.DataFrame([{
                "symbol": "000001.SZ",
                "date": trade_date,
                "close": 12.3,
                "prev_close": 12.0,
                "volume": 100.0,
            }])

        def get_daily(self, symbols, start_time, end_time, asset_type="index"):
            assert asset_type == "index"
            return pl.DataFrame([
                {"symbol": "000001.SH", "date": trade_date, "close": 3001.0},
                {"symbol": "000001.SH", "date": date(2026, 8, 17), "close": 2990.0},
            ])

    provider = _Provider()
    monkeypatch.setattr("app.data_providers.custom.get_provider", lambda _name: provider)
    clock = {"value": 100.0}
    monkeypatch.setattr("app.services.market_overview_preloader.time.time", lambda: clock["value"])

    fetch = make_dashboard_snapshot_fetcher()
    result = fetch()
    clock["value"] = 131.0
    cached = fetch()

    assert result.kind == "teajoin.daily"
    assert result.status == "post_close"
    assert result.snapshot_date == trade_date
    assert result.market_as_of["session"] == "post_close"
    assert cached.snapshot_date == trade_date
    assert provider.realtime_calls == 0
    assert provider.daily_calls == 1


def test_dashboard_fetcher_uses_completed_daily_snapshot_during_lunch(monkeypatch):
    trade_date = date(2026, 8, 18)
    completed_date = date(2026, 8, 17)
    monkeypatch.setattr("app.services.market_overview_preloader.cn_today", lambda: trade_date)
    monkeypatch.setattr(
        "app.services.market_overview_preloader.resolve_market_as_of",
        lambda: MarketAsOf(
            current_date=trade_date,
            daily_date=completed_date,
            intraday_date=trade_date,
            session=MarketSession.LUNCH,
            cutoff_time="11:30:00",
            is_partial=True,
            observed_at=datetime(2026, 8, 18, 12, 0),
        ),
    )
    monkeypatch.setattr("app.services.preferences.get_realtime_data_provider", lambda: "teajoin")
    monkeypatch.setattr("app.services.preferences.get_daily_data_provider", lambda: "teajoin")
    monkeypatch.setattr(
        "app.data_providers.custom.provider_has_dataset",
        lambda _name, dataset: dataset in {"realtime", "daily"},
    )

    class _Provider:
        def __init__(self):
            self.realtime_calls = 0

        def get_realtime(self):
            self.realtime_calls += 1
            return [{"symbol": "000001.SZ", "last_price": 99.0}]

        def get_latest_daily_snapshot(self, asset_type="stock", as_of=None):
            assert asset_type == "stock"
            assert as_of == datetime(2026, 8, 17)
            return pl.DataFrame([{
                "symbol": "000001.SZ",
                "date": completed_date,
                "close": 12.3,
                "prev_close": 12.0,
                "volume": 100.0,
            }])

        def get_daily(self, symbols, start_time, end_time, asset_type="index"):
            assert asset_type == "index"
            return pl.DataFrame([{
                "symbol": "000001.SH",
                "date": completed_date,
                "close": 3001.0,
            }])

    provider = _Provider()
    monkeypatch.setattr("app.data_providers.custom.get_provider", lambda _name: provider)

    result = make_dashboard_snapshot_fetcher()()

    assert result.kind == "teajoin.daily"
    assert result.snapshot_date == completed_date
    assert result.market_as_of["session"] == "lunch"
    assert provider.realtime_calls == 0
