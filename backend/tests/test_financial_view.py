import polars as pl

from app.api import financials as financials_api
from app.services.financial_analyzer import _load_stock_financials
from app.services.financial_view import (
    load_financial_frame,
    normalize_financial_frame,
    search_financial_symbols,
)


def test_normalize_financial_frame_adds_frontend_contract_aliases():
    raw = pl.DataFrame({
        "ts_code": ["000001.SZ"],
        "trade_date": ["20260813"],
        "turnover_rate": [0.5],
        "total_mv": [100.0],
    })

    result = normalize_financial_frame("metrics", raw)
    row = result.to_dicts()[0]

    assert row["period_end"] == "20260813"
    assert row["announce_date"] == "20260813"
    assert row["market_cap"] == 1_000_000.0


def test_normalize_financial_frame_maps_tushare_report_fields():
    raw = pl.DataFrame({
        "symbol": ["000001.SZ"],
        "end_date": ["20240630"],
        "ann_date": ["20240816"],
        "oper_cost": [10.0],
        "operate_profit": [12.0],
        "n_income": [8.0],
    })

    row = normalize_financial_frame("income", raw).to_dicts()[0]

    assert row["period_end"] == "20240630"
    assert row["announce_date"] == "20240816"
    assert row["operating_cost"] == 10.0
    assert row["operating_profit"] == 12.0
    assert row["net_income"] == 8.0


def test_load_financial_frame_uses_provider_when_local_symbol_is_missing(tmp_path):
    class Provider:
        def __init__(self):
            self.calls = []
            self.closed = False

        def get_financials(self, table, symbols, latest_only=True):
            self.calls.append((table, symbols, latest_only))
            return pl.DataFrame({
                "symbol": symbols,
                "end_date": ["20240630"],
                "ann_date": ["20240816"],
                "n_income": [8.0],
            })

        def close(self):
            self.closed = True

    provider = Provider()
    result = load_financial_frame(
        tmp_path,
        "income",
        "000001.SZ",
        provider_factory=lambda: provider,
    )

    assert result.to_dicts() == [{
        "symbol": "000001.SZ",
        "end_date": "20240630",
        "ann_date": "20240816",
        "n_income": 8.0,
        "period_end": "20240630",
        "announce_date": "20240816",
        "net_income": 8.0,
    }]
    assert provider.calls == [("income", ["000001.SZ"], True)]
    assert provider.closed is True


def test_load_financial_frame_keeps_shared_custom_provider_open(tmp_path, monkeypatch):
    class Provider:
        def __init__(self):
            self.closed = False

        def get_financials(self, table, symbols, latest_only=True):
            return pl.DataFrame({
                "symbol": symbols,
                "end_date": ["20240630"],
                "n_income": [8.0],
            })

        def close(self):
            self.closed = True

    provider = Provider()
    monkeypatch.setattr(
        "app.services.financial_view._custom_financial_provider",
        lambda: provider,
    )

    result = load_financial_frame(tmp_path, "income", "000001.SZ")

    assert result.get_column("symbol").to_list() == ["000001.SZ"]
    assert provider.closed is False


def test_search_financial_symbols_falls_back_to_custom_instruments():
    class Repo:
        def get_instruments_asset(self, asset_type):
            return pl.DataFrame()

    result = search_financial_symbols(
        Repo(),
        "600519",
        instruments_factory=lambda: pl.DataFrame({
            "symbol": ["600519.SH"],
            "name": ["贵州茅台"],
            "code": ["600519"],
        }),
    )

    assert result == [{
        "symbol": "600519.SH",
        "name": "贵州茅台",
        "code": "600519",
        "asset_type": "stock",
    }]


def test_search_financial_symbols_keeps_default_provider_open(monkeypatch):
    class Provider:
        def __init__(self):
            self.closed = False

        def get_instruments(self, asset_type):
            assert asset_type == "stock"
            return pl.DataFrame({
                "symbol": ["600519.SH"],
                "name": ["贵州茅台"],
                "code": ["600519"],
            })

        def close(self):
            self.closed = True

    provider = Provider()
    monkeypatch.setattr(
        "app.services.financial_view._custom_financial_provider",
        lambda: provider,
    )

    class Repo:
        def get_instruments_asset(self, asset_type):
            return pl.DataFrame()

    assert search_financial_symbols(Repo(), "600519")[0]["symbol"] == "600519.SH"
    assert provider.closed is False


def test_financial_search_route_is_registered():
    paths = {route.path for route in financials_api.router.routes}
    assert "/api/financials/search" in paths


def test_financial_analyzer_reads_canonical_periods_from_teajoin_rows(tmp_path):
    path = tmp_path / "financials" / "income" / "part.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({
        "symbol": ["000001.SZ"],
        "end_date": ["20240630"],
        "ann_date": ["20240816"],
        "n_income": [8.0],
    }).write_parquet(path)

    result = _load_stock_financials(tmp_path, "000001.SZ")

    assert result["income"][0]["period_end"] == "20240630"
    assert result["income"][0]["net_income"] == 8.0
