from __future__ import annotations

from types import SimpleNamespace

from app.api import overview


def test_local_overview_mode_bypasses_live_services_and_preloader(monkeypatch):
    calls: dict = {}

    class _Preloader:
        def snapshot(self):
            raise AssertionError("local dashboard mode must not read the preloader")

    def fake_build(**kwargs):
        calls.update(kwargs)
        return {"data_freshness": {"source": "teajoin", "snapshot_kind": "teajoin.realtime"}}

    monkeypatch.setattr("app.services.market_overview_builder.build_market_overview", fake_build)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(
            repo=object(),
            quote_service=object(),
            depth_service=object(),
            market_overview_preloader=_Preloader(),
        )),
    )

    result = overview._build_overview(request, local_only=True)

    assert calls["quote_service"] is None
    assert calls["dashboard_live"] is False
    assert calls["dashboard_snapshot"] is None
    assert result["data_freshness"] == {
        "source": "persisted",
        "snapshot_kind": "persisted.enriched",
        "realtime_provider": None,
        "realtime_status": None,
        "realtime_rows": 0,
    }
