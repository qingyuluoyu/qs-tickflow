from __future__ import annotations


def test_query_market_lets_overview_resolve_latest_real_trading_date(monkeypatch):
    from app.services import ai_tools
    from app.services import market_overview_builder

    captured: dict[str, object] = {}

    def fake_overview(repo, quote_service, depth_service, as_of):
        captured["as_of"] = as_of
        return {"as_of": "2026-08-21", "indices": []}

    monkeypatch.setattr(market_overview_builder, "build_market_overview", fake_overview)

    result = ai_tools._query_market(object(), None, None)

    assert captured["as_of"] is None
    assert result["as_of"] == "2026-08-21"
