from __future__ import annotations

import polars as pl


def test_ai_financial_loader_prefers_fresh_provider_rows_over_stale_local_rows(monkeypatch, tmp_path):
    from app.services import financial_view

    local_dir = tmp_path / "financials" / "income"
    local_dir.mkdir(parents=True)
    pl.DataFrame({
        "symbol": ["000001.SZ"],
        "end_date": ["20241231"],
        "ann_date": ["20250301"],
        "n_income": [10.0],
    }).write_parquet(local_dir / "part.parquet")

    class Provider:
        def get_financials(self, table, symbols, *, latest_only):
            assert table == "income"
            assert symbols == ["000001.SZ"]
            assert latest_only is False
            return pl.DataFrame({
                "symbol": ["000001.SZ"],
                "end_date": ["20250630"],
                "ann_date": ["20250820"],
                "n_income": [20.0],
            })

    monkeypatch.setattr(financial_view, "_custom_financial_provider", lambda: Provider())

    result = financial_view.load_financial_frame(
        tmp_path, "income", "000001.SZ", latest_only=False, prefer_provider=True,
    )

    assert result["period_end"].to_list() == ["20250630"]
    assert result["net_income"].to_list() == [20.0]


def test_query_financials_maps_legacy_balance_name_to_canonical_table(monkeypatch, tmp_path):
    from app.services import ai_tools

    seen: list[str] = []

    def fake_loader(_data_dir, table, _symbol, *, latest_only, prefer_provider):
        seen.append(table)
        assert latest_only is False
        assert prefer_provider is True
        return pl.DataFrame({
            "symbol": ["000001.SZ"],
            "period_end": ["20250630"],
            "total_assets": [100.0],
        })

    monkeypatch.setattr(ai_tools, "load_financial_frame", fake_loader)
    repo = type("Repo", (), {"resolve_asset_type": lambda _self, _symbol: "stock"})()

    result = ai_tools._query_financials(repo, tmp_path, "000001.SZ", "balance")

    assert seen == ["balance_sheet"]
    assert result["balance_sheet"][0]["total_assets"] == 100.0
