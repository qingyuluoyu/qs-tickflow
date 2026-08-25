from __future__ import annotations

from types import SimpleNamespace

import polars as pl

from app.api import intraday


def test_status_includes_preloaded_snapshot_generation():
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(
            quote_service=SimpleNamespace(status=lambda: {"enabled": True, "running": False}),
            market_overview_preloader=SimpleNamespace(status=lambda: {
                "snapshot_generation": 7,
                "snapshot_date": "2026-08-24",
                "snapshot_kind": "teajoin.daily",
                "snapshot_status": "post_close",
            }),
        )),
    )

    result = intraday.status(request)

    assert result["enabled"] is True
    assert result["snapshot_generation"] == 7
    assert result["snapshot_date"] == "2026-08-24"


def test_index_route_prefers_selected_custom_snapshot_over_quote_cache(monkeypatch):
    monkeypatch.setattr(
        intraday,
        "_fallback_index_quotes_from_dashboard_source",
        lambda _request, _symbols: [{
            "symbol": "000001.SH",
            "last_price": 3927.1764,
            "change_pct": 0.005388,
        }],
    )
    monkeypatch.setattr(
        "app.services.preferences.get_daily_data_provider",
        lambda: "teajoin",
    )

    class _QuoteCache:
        def get_index_quotes(self, _symbols):
            raise AssertionError("stale quote cache must not win over TeaJoin")

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(quote_service=_QuoteCache()))
    )

    result = intraday.index_quotes(request, symbols="000001.SH")

    assert result["source"] == "teajoin.daily"
    assert result["rows"][0]["last_price"] == 3927.1764


def test_index_route_reuses_preloaded_index_frame(monkeypatch):
    monkeypatch.setattr(
        "app.services.preferences.get_daily_data_provider",
        lambda: "teajoin",
    )
    monkeypatch.setattr(
        "app.data_providers.custom.provider_has_dataset",
        lambda _name, dataset: dataset == "daily",
    )
    cached = pl.DataFrame([{
        "symbol": "000001.SH",
        "date": "2026-08-14",
        "close": 3927.1764,
        "prev_close": 3926.9648,
        "change_pct": 0.0000538838545,
    }])
    preloader = SimpleNamespace(
        snapshot=lambda: SimpleNamespace(index_frame=cached, snapshot_date=None),
    )

    def fail_if_provider_called(*_args, **_kwargs):
        raise AssertionError("preloaded index frame should avoid another TeaJoin call")

    monkeypatch.setattr(intraday, "_fallback_index_quotes_from_daily", fail_if_provider_called)
    monkeypatch.setattr(
        "app.data_providers.custom.get_provider",
        fail_if_provider_called,
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(
            quote_service=None,
            market_overview_preloader=preloader,
        )),
    )

    result = intraday.index_quotes(request, symbols="000001.SH")

    assert result["source"] == "teajoin.daily"
    assert result["rows"][0]["change_pct"] == 0.00538838545


def test_index_route_local_mode_never_calls_custom_provider(monkeypatch):
    monkeypatch.setattr(
        "app.data_providers.custom.get_provider",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("dashboard local mode must not load a custom provider")
        ),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(
            quote_service=SimpleNamespace(
                get_index_quotes=lambda _symbols: (_ for _ in ()).throw(
                    AssertionError("dashboard local mode must not read realtime cache")
                ),
            ),
            repo=SimpleNamespace(execute_all=lambda *_args, **_kwargs: [
                ("000001.SH", "2026-08-17", 3000.0, 2990.0),
            ]),
        )),
    )

    result = intraday.index_quotes(request, symbols="000001.SH", local_only=True)

    assert result["source"] == "index_daily"
    assert result["rows"][0]["last_price"] == 3000.0


def test_fail_closed_daily_provider_does_not_mix_in_quote_cache(monkeypatch):
    """TeaJoin 无结果时只能退回带日期的本地日线，不能混入旧 TickFlow 缓存。"""
    monkeypatch.setattr(
        intraday,
        "_fallback_index_quotes_from_dashboard_source",
        lambda _request, _symbols: [],
    )
    monkeypatch.setattr(
        "app.services.preferences.get_daily_data_provider",
        lambda: "teajoin",
    )
    monkeypatch.setattr(
        "app.data_providers.custom.get_provider",
        lambda _name: SimpleNamespace(config=SimpleNamespace(fail_closed=True)),
    )

    class _QuoteCache:
        def get_index_quotes(self, _symbols):
            raise AssertionError("fail-closed TeaJoin must not mix in the quote cache")

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(
            quote_service=_QuoteCache(),
            repo=SimpleNamespace(execute_all=lambda *_args, **_kwargs: [
                ("000016.SH", "2026-08-19", 2895.57, 2888.12),
            ]),
        )),
    )

    result = intraday.index_quotes(request, symbols="000016.SH")

    assert result["source"] == "index_daily"
    assert result["rows"][0]["is_realtime"] is False
    assert result["rows"][0]["as_of"] == "2026-08-19"
