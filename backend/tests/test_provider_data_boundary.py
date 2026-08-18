"""Provider boundary tests for user-selected TeaJoin data."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import polars as pl

from app.services import kline_sync


def _daily_frame() -> pl.DataFrame:
    return pl.DataFrame({
        "symbol": ["000001.SZ"],
        "date": [datetime(2026, 8, 14).date()],
        "open": [11.1],
        "high": [11.2],
        "low": [11.0],
        "close": [11.1],
        "volume": [100.0],
        "amount": [1100.0],
    })


def _custom_provider(monkeypatch, provider, *, dataset: str):
    monkeypatch.setattr(kline_sync.preferences, "get_daily_data_provider", lambda: "teajoin")
    monkeypatch.setattr(kline_sync.preferences, "get_adj_factor_provider", lambda: "teajoin")
    monkeypatch.setattr(
        "app.data_providers.custom.provider_has_dataset",
        lambda name, current: name == "teajoin" and current == dataset,
    )
    monkeypatch.setattr(
        "app.data_providers.custom.get_provider",
        lambda name: provider,
    )


def test_sync_daily_batch_uses_selected_custom_provider(monkeypatch):
    provider = SimpleNamespace(
        config=SimpleNamespace(fail_closed=True),
        get_daily=MagicMock(return_value=_daily_frame()),
    )
    _custom_provider(monkeypatch, provider, dataset="daily")
    monkeypatch.setattr(kline_sync, "get_client", lambda: (_ for _ in ()).throw(
        AssertionError("selected TeaJoin daily data must not call TickFlow"),
    ))

    result = kline_sync.sync_daily_batch(
        ["000001.SZ"],
        start_time=datetime(2026, 8, 14),
        end_time=datetime(2026, 8, 15),
        asset_type="stock",
    )

    assert result.height == 1
    provider.get_daily.assert_called_once()


def test_sync_daily_batch_fail_closed_custom_error_does_not_use_tickflow(monkeypatch):
    provider = SimpleNamespace(
        config=SimpleNamespace(fail_closed=True),
        get_daily=MagicMock(side_effect=TimeoutError("TeaJoin unavailable")),
    )
    _custom_provider(monkeypatch, provider, dataset="daily")
    monkeypatch.setattr(kline_sync, "get_client", lambda: (_ for _ in ()).throw(
        AssertionError("fail-closed TeaJoin must not call TickFlow"),
    ))

    result = kline_sync.sync_daily_batch(["000001.SZ"], count=30)

    assert result.is_empty()


def test_fetch_adj_factor_single_uses_selected_custom_provider(monkeypatch):
    factors = pl.DataFrame({
        "symbol": ["000001.SZ"],
        "trade_date": [datetime(2026, 8, 14).date()],
        "ex_factor": [1.0],
    })
    provider = SimpleNamespace(
        config=SimpleNamespace(fail_closed=True),
        get_adj_factors=MagicMock(return_value=factors),
    )
    _custom_provider(monkeypatch, provider, dataset="adj_factor")
    monkeypatch.setattr(kline_sync, "get_client", lambda: (_ for _ in ()).throw(
        AssertionError("selected TeaJoin adjustment data must not call TickFlow"),
    ))

    result = kline_sync.fetch_adj_factor_single("000001.SZ")

    assert result.to_dicts() == factors.to_dicts()
    provider.get_adj_factors.assert_called_once()


def test_depth_service_does_not_use_tickflow_depth_with_custom_provider(monkeypatch):
    from app.services.depth_service import DepthService

    monkeypatch.setattr(
        "app.services.preferences.get_realtime_data_provider",
        lambda: "teajoin",
    )
    service = DepthService()
    service._get_capset = lambda: SimpleNamespace(has=lambda _cap: True)

    assert service._has_capability() is False
