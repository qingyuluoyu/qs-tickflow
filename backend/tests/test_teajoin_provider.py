from datetime import datetime
from pathlib import Path

import polars as pl
import pytest
import yaml

from app.data_providers.custom.config import CustomSourceConfig, DatasetConfig
from app.data_providers.custom.loader import _sanitize_for_yaml
from app.data_providers.custom.provider import GenericHTTPProvider
from app.services import instrument_sync


def test_private_deploy_secret_file_is_used_when_environment_is_empty(monkeypatch, tmp_path: Path):
    from app.config import settings
    from app.data_providers.custom.provider import _token_from_env

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.delenv("TEAJOIN_API_KEY", raising=False)
    secret = tmp_path / "private" / "TEAJOIN_API_KEY"
    secret.parent.mkdir()
    secret.write_text("private-deploy-token\n", encoding="utf-8")

    assert _token_from_env("TEAJOIN_API_KEY") == "private-deploy-token"


def test_environment_secret_wins_over_private_deploy_file(monkeypatch, tmp_path: Path):
    from app.config import settings
    from app.data_providers.custom.provider import _token_from_env

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    secret = tmp_path / "private" / "TEAJOIN_API_KEY"
    secret.parent.mkdir()
    secret.write_text("file-token", encoding="utf-8")
    monkeypatch.setenv("TEAJOIN_API_KEY", "environment-token")

    assert _token_from_env("TEAJOIN_API_KEY") == "environment-token"


def test_teajoin_minute_dataset_uses_official_stk_mins_contract():
    config_path = Path(__file__).resolve().parents[2] / "data" / "data_sources" / "teajoin.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    minute = config["datasets"]["minute"]

    assert minute["url"] == "https://teajoin.com/stk_mins"
    assert minute["symbols_body_path"] == "params.ts_code"
    assert minute["start_body_path"] == "params.start_date"
    assert minute["end_body_path"] == "params.end_date"
    assert minute["body"]["params"]["freq"] == "1min"
    assert minute["field_map"]["trade_time"] == "datetime"
    # TeaJoin stk_mins requires full timestamps, unlike daily which accepts
    # YYYYMMDD.  Sending date-only values makes an otherwise valid request fail.
    assert minute.get("date_only", False) is False
    assert minute.get("date_format", "") == ""


def test_teajoin_daily_dataset_supports_exact_trade_date_queries():
    config_path = Path(__file__).resolve().parents[2] / "data" / "data_sources" / "teajoin.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    daily = config["datasets"]["daily"]

    assert daily["trade_date_body_path"] == "params.trade_date"


def test_teajoin_minute_normalizes_trade_time_to_datetime():
    from app.data_providers.custom.provider import GenericHTTPProvider

    df = pl.DataFrame({
        "symbol": ["000001.SZ"],
        "datetime": ["2026-08-14 15:00:00"],
        "open": [11.1],
        "high": [11.2],
        "low": [11.0],
        "close": [11.1],
        "volume": [100.0],
        "amount": [1100.0],
    })

    normalized = GenericHTTPProvider._normalize_minute(df)

    assert normalized.schema["datetime"] == pl.Datetime("us")
    assert normalized["datetime"].item() == datetime(2026, 8, 14, 15, 0)


def test_teajoin_realtime_dataset_keeps_table_wrapper_for_fields_mapping():
    config_path = Path(__file__).resolve().parents[2] / "data" / "data_sources" / "teajoin.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    realtime = config["datasets"]["realtime"]

    # TeaJoin returns {fields: [...], items: [[...]]}; extracting data.items
    # first loses the field names and turns every row into an unparseable list.
    assert realtime["response_path"] == "data"


def test_teajoin_realtime_dataset_supports_symbol_queries():
    config_path = Path(__file__).resolve().parents[2] / "data" / "data_sources" / "teajoin.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    realtime = config["datasets"]["realtime"]

    assert realtime["batch"] == 100
    assert realtime["symbols_body_path"] == "params.ts_code"
    assert realtime["body"] == {"params": {}}


