from __future__ import annotations

from types import SimpleNamespace

from app.api import intraday


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
