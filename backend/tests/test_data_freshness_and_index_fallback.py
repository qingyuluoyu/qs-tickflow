"""数据新鲜度与指数日线兜底契约测试。"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.api import data as data_api
from app.api import intraday


def test_market_data_health_exposes_current_date_and_partial_coverage_summary():
    health = data_api.build_market_data_health({
        "job_id": "job-20260819",
        "data_freshness": {
            "status": "partial",
            "provider": "teajoin",
            "target_date": "2026-08-19",
            "provider_date": "2026-08-19",
            "persisted_daily_date": "2026-08-19",
            "persisted_enriched_date": "2026-08-19",
            "requested_symbol_count": 5885,
            "available_symbol_count": 5539,
            "missing_symbol_count": 346,
            "inactive_symbol_count": 334,
            "unresolved_symbol_count": 12,
            "persistence_status": "ready",
            "provider_reconciliation": {"status": "checked"},
        },
    })

    assert health["freshness"]["status"] == "current"
    assert health["freshness"]["as_of"] == "2026-08-19"
    assert health["freshness"]["daily_date"] == "2026-08-19"
    assert health["freshness"]["enriched_date"] == "2026-08-19"
    assert health["freshness"]["coverage"] == "partial"


def test_daily_index_fallback_is_explicitly_non_realtime_and_dated():
    class Repo:
        def execute_all(self, _sql, _params):
            return [("000016.SH", date(2026, 8, 19), 2895.57, 2888.12)]

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(repo=Repo())),
    )

    rows = intraday._fallback_index_quotes_from_daily(request, ["000016.SH"])

    assert len(rows) == 1
    assert rows[0] == {
        "symbol": "000016.SH",
        "name": None,
        "date": "2026-08-19",
        "as_of": "2026-08-19",
        "last_price": 2895.57,
        "close": 2895.57,
        "prev_close": 2888.12,
        "change_amount": pytest.approx(7.45),
        "change_pct": pytest.approx(0.25795, abs=1e-5),
        "source": "index_daily",
        "is_realtime": False,
    }