def test_realtime_symbol_path_survives_settings_config_roundtrip():
    from app.data_providers.custom.loader import _config_to_dict, load_config

    config_path = Path(__file__).resolve().parents[2] / "data" / "data_sources" / "teajoin.yaml"
    config_dict = _config_to_dict(load_config(config_path))

    assert config_dict["datasets"]["realtime"]["symbols_body_path"] == "params.ts_code"


def test_realtime_symbol_query_places_codes_in_nested_params_body():
    provider = GenericHTTPProvider(CustomSourceConfig(
        name="teajoin",
        display_name="TeaJoin",
        datasets={
            "realtime": DatasetConfig(
                url="https://teajoin.example/realtime",
                method="POST",
                body={"params": {}},
                symbols_body_path="params.ts_code",
                field_map={
                    "ts_code": "symbol", "last": "last_price", "pre_close": "prev_close",
                    "open": "open", "high": "high", "low": "low", "vol": "volume",
                },
            ),
        },
    ))
    captured = {}

    def request(method, url, **kwargs):
        captured.update(method=method, url=url, kwargs=kwargs)
        return type("Response", (), {
            "raise_for_status": lambda self: None,
            "json": lambda self: {"data": {"fields": [], "items": []}},
        })()

    provider._client.request = request
    provider.get_realtime(symbols=["000001.SZ", "600000.SH"])
    provider.close()

    assert captured["kwargs"]["json"]["params"]["ts_code"] == "000001.SZ,600000.SH"


def test_teajoin_realtime_table_payload_maps_to_quote_records():
    from app.data_providers.custom.config import load_config

    config_path = Path(__file__).resolve().parents[2] / "data" / "data_sources" / "teajoin.yaml"
    provider = GenericHTTPProvider(load_config(config_path))

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": {
                    "fields": ["ts_code", "last", "pre_close", "pct_chg"],
                    "items": [["000001.SZ", 11.25, 11.10, 1.35]],
                }
            }

    provider._client.request = lambda *_args, **_kwargs: Response()
    rows = provider.get_realtime()
    provider.close()

    assert rows[0]["symbol"] == "000001.SZ"
    assert rows[0]["last_price"] == "11.25"
    assert rows[0]["prev_close"] == "11.1"
    assert rows[0]["change_pct"] == pytest.approx(0.0135)


def test_financial_dataset_test_uses_a_real_configured_table():
    provider = GenericHTTPProvider(CustomSourceConfig(
        name="teajoin",
        display_name="TeaJoin",
        datasets={
            "financial": DatasetConfig(
                url="https://teajoin.example/financial",
                financial_table_map={"metrics": "daily_basic"},
                field_map={"ts_code": "symbol"},
            ),
        },
    ))
    captured: dict[str, object] = {}

    def get_financials(table, symbols, latest_only=True):
        captured.update(table=table, symbols=symbols, latest_only=latest_only)
        return pl.DataFrame({"symbol": ["000001.SZ"], "pe": [8.1]})

    provider.get_financials = get_financials
    result = provider.test_dataset("financial", ["000001.SZ"])
    provider.close()

    assert captured == {"table": "metrics", "symbols": ["000001.SZ"], "latest_only": True}
    assert result["rows"] == 1
    assert result["columns"] == ["symbol", "pe"]


def test_teajoin_config_maps_all_financial_tables_to_real_endpoints():
    config_path = Path(__file__).resolve().parents[2] / "data" / "data_sources" / "teajoin.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    table_map = config["datasets"]["financial"]["financial_table_map"]

    assert table_map == {
        "metrics": "daily_basic",
        "income": "income",
        "balance_sheet": "balancesheet",
        "cash_flow": "cashflow",
        "shares": "daily_basic",
    }


def test_teajoin_daily_config_normalizes_amount_to_yuan():
    config_path = Path(__file__).resolve().parents[2] / "data" / "data_sources" / "teajoin.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert config["datasets"]["daily"]["transforms"]["amount"] == "value * 1000"


