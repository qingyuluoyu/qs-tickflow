"""Custom HTTP data source configuration."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

DatasetName = Literal["instruments", "daily", "adj_factor", "realtime", "minute", "financial"]
DEFAULT_TIMEOUT = 30.0
MAX_TIMEOUT = 300.0


@dataclass(frozen=True)
class AuthConfig:
    type: str = "none"
    token_env: str | None = None
    header: str = "Authorization"
    param: str = "token"


@dataclass(frozen=True)
class DatasetConfig:
    url: str
    method: str = "GET"
    batch: int | None = None
    rpm: int | None = None
    # Split long date ranges before requesting providers that reject large
    # multi-symbol payloads. ``None`` preserves the provider's original mode.
    range_window_days: int | None = None
    timeout: float = DEFAULT_TIMEOUT
    response_path: str = ""
    field_map: dict[str, str] = field(default_factory=dict)
    transforms: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)
    symbols_param: str = "symbols"
    start_param: str = "start_time"
    end_param: str = "end_time"
    asset_type_param: str | None = None
    freq_param: str | None = None
    # 财务表专用: 用 {table} 占位, 按 table 动态拼 URL (teajoin 等分端点财务源)。
    financial_url_template: str = ""
    financial_table_map: dict[str, str] = field(default_factory=dict)
    # 把 symbols 放到 body 的嵌套路径, 如 "params.ts_code" (teajoin 财务接口)。
    symbols_body_path: str = ""
    # 起止时间放到 body 的嵌套路径, 如 "params.start_date"。用于 TeaJoin
    # 这类不接受通用 start_time/end_time 顶层字段的上游。
    start_body_path: str = ""
    end_body_path: str = ""
    # 精确查询某个交易日时使用的嵌套路径, 如 "params.trade_date".
    trade_date_body_path: str = ""
    # 部分日频源严格要求 YYYY-MM-DD，不接受 ISO 时间戳。
    date_only: bool = False
    date_format: str = ""
    daily_url_by_asset_type: dict[str, str] = field(default_factory=dict)
    # ``event_ratio`` is the internal canonical form. Some providers expose a
    # cumulative adjustment factor instead and must be converted before it is
    # persisted, otherwise the indicator pipeline would multiply it repeatedly.
    adj_factor_kind: Literal["event_ratio", "cumulative"] = "event_ratio"
    instruments_url_by_asset_type: dict[str, str] = field(default_factory=dict)
    instruments_params_by_asset_type: dict[str, dict[str, Any]] = field(default_factory=dict)
    instruments_body_by_asset_type: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class CustomSourceConfig:
    name: str
    display_name: str
    auth: AuthConfig = field(default_factory=AuthConfig)
    datasets: dict[str, DatasetConfig] = field(default_factory=dict)
    fail_closed: bool = False
    path: Path | None = None

    def has_dataset(self, name: DatasetName) -> bool:
        return name in self.datasets


def _auth_from_dict(raw: dict[str, Any] | None) -> AuthConfig:
    raw = raw or {}
    return AuthConfig(
        type=str(raw.get("type", "none") or "none").lower(),
        token_env=raw.get("token_env"),
        header=str(raw.get("header", "Authorization") or "Authorization"),
        param=str(raw.get("param", "token") or "token"),
    )


def _dataset_from_dict(raw: dict[str, Any]) -> DatasetConfig:
    timeout_raw = raw.get("timeout")
    if timeout_raw is None:
        timeout = DEFAULT_TIMEOUT
    else:
        try:
            timeout = float(timeout_raw)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"timeout must be a number between 0 and {MAX_TIMEOUT:g} seconds"
            ) from e
        if not 0 < timeout <= MAX_TIMEOUT:
            raise ValueError(f"timeout must be between 0 and {MAX_TIMEOUT:g} seconds")

    adj_factor_kind = str(raw.get("adj_factor_kind", "event_ratio") or "event_ratio")
    if adj_factor_kind not in {"event_ratio", "cumulative"}:
        raise ValueError("adj_factor_kind must be 'event_ratio' or 'cumulative'")

    range_window_days = raw.get("range_window_days")
    if range_window_days is not None:
        try:
            range_window_days = int(range_window_days)
        except (TypeError, ValueError) as e:
            raise ValueError("range_window_days must be an integer between 1 and 365") from e
        if not 1 <= range_window_days <= 365:
            raise ValueError("range_window_days must be between 1 and 365")

    return DatasetConfig(
        url=str(raw.get("url", "") or ""),
        method=str(raw.get("method", "GET") or "GET").upper(),
        batch=int(raw["batch"]) if raw.get("batch") is not None else None,
        rpm=int(raw["rpm"]) if raw.get("rpm") is not None else None,
        range_window_days=range_window_days,
        timeout=timeout,
        response_path=str(raw.get("response_path", "") or ""),
        field_map={str(k): str(v) for k, v in (raw.get("field_map") or {}).items()},
        transforms={str(k): str(v) for k, v in (raw.get("transforms") or {}).items()},
        params=dict(raw.get("params") or {}),
        body=dict(raw.get("body") or {}),
        symbols_param=str(raw.get("symbols_param", "symbols") or "symbols").strip() or "symbols",
        start_param=str(raw.get("start_param", "start_time") or "start_time").strip() or "start_time",
        end_param=str(raw.get("end_param", "end_time") or "end_time").strip() or "end_time",
        asset_type_param=(str(raw.get("asset_type_param") or "").strip() or None),
        freq_param=(str(raw.get("freq_param") or "").strip() or None),
        financial_url_template=str(raw.get("financial_url_template", "") or ""),
        financial_table_map={str(k): str(v) for k, v in (raw.get("financial_table_map") or {}).items()},
        symbols_body_path=str(raw.get("symbols_body_path", "") or ""),
        start_body_path=str(raw.get("start_body_path", "") or ""),
        end_body_path=str(raw.get("end_body_path", "") or ""),
        trade_date_body_path=str(raw.get("trade_date_body_path", "") or ""),
        date_only=bool(raw.get("date_only", False)),
        date_format=str(raw.get("date_format", "") or ""),
        daily_url_by_asset_type={
            str(key): str(value)
            for key, value in (raw.get("daily_url_by_asset_type") or {}).items()
        },
        adj_factor_kind=adj_factor_kind,
        instruments_url_by_asset_type={
            str(key): str(value)
            for key, value in (raw.get("instruments_url_by_asset_type") or {}).items()
        },
        instruments_params_by_asset_type={
            str(key): dict(value)
            for key, value in (raw.get("instruments_params_by_asset_type") or {}).items()
            if isinstance(value, dict)
        },
        instruments_body_by_asset_type={
            str(key): dict(value)
            for key, value in (raw.get("instruments_body_by_asset_type") or {}).items()
            if isinstance(value, dict)
        },
    )


def config_from_dict(raw: dict[str, Any], path: Path | None = None) -> CustomSourceConfig:
    datasets = {
        name: _dataset_from_dict(cfg)
        for name, cfg in (raw.get("datasets") or {}).items()
        if name in {"instruments", "daily", "adj_factor", "realtime", "minute", "financial"} and isinstance(cfg, dict)
    }
    default_name = path.stem if path else "preview"
    name = str(raw.get("name", default_name) or default_name).lower()
    return CustomSourceConfig(
        name=name,
        display_name=str(raw.get("display_name", name) or name),
        auth=_auth_from_dict(raw.get("auth")),
        datasets=datasets,
        fail_closed=bool(raw.get("fail_closed", False)),
        path=path,
    )


def load_config(path: Path) -> CustomSourceConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return config_from_dict(raw, path)
