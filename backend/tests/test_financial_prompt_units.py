from __future__ import annotations

import polars as pl

from app.services import financial_analyzer
from app.services.financial_view import prepare_financial_prompt_frame


def test_financial_prompt_frame_exposes_canonical_units_without_ambiguous_raw_fields():
    frame = pl.DataFrame(
        {
            "symbol": ["600000.SH"],
            "trade_date": ["20260824"],
            "total_mv": [1234.0],
            "circ_mv": [1000.0],
            "total_share": [100.0],
            "float_share": [80.0],
            "turnover_rate": [0.5],
        }
    )

    result = prepare_financial_prompt_frame("metrics", frame)
    row = result.to_dicts()[0]

    assert row["market_cap_cny"] == 12_340_000.0
    assert row["float_market_cap_cny"] == 10_000_000.0
    assert row["total_shares"] == 1_000_000.0
    assert row["float_shares"] == 800_000.0
    assert row["turnover_rate_pct"] == 0.5
    assert "total_mv" not in row
    assert "total_share" not in row


def test_financial_analyzer_uses_provider_for_missing_local_rows(monkeypatch, tmp_path):
    calls = []

    def fake_loader(data_dir, table, symbol, *, latest_only=True):
        calls.append((data_dir, table, symbol, latest_only))
        if table != "income":
            return pl.DataFrame()
        return pl.DataFrame(
            {
                "symbol": [symbol],
                "end_date": ["20260630"],
                "ann_date": ["20260820"],
                "n_income": [12.0],
            }
        )

    monkeypatch.setattr(financial_analyzer, "load_financial_frame", fake_loader)
    result = financial_analyzer._load_stock_financials(tmp_path, "000001.SZ")

    assert result["income"][0]["net_income"] == 12.0
    assert calls
    assert all(call[3] is False for call in calls)