def test_teajoin_realtime_config_normalizes_percent_fields_to_decimal():
    config_path = Path(__file__).resolve().parents[2] / "data" / "data_sources" / "teajoin.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    transforms = config["datasets"]["realtime"]["transforms"]
    assert transforms["change_pct"] == "value / 100"
    assert transforms["amplitude"] == "value / 100"
    assert transforms["turnover_rate"] == "value / 100"


def test_latest_daily_snapshot_requests_unfiltered_rows_and_keeps_latest_date():
    provider = GenericHTTPProvider(CustomSourceConfig(
        name="teajoin",
        display_name="TeaJoin",
        datasets={
            "daily": DatasetConfig(
                url="https://teajoin.example/daily",
                method="POST",
                field_map={
                    "ts_code": "symbol", "trade_date": "date", "open": "open",
                    "high": "high", "low": "low", "close": "close",
                    "pre_close": "prev_close", "pct_chg": "change_pct",
                    "change": "change_amount", "vol": "volume", "amount": "amount",
                },
                transforms={
                    "date": "parse_date(value, '%Y%m%d')",
                    "change_pct": "value / 100",
                    "amount": "value * 1000",
                },
            ),
        },
    ))

    captured = {}

    def request_rows(_cfg, **kwargs):
        captured.update(kwargs)
        return [
            {"ts_code": "000001.SZ", "trade_date": "20260813", "close": 11,
             "pre_close": 10, "pct_chg": 10, "change": 1, "vol": 100, "amount": 2},
            {"ts_code": "000001.SZ", "trade_date": "20260814", "close": 12,
             "pre_close": 11, "pct_chg": 9.0909, "change": 1, "vol": 120, "amount": 3},
        ]

    provider._request_rows = request_rows
    result = provider.get_latest_daily_snapshot()
    provider.close()

    assert captured == {"override_url": "https://teajoin.example/daily"}
    assert result.height == 1
    assert result["date"].item().isoformat() == "2026-08-14"
    assert result["change_pct"].item() == 0.090909
    assert result["amount"].item() == 3000


def test_latest_daily_snapshot_can_query_an_explicit_trade_date():
    provider = GenericHTTPProvider(CustomSourceConfig(
        name="teajoin",
        display_name="TeaJoin",
        datasets={
            "daily": DatasetConfig(
                url="https://teajoin.example/daily",
                method="POST",
                body={"params": {}},
                response_path="data",
                trade_date_body_path="params.trade_date",
                date_only=True,
                date_format="%Y%m%d",
                field_map={
                    "ts_code": "symbol", "trade_date": "date", "close": "close",
                },
                transforms={"date": "parse_date(value, '%Y%m%d')"},
            ),
        },
    ))
    captured: dict[str, object] = {}

    def request(_method, _url, **kwargs):
        captured.update(kwargs)
        return type("Response", (), {
            "raise_for_status": lambda self: None,
            "json": lambda self: {
                "data": {
                    "fields": ["ts_code", "trade_date", "close"],
                    "items": [["000001.SZ", "20260817", 12.5]],
                },
            },
        })()

    provider._client.request = request
    result = provider.get_latest_daily_snapshot(
        as_of=datetime(2026, 8, 17),
    )
    provider.close()

    assert captured["json"]["params"] == {"trade_date": "20260817"}
    assert result["date"].item().isoformat() == "2026-08-17"


def test_teajoin_daily_request_places_symbol_and_dates_in_nested_params_body():
    provider = GenericHTTPProvider(CustomSourceConfig(
        name="teajoin",
        display_name="TeaJoin",
        datasets={
            "daily": DatasetConfig(
                url="https://teajoin.example/daily",
                method="POST",
                symbols_body_path="params.ts_code",
                start_body_path="params.start_date",
                end_body_path="params.end_date",
                date_only=True,
                date_format="%Y%m%d",
                field_map={
                    "ts_code": "symbol", "trade_date": "date", "open": "open",
                    "high": "high", "low": "low", "close": "close",
                    "vol": "volume", "amount": "amount",
                },
            ),
        },
    ))
    captured = {}

    def request(method, url, **kwargs):
        captured.update(kwargs)
        return type("Response", (), {
            "raise_for_status": lambda self: None,
            "json": lambda self: {"data": {"fields": [], "items": []}},
        })()

    provider._client.request = request
    provider.get_daily(
        ["000001.SZ"],
        datetime(2026, 8, 1),
        datetime(2026, 8, 12),
    )
    provider.close()

    assert captured["json"]["params"] == {
        "ts_code": "000001.SZ",
        "start_date": "20260801",
        "end_date": "20260812",
    }


