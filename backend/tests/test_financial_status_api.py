from types import SimpleNamespace

import polars as pl

from app.api import financials


def _request_for(data_dir):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                capabilities=object(),
                repo=SimpleNamespace(store=SimpleNamespace(data_dir=data_dir)),
                financial_scheduler=None,
            )
        )
    )


def test_financial_status_reports_actual_latest_dates_and_missing_data_as_null(tmp_path, monkeypatch):
    path = tmp_path / "financials" / "income" / "part.parquet"
    path.parent.mkdir(parents=True)
    pl.DataFrame({
        "symbol": ["000001.SZ", "000002.SZ"],
        "end_date": ["20260331", "20260630"],
        "ann_date": ["20260430", "20260820"],
    }).write_parquet(path)
    monkeypatch.setattr(financials, "_financial_allowed", lambda _: True)

    payload = financials.financial_status(_request_for(tmp_path))

    assert payload["tables"]["income"] == {
        "rows": 2,
        "symbols": 2,
        "latest_period_end": "20260630",
        "latest_announce_date": "20260820",
    }
    assert payload["tables"]["cash_flow"] == {
        "rows": 0,
        "symbols": 0,
        "latest_period_end": None,
        "latest_announce_date": None,
    }