def test_teajoin_request_retries_a_transient_transport_failure(monkeypatch):
    import httpx

    provider = GenericHTTPProvider(CustomSourceConfig(
        name="teajoin",
        display_name="TeaJoin",
        datasets={"daily": DatasetConfig(url="https://teajoin.example/daily", response_path="data")},
    ))
    attempts = 0

    def request(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.RemoteProtocolError("server disconnected")
        return type("Response", (), {
            "raise_for_status": lambda self: None,
            "json": lambda self: {"data": {"fields": [], "items": []}},
        })()

    monkeypatch.setattr(provider._client, "request", request)

    assert provider._request_rows(provider._dataset("daily")) == []
    provider.close()
    assert attempts == 2


def test_daily_splits_long_ranges_and_reports_combined_progress(monkeypatch):
    provider = GenericHTTPProvider(CustomSourceConfig(
        name="teajoin",
        display_name="TeaJoin",
        datasets={
            "daily": DatasetConfig(
                url="https://teajoin.example/daily",
                batch=2,
                range_window_days=3,
                field_map={
                    "ts_code": "symbol", "trade_date": "date", "open": "open",
                    "high": "high", "low": "low", "close": "close",
                    "vol": "volume", "amount": "amount",
                },
                 transforms={
                     "date": "parse_date(value, '%Y%m%d')",
                     "amount": "value * 1000",
                 },
            ),
        },
    ))
    calls: list[tuple[list[str], datetime, datetime]] = []
    progress: list[tuple[int, int]] = []

    def request_rows(_cfg, *, symbols, start_time, end_time, **_kwargs):
        calls.append((symbols, start_time, end_time))
        return [{
            "ts_code": symbol,
            "trade_date": start_time.strftime("%Y%m%d"),
            "open": 10, "high": 11, "low": 9, "close": 10,
            "vol": 100, "amount": 1000,
        } for symbol in symbols]

    monkeypatch.setattr(provider, "_request_rows", request_rows)
    monkeypatch.setattr("app.data_providers.custom.provider.sleep_between_batches", lambda *_: None)

    result = provider.get_daily(
        ["000001.SZ", "000002.SZ", "000003.SZ"],
        datetime(2026, 8, 1),
        datetime(2026, 8, 7),
        on_chunk_done=lambda done, total: progress.append((done, total)),
    )
    provider.close()

    assert len(calls) == 6
    assert [(start.date().isoformat(), end.date().isoformat()) for _, start, end in calls] == [
        ("2026-08-01", "2026-08-03"), ("2026-08-01", "2026-08-03"),
        ("2026-08-04", "2026-08-06"), ("2026-08-04", "2026-08-06"),
        ("2026-08-07", "2026-08-07"), ("2026-08-07", "2026-08-07"),
    ]
    assert progress == [(1, 6), (2, 6), (3, 6), (4, 6), (5, 6), (6, 6)]
    assert result.height == 9
    assert result["amount"].unique().to_list() == [1_000_000.0]


def test_extract_rows_returns_no_wrapper_row_for_empty_teajoin_table():
    from app.data_providers.custom.mapper import extract_rows

    assert extract_rows({"data": {"fields": ["ts_code"], "items": []}}, "data") == []


def test_teajoin_instruments_normalizes_stock_basic_rows():
    provider = GenericHTTPProvider(CustomSourceConfig(
        name="teajoin",
        display_name="TeaJoin",
        datasets={
            "instruments": DatasetConfig(
                url="https://teajoin.example/stock_basic",
                method="POST",
                response_path="data",
                field_map={"ts_code": "symbol", "symbol": "code", "name": "name"},
            ),
        },
    ))
    provider._request_rows = lambda *_args, **_kwargs: [
        {"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行"},
    ]

    result = provider.get_instruments("stock")
    provider.close()

    assert result.to_dicts() == [{
        "symbol": "000001.SZ", "name": "平安银行", "code": "000001",
        "exchange": "SZ", "asset_type": "stock", "source": "teajoin",
    }]


def test_instruments_uses_asset_specific_endpoint_and_derives_code():
    provider = GenericHTTPProvider(CustomSourceConfig(
        name="teajoin",
        display_name="TeaJoin",
        datasets={
            "instruments": DatasetConfig(
                url="https://teajoin.example/stock_basic",
                instruments_url_by_asset_type={"index": "https://teajoin.example/index_basic"},
                field_map={"ts_code": "symbol", "name": "name"},
            ),
        },
    ))
    captured = {}

    def request_rows(_cfg, **kwargs):
        captured.update(kwargs)
        return [{"ts_code": "000001.SH", "name": "上证指数"}]

    provider._request_rows = request_rows
    result = provider.get_instruments("index")
    provider.close()

    assert captured["override_url"] == "https://teajoin.example/index_basic"
    assert result.to_dicts() == [{
        "symbol": "000001.SH", "name": "上证指数", "code": "000001",
        "exchange": "SH", "asset_type": "index", "source": "teajoin",
    }]


def test_instruments_uses_asset_specific_request_params():
    provider = GenericHTTPProvider(CustomSourceConfig(
        name="teajoin",
        display_name="TeaJoin",
        datasets={
            "instruments": DatasetConfig(
                url="https://teajoin.example/stock_basic",
                instruments_params_by_asset_type={"etf": {"market": "E"}},
                field_map={"ts_code": "symbol", "name": "name"},
            ),
        },
    ))
    captured = {}
    provider._request_rows = lambda _cfg, **kwargs: captured.update(kwargs) or []

    provider.get_instruments("etf")
    provider.close()

    assert captured["override_params"] == {"market": "E"}


def test_instruments_supports_asset_specific_nested_request_body():
    provider = GenericHTTPProvider(CustomSourceConfig(
        name="teajoin",
        display_name="TeaJoin",
        datasets={
            "instruments": DatasetConfig(
                url="https://teajoin.example/fund_basic",
                body={"params": {}},
                instruments_body_by_asset_type={"etf": {"params": {"market": "E"}}},
                field_map={"ts_code": "symbol", "name": "name"},
            ),
        },
    ))
    captured = {}
    provider._request_rows = lambda _cfg, **kwargs: captured.update(kwargs) or []

    provider.get_instruments("etf")
    provider.close()

    assert captured["override_body"] == {"params": {"market": "E"}}


def test_teajoin_daily_and_factors_normalize_real_response_shape():
    provider = GenericHTTPProvider(CustomSourceConfig(
        name="teajoin",
        display_name="TeaJoin",
        datasets={
            "daily": DatasetConfig(
                url="https://teajoin.example/daily", response_path="data",
                transforms={"date": "parse_date(value, '%Y%m%d')"},
                field_map={
                    "ts_code": "symbol", "trade_date": "date", "open": "open",
                    "high": "high", "low": "low", "close": "close",
                    "vol": "volume", "amount": "amount",
                },
            ),
            "adj_factor": DatasetConfig(
                url="https://teajoin.example/adj_factor", response_path="data",
                transforms={"trade_date": "parse_date(value, '%Y%m%d')"},
                field_map={"ts_code": "symbol", "trade_date": "trade_date", "adj_factor": "ex_factor"},
            ),
        },
    ))
    provider._request_rows = lambda cfg, **_kwargs: (
        [{"ts_code": "000001.SZ", "trade_date": "20260812", "open": 11.2,
          "high": 11.3, "low": 11.1, "close": 11.25, "vol": 100, "amount": 1000}]
        if cfg.url.endswith("daily") else
        [{"ts_code": "000001.SZ", "trade_date": "20260812", "adj_factor": 139.008}]
    )

    daily = provider.get_daily(["000001.SZ"], None, None)
    factors = provider.get_adj_factors(["000001.SZ"], None, None)
    provider.close()

    assert daily.schema["date"] == __import__("polars").Date
    assert daily.row(0, named=True)["amount"] == 1000.0
    assert factors.schema["trade_date"] == __import__("polars").Date
    assert factors.row(0, named=True)["ex_factor"] == 139.008


def test_teajoin_cumulative_adj_factors_are_converted_to_event_ratios():
    provider = GenericHTTPProvider(CustomSourceConfig(
        name="teajoin",
        display_name="TeaJoin",
        datasets={
            "adj_factor": DatasetConfig(
                url="https://teajoin.example/adj_factor",
                response_path="data",
                adj_factor_kind="cumulative",
                transforms={"trade_date": "parse_date(value, '%Y%m%d')"},
                field_map={
                    "ts_code": "symbol", "trade_date": "trade_date",
                    "adj_factor": "ex_factor",
                },
            ),
        },
    ))
    provider._request_rows = lambda *_args, **_kwargs: [
        {"ts_code": "000001.SZ", "trade_date": "20260811", "adj_factor": 139.008},
        {"ts_code": "000001.SZ", "trade_date": "20260812", "adj_factor": 139.008},
        {"ts_code": "600000.SH", "trade_date": "20260811", "adj_factor": 10.0},
        {"ts_code": "600000.SH", "trade_date": "20260812", "adj_factor": 12.0},
    ]

    factors = provider.get_adj_factors(["000001.SZ", "600000.SH"], None, None)
    provider.close()

    assert factors.sort(["symbol", "trade_date"]).to_dicts() == [
        {"symbol": "000001.SZ", "trade_date": __import__("datetime").date(2026, 8, 11), "ex_factor": 1.0},
        {"symbol": "000001.SZ", "trade_date": __import__("datetime").date(2026, 8, 12), "ex_factor": 1.0},
        {"symbol": "600000.SH", "trade_date": __import__("datetime").date(2026, 8, 11), "ex_factor": 1.0},
        {"symbol": "600000.SH", "trade_date": __import__("datetime").date(2026, 8, 12), "ex_factor": 1.2},
    ]


def test_daily_repair_is_allowed_for_a_custom_batch_provider(monkeypatch):
    from app.api import kline

    class Capset:
        def has(self, _cap):
            return False

    monkeypatch.setattr("app.services.preferences.get_daily_data_provider", lambda: "teajoin")
    monkeypatch.setattr("app.data_providers.custom.provider_has_dataset", lambda name, dataset: (name, dataset) == ("teajoin", "daily"))

    assert kline._daily_repair_allowed(Capset()) is True


def test_custom_daily_sync_releases_parquet_read_handles_before_rewrite(monkeypatch):
    from app.services import kline_sync

    calls: list[str] = []

    class Provider:
        def get_daily(self, *_args, **_kwargs):
            return pl.DataFrame({
                "symbol": ["000001.SZ"], "date": [__import__("datetime").date(2026, 8, 13)],
                "open": [10.0], "high": [11.0], "low": [9.0], "close": [10.0],
                "volume": [100.0], "amount": [1000.0],
            })

    class Repo:
        store = type("Store", (), {"data_dir": Path(".")})()

        def release_parquet_read_handles(self):
            calls.append("release")

        def append_daily(self, _df):
            calls.append("append")

    monkeypatch.setattr("app.services.preferences.get_daily_data_provider", lambda: "teajoin")
    monkeypatch.setattr("app.data_providers.custom.provider_has_dataset", lambda *_: True)
    monkeypatch.setattr("app.data_providers.custom.get_provider", lambda _name: Provider())

    monkeypatch.setattr(kline_sync, "logger", type("Logger", (), {"warning": lambda *_: None})())
    assert kline_sync.sync_and_persist_daily_batch(
        ["000001.SZ"], Repo(), capset=None,
        start_date=__import__("datetime").datetime(2026, 8, 13),
        end_date=__import__("datetime").datetime(2026, 8, 13),
    ) == 1
    assert calls == ["release", "append"]


def test_data_write_refresh_rebuilds_memory_and_invalidates_overview(monkeypatch):
    from app.api import kline

    calls: list[str] = []

    class Repo:
        def clear_cache(self):
            calls.append("clear")

        def refresh_cache(self):
            calls.append("refresh")

    monkeypatch.setattr("app.api.overview.invalidate_overview_cache", lambda: calls.append("overview"))
    monkeypatch.setattr("app.services.screener.ScreenerService.clear_history_cache", lambda: calls.append("screener"))

    kline._refresh_after_data_write(Repo())

    assert calls == ["clear", "refresh", "overview", "screener"]


def test_daily_uses_asset_specific_endpoint_for_index():
    provider = GenericHTTPProvider(CustomSourceConfig(
        name="teajoin",
        display_name="TeaJoin",
        datasets={
            "daily": DatasetConfig(
                url="https://teajoin.example/daily",
                daily_url_by_asset_type={"index": "https://teajoin.example/index_daily"},
                field_map={
                    "ts_code": "symbol", "trade_date": "date", "open": "open",
                    "high": "high", "low": "low", "close": "close",
                    "vol": "volume", "amount": "amount",
                },
            ),
        },
    ))
    captured = {}

    def request_rows(_cfg, **kwargs):
        captured.update(kwargs)
        return []

    provider._request_rows = request_rows
    provider.get_daily(["000001.SH"], None, None, asset_type="index")
    provider.close()

    assert captured["override_url"] == "https://teajoin.example/index_daily"


def test_instrument_sync_uses_custom_provider_dataframe_without_tickflow(monkeypatch):
    class Provider:
        def get_instruments(self, asset_type):
            assert asset_type == "stock"
            return pl.DataFrame({
                "symbol": ["000001.SZ"], "name": ["平安银行"], "code": ["000001"],
                "exchange": ["SZ"], "asset_type": ["stock"], "source": ["teajoin"],
            })

    monkeypatch.setattr("app.services.preferences.get_daily_data_provider", lambda: "teajoin")
    monkeypatch.setattr("app.data_providers.custom.is_custom_provider", lambda _: True)
    monkeypatch.setattr("app.data_providers.custom.get_provider", lambda _: Provider())

    assert instrument_sync._fetch_instruments_via_provider() == [{
        "symbol": "000001.SZ", "name": "平安银行", "code": "000001", "exchange": "SZ",
        "region": None, "type": "stock", "listing_date": None, "total_shares": None,
        "float_shares": None, "tick_size": None, "limit_up": None, "limit_down": None,
    }]


def test_instrument_sync_does_not_fall_back_to_tickflow_when_selected_provider_fails(monkeypatch):
    monkeypatch.setattr("app.services.preferences.get_daily_data_provider", lambda: "teajoin")
    monkeypatch.setattr("app.data_providers.custom.is_custom_provider", lambda _: True)
    monkeypatch.setattr("app.data_providers.custom.get_provider", lambda _: (_ for _ in ()).throw(RuntimeError("offline")))

    assert instrument_sync._fetch_instruments_via_provider() == []


def test_teajoin_financial_table_alias_uses_verified_endpoint_name():
    provider = GenericHTTPProvider(CustomSourceConfig(
        name="teajoin",
        display_name="TeaJoin",
        datasets={
            "financial": DatasetConfig(
                url="https://teajoin.example/financial",
                method="POST",
                financial_url_template="https://teajoin.example/{table}",
                financial_table_map={"balance_sheet": "balancesheet"},
                symbols_body_path="params.ts_code",
                field_map={"ts_code": "symbol"},
            ),
        },
    ))
    captured = {}

    def request_rows(cfg, **kwargs):
        captured.update(kwargs)
        return [{"ts_code": "000001.SZ", "total_assets": 100.0}]

    provider._request_rows = request_rows
    result = provider.get_financials("balance_sheet", ["000001.SZ"])
    provider.close()

    assert captured["override_url"] == "https://teajoin.example/balancesheet"
    assert result.to_dicts() == [{"symbol": "000001.SZ", "total_assets": 100.0}]


def test_teajoin_daily_basic_normalizes_historical_shares_to_shares():
    provider = GenericHTTPProvider(CustomSourceConfig(
        name="teajoin",
        display_name="TeaJoin",
        datasets={
            "financial": DatasetConfig(
                url="https://teajoin.example/financial",
                financial_url_template="https://teajoin.example/{table}",
                financial_table_map={"shares": "daily_basic"},
                field_map={"ts_code": "symbol"},
            ),
        },
    ))
    provider._request_rows = lambda _cfg, **_kwargs: [{
        "ts_code": "000001.SZ", "trade_date": "20260812",
        "total_share": 1940591.8198, "float_share": 1940560.0653,
    }]

    result = provider.get_financials("shares", ["000001.SZ"], latest_only=False)
    provider.close()

    assert result.to_dicts() == [{
        "symbol": "000001.SZ", "period_end": "20260812", "announce_date": "20260812",
        "total_shares": 19405918198.0, "float_shares": 19405600653.0,
    }]


def test_teajoin_shares_requests_one_symbol_per_call():
    provider = GenericHTTPProvider(CustomSourceConfig(
        name="teajoin",
        display_name="TeaJoin",
        datasets={
            "financial": DatasetConfig(
                url="https://teajoin.example/financial",
                batch=100,
                financial_table_map={"shares": "daily_basic"},
                field_map={"ts_code": "symbol"},
            ),
        },
    ))
    calls = []
    provider._request_rows = lambda _cfg, **kwargs: calls.append(kwargs["symbols"]) or []

    provider.get_financials("shares", ["000001.SZ", "600000.SH"], latest_only=False)
    provider.close()

    assert calls == [["000001.SZ"], ["600000.SH"]]


def test_teajoin_rejects_unconfigured_financial_table():
    provider = GenericHTTPProvider(CustomSourceConfig(
        name="teajoin",
        display_name="TeaJoin",
        datasets={
            "financial": DatasetConfig(
                url="https://teajoin.example/financial",
                financial_table_map={"income": "income"},
                field_map={"ts_code": "symbol"},
            ),
        },
    ))

    try:
        provider.get_financials("shares", ["000001.SZ"])
    except ValueError as exc:
        assert "shares" in str(exc)
    else:
        raise AssertionError("unconfigured financial table must fail closed")
    finally:
        provider.close()


def test_teajoin_request_contract_survives_settings_config_sanitization():
    cleaned = _sanitize_for_yaml({
        "name": "teajoin",
        "display_name": "TeaJoin",
        "auth": {"type": "body", "token_env": "TEAJOIN_API_KEY"},
        "datasets": {
            "instruments": {
                "url": "https://teajoin.example/stock_basic",
                "method": "POST",
                "response_path": "data",
            },
            "daily": {
                "url": "https://teajoin.example/daily",
                "method": "POST",
                "body": {"params": {}},
                "symbols_body_path": "params.ts_code",
                "start_body_path": "params.start_date",
                "end_body_path": "params.end_date",
                "date_only": True,
                "date_format": "%Y%m%d",
            },
            "adj_factor": {
                "url": "https://teajoin.example/adj_factor",
                "method": "POST",
                "adj_factor_kind": "cumulative",
            },
            "financial": {
                "url": "https://teajoin.example/financial",
                "method": "POST",
                "financial_url_template": "https://teajoin.example/{table}",
                "financial_table_map": {"metrics": "daily_basic"},
            },
        },
    })

    assert cleaned["datasets"]["instruments"]["url"].endswith("stock_basic")
    assert cleaned["datasets"]["daily"]["body"] == {"params": {}}
    assert cleaned["datasets"]["daily"]["start_body_path"] == "params.start_date"
    assert cleaned["datasets"]["daily"]["date_format"] == "%Y%m%d"
    assert cleaned["datasets"]["adj_factor"]["adj_factor_kind"] == "cumulative"
    assert cleaned["datasets"]["financial"]["financial_table_map"] == {"metrics": "daily_basic"}
