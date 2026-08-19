"""Generic HTTP provider for custom market data sources."""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import polars as pl

from app.config import settings
from app.data_providers.base import AssetType
from app.data_providers.custom.config import CustomSourceConfig, DatasetConfig
from app.data_providers.custom.mapper import (
    apply_transforms,
    datetime_payload,
    extract_rows,
    map_rows,
)
from app.data_providers.normalizer import (
    normalize_adj_factors,
    normalize_daily,
    normalize_instruments,
)
from app.tickflow.rate_limits import chunked, sleep_between_batches

logger = logging.getLogger(__name__)


def _cumulative_factors_to_event_ratios(factors: pl.DataFrame) -> pl.DataFrame:
    """Convert provider cumulative factors to canonical per-event ratios.

    The first available date is a normalization baseline, so it is assigned
    ``1.0``. Later rows are the ratio to the previous cumulative value. This
    prevents applying a cumulative factor once per returned day in the
    indicator pipeline.
    """
    return (
        factors.sort(["symbol", "trade_date"])
        .unique(subset=["symbol", "trade_date"], keep="last")
        .sort(["symbol", "trade_date"])
        .with_columns(
            pl.when(pl.col("ex_factor").shift(1).over("symbol") > 0)
            .then(pl.col("ex_factor") / pl.col("ex_factor").shift(1).over("symbol"))
            .otherwise(1.0)
            .alias("ex_factor")
        )
    )


def _date_windows(
    start_time: datetime | None,
    end_time: datetime | None,
    range_window_days: int | None,
) -> list[tuple[datetime | None, datetime | None]]:
    """Return inclusive calendar-day windows without gaps or overlap."""
    if not start_time or not end_time or not range_window_days or start_time >= end_time:
        return [(start_time, end_time)]

    windows: list[tuple[datetime, datetime]] = []
    current_start = start_time
    while current_start <= end_time:
        current_end = min(
            current_start + timedelta(days=range_window_days - 1),
            end_time,
        )
        windows.append((current_start, current_end))
        current_start = current_end + timedelta(days=1)
    return windows


def _set_nested(d: dict[str, Any], path: str, value: Any) -> None:
    """按 dot-path 设置嵌套值, 如 _set_nested(body, "params.ts_code", val)。"""
    parts = path.split(".")
    for part in parts[:-1]:
        if part not in d or not isinstance(d[part], dict):
            d[part] = {}
        d = d[part]
    d[parts[-1]] = value

_REQUIRED = {
        "instruments": {"symbol", "code", "name"},
    "daily": {"symbol", "date", "open", "high", "low", "close", "volume", "amount"},
    "adj_factor": {"symbol", "trade_date", "ex_factor"},
    "realtime": {"symbol", "last_price", "prev_close", "open", "high", "low", "volume"},
    "minute": {"symbol", "datetime", "open", "high", "low", "close", "volume", "amount"},
    # financial 字段由数据源决定, 只要求能映射出 symbol
    "financial": {"symbol"},
}


class GenericHTTPProvider:
    """HTTP-backed custom source. It only handles fetching and schema mapping."""

    def __init__(self, config: CustomSourceConfig) -> None:
        self.config = config
        self.name = config.name
        self._client = httpx.Client(timeout=30.0)

    def close(self) -> None:
        self._client.close()

    def validate(self) -> list[str]:
        errors: list[str] = []
        for dataset, cfg in self.config.datasets.items():
            if not cfg.url:
                errors.append(f"{dataset}: url is required")
            required = _REQUIRED.get(dataset)
            if required:
                mapped = set(cfg.field_map.values())
                missing = sorted(required - mapped)
                if missing:
                    errors.append(f"{dataset}: missing mapped fields: {', '.join(missing)}")
            if dataset != "realtime":
                request_params = [cfg.symbols_param, cfg.start_param, cfg.end_param]
                if dataset == "minute":
                    request_params.extend(
                        name for name in (cfg.asset_type_param, cfg.freq_param) if name
                    )
                duplicates = sorted({
                    name for name in request_params if request_params.count(name) > 1
                })
                if duplicates:
                    errors.append(
                        f"{dataset}: duplicate request parameter names: "
                        f"{', '.join(duplicates)}"
                    )
        return errors

    def get_instruments(self, asset_type: AssetType = "stock") -> pl.DataFrame:
        cfg = self._dataset("instruments")
        rows = self._request_rows(
            cfg,
            override_params=cfg.instruments_params_by_asset_type.get(asset_type),
            override_body=cfg.instruments_body_by_asset_type.get(asset_type),
            override_url=cfg.instruments_url_by_asset_type.get(asset_type, cfg.url),
        )
        df = self._mapped_frame(cfg, rows)
        if df.is_empty():
            return pl.DataFrame()
        records = df.to_dicts()
        for record in records:
            symbol = str(record.get("symbol") or "")
            record.setdefault("code", symbol.split(".", 1)[0])
            record.setdefault("exchange", symbol.rsplit(".", 1)[-1] if "." in symbol else None)
        return normalize_instruments(records, asset_type=asset_type, source=self.name)

    def get_daily(
        self,
        symbols: list[str],
        start_time: datetime | None,
        end_time: datetime | None,
        asset_type: str = "stock",
        on_chunk_done=None,
    ) -> pl.DataFrame:
        cfg = self._dataset("daily")
        url = cfg.daily_url_by_asset_type.get(asset_type, cfg.url)
        frames: list[pl.DataFrame] = []
        chunks = chunked(symbols, cfg.batch)
        windows = _date_windows(start_time, end_time, cfg.range_window_days)
        total_requests = len(chunks) * len(windows)
        request_number = 0
        for window_start, window_end in windows:
            for chunk in chunks:
                sleep_between_batches(request_number, cfg.rpm)
                rows = self._request_rows(
                    cfg,
                    symbols=chunk,
                    start_time=window_start,
                    end_time=window_end,
                    override_url=url,
                )
                df = self._mapped_frame(cfg, rows)
                df = normalize_daily(df, source=self.name)
                if not df.is_empty():
                    frames.append(df)
                request_number += 1
                if on_chunk_done:
                    on_chunk_done(request_number, total_requests)
        return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()

    def get_latest_daily_snapshot(
        self,
        asset_type: AssetType = "stock",
        as_of: datetime | None = None,
    ) -> pl.DataFrame:
        """Fetch the provider's latest unfiltered daily market snapshot.

        This is intentionally separate from ``get_daily``: providers such as
        TeaJoin expose a bounded, full-market latest-day response when no
        symbol/date filter is supplied.  The dashboard can use that response
        without pretending that the locally persisted enriched partition is
        current.  When ``as_of`` is supplied, query the exact trading date
        first so a provider-side row limit cannot hide a newly published day;
        an empty exact-date response falls back to the latest unfiltered
        snapshot. No data is persisted by this method.
        """
        cfg = self._dataset("daily")
        url = cfg.daily_url_by_asset_type.get(asset_type, cfg.url)
        request_kwargs: dict[str, Any] = {"override_url": url}
        if as_of is not None:
            request_kwargs["trade_date"] = as_of
        rows = self._request_rows(cfg, **request_kwargs)
        if as_of is not None and not rows:
            rows = self._request_rows(cfg, override_url=url)
        df = self._mapped_frame(cfg, rows)
        if df.is_empty() or "date" not in df.columns:
            return pl.DataFrame()

        if df.schema["date"] != pl.Date:
            if cfg.date_format and df.schema["date"] == pl.Utf8:
                df = df.with_columns(
                    pl.col("date").str.strptime(
                        pl.Date, format=cfg.date_format, strict=False,
                    ).alias("date")
                )
            else:
                df = df.with_columns(pl.col("date").cast(pl.Date, strict=False))

        for column in (
            "open", "high", "low", "close", "prev_close", "change_pct",
            "change_amount", "volume", "amount", "turnover_rate",
        ):
            if column in df.columns:
                df = df.with_columns(
                    pl.col(column).cast(pl.Float64, strict=False).alias(column)
                )

        latest = df.get_column("date").drop_nulls().max()
        if latest is None:
            return pl.DataFrame()
        return df.filter(pl.col("date") == latest)

    def get_adj_factors(
        self,
        symbols: list[str],
        start_time: datetime | None,
        end_time: datetime | None,
        asset_type: str = "stock",  # noqa: ARG002
        on_chunk_done=None,
    ) -> pl.DataFrame:
        cfg = self._dataset("adj_factor")
        frames: list[pl.DataFrame] = []
        chunks = chunked(symbols, cfg.batch)
        windows = _date_windows(start_time, end_time, cfg.range_window_days)
        total_requests = len(chunks) * len(windows)
        request_number = 0
        for window_start, window_end in windows:
            for chunk in chunks:
                sleep_between_batches(request_number, cfg.rpm)
                rows = self._request_rows(
                    cfg,
                    symbols=chunk,
                    start_time=window_start,
                    end_time=window_end,
                )
                df = self._mapped_frame(cfg, rows)
                df = normalize_adj_factors(df, source=self.name)
                if not df.is_empty():
                    frames.append(df)
                request_number += 1
                if on_chunk_done:
                    on_chunk_done(request_number, total_requests)
        if not frames:
            return pl.DataFrame()
        factors = pl.concat(frames, how="diagonal_relaxed")
        if cfg.adj_factor_kind == "cumulative":
            factors = _cumulative_factors_to_event_ratios(factors)
        return factors

    def get_realtime(
        self,
        universes: list[str] | None = None,
        symbols: list[str] | None = None,
    ) -> list[dict]:
        if universes:
            raise ValueError(
                f"Custom data source '{self.name}' does not support realtime universes"
            )
        cfg = self._dataset("realtime")
        if symbols:
            rows = []
            for index, chunk in enumerate(chunked(symbols, cfg.batch)):
                sleep_between_batches(index, cfg.rpm)
                rows.extend(self._request_rows(cfg, symbols=chunk))
        else:
            rows = self._request_rows(cfg)
        df = self._mapped_frame(cfg, rows)
        if df.is_empty():
            return []
        return df.to_dicts()

    def get_minute(
        self,
        symbols: list[str],
        start_time: datetime | None,
        end_time: datetime | None,
        asset_type: AssetType = "stock",
        freq: str = "1m",
        on_chunk_done: Callable[[int, int], None] | None = None,
    ) -> pl.DataFrame:
        """拉取分钟 K。

        asset_type / freq 默认不传上游 (minute dataset URL 应返回 1m 数据)。
        在 dataset 配置中设置 asset_type_param / freq_param 后, 这两个参数会以
        配置的参数名注入请求 (GET → params, POST → body), 用于上游需区分
        stock/ETF/index 或固定频率的场景。
        """
        cfg = self._dataset("minute")
        override: dict[str, Any] = {}
        if cfg.asset_type_param:
            override[cfg.asset_type_param] = asset_type
        if cfg.freq_param:
            override[cfg.freq_param] = freq
        frames: list[pl.DataFrame] = []
        chunks = chunked(symbols, cfg.batch)
        for i, chunk in enumerate(chunks):
            sleep_between_batches(i, cfg.rpm)
            rows = self._request_rows(
                cfg, symbols=chunk, start_time=start_time, end_time=end_time,
                override_params=override or None, override_body=override or None,
            )
            df = self._mapped_frame(cfg, rows)
            df = self._normalize_minute(df)
            if not df.is_empty():
                frames.append(df)
            if on_chunk_done:
                on_chunk_done(i + 1, len(chunks))
        return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()

    def get_financials(
        self,
        table: str,
        symbols: list[str],
        latest_only: bool = True,
    ) -> pl.DataFrame:
        """拉取财务数据。table 包含四张财务报表及 shares 股本表。

        custom 源用一个 'financial' dataset 配置覆盖全部财务表; 请求时把 table 作为参数传给上游,
        上游根据 table 返回对应数据。字段由数据源决定, 这里只确保有 symbol 列。
        """
        cfg = self._dataset("financial")
        if cfg.financial_table_map and table not in cfg.financial_table_map:
            raise ValueError(
                f"Custom data source '{self.name}' does not configure financial table '{table}'"
            )
        frames: list[pl.DataFrame] = []
        chunks = chunked(symbols, 1 if table == "shares" else cfg.batch)
        for i, chunk in enumerate(chunks):
            sleep_between_batches(i, cfg.rpm)
            # 支持 financial_url_template: 按 table 动态拼 URL (teajoin 分端点模式)
            upstream_table = cfg.financial_table_map.get(table, table)
            url = cfg.url
            if cfg.financial_url_template:
                url = cfg.financial_url_template.replace("{table}", upstream_table)
            # 把 table 注入到请求参数 (上游据此区分财务表)
            extra_params = {**cfg.params, "table": upstream_table}
            extra_body = {**cfg.body, "table": upstream_table}
            if table == "shares":
                extra_params["latest"] = latest_only
                extra_body["latest"] = latest_only
            rows = self._request_rows(
                cfg, symbols=chunk,
                override_params=extra_params, override_body=extra_body,
                override_url=url or None,
            )
            # 财务三表字段彼此不同。只应用证券代码别名并保留 TeaJoin 返回的
            # 全部字段，不能复用某一张表的 field_map 而截断资产负债表或现金流。
            # TeaJoin 同一财务列可能跨报告期混用 JSON number / string。先统一成
            # Utf8，保留原始可追溯值，避免 Polars schema 推断因批次顺序失败。
            if rows:
                columns = list(dict.fromkeys(key for row in rows for key in row))
                df = pl.DataFrame(
                    [
                        {key: (None if row.get(key) is None else str(row.get(key))) for key in columns}
                        for row in rows
                    ],
                    schema={key: pl.Utf8 for key in columns},
                )
            else:
                df = pl.DataFrame()
            if "ts_code" in df.columns and "symbol" not in df.columns:
                df = df.rename({"ts_code": "symbol"})
            if "symbol" in df.columns:
                df = df.with_columns(pl.col("symbol").cast(pl.Utf8, strict=False))
            identity_columns = {"symbol", "ann_date", "f_ann_date", "end_date", "trade_date"}
            numeric_columns = [column for column in df.columns if column not in identity_columns]
            if numeric_columns:
                df = df.with_columns(
                    [pl.col(column).cast(pl.Float64, strict=False).alias(column) for column in numeric_columns]
                )
            if not df.is_empty():
                frames.append(df)
        if not frames:
            return pl.DataFrame()
        result = pl.concat(frames, how="diagonal_relaxed")
        if table != "shares":
            return result
        required = {"symbol", "trade_date", "total_share", "float_share"}
        if not required <= set(result.columns):
            raise ValueError(
                f"Custom data source '{self.name}' returned invalid shares fields"
            )
        return result.select([
            pl.col("symbol"),
            pl.col("trade_date").alias("period_end"),
            pl.col("trade_date").alias("announce_date"),
            (pl.col("total_share") * 10_000.0).alias("total_shares"),
            (pl.col("float_share") * 10_000.0).alias("float_shares"),
        ])

    @staticmethod
    def _normalize_minute(df: pl.DataFrame) -> pl.DataFrame:
        """把映射后的 df 规范成 minute canonical 列。"""
        if df.is_empty():
            return df
        if "datetime" in df.columns:
            dt_type = df.schema["datetime"]
            if dt_type == pl.String:
                # TeaJoin returns ``YYYY-MM-DD HH:MM:SS`` strings.  A direct
                # cast to Datetime silently turns these valid rows into nulls.
                df = df.with_columns(
                    pl.col("datetime").str.to_datetime(strict=False).alias("datetime"),
                )
            elif not isinstance(dt_type, pl.Datetime) or dt_type.time_unit != "us":
                df = df.with_columns(
                    pl.col("datetime").cast(pl.Datetime("us"), strict=False),
                )
            # Invalid timestamps must not enter the canonical minute table.
            df = df.filter(pl.col("datetime").is_not_null())
        for col in ("open", "high", "low", "close", "volume", "amount"):
            if col in df.columns:
                df = df.with_columns(pl.col(col).cast(pl.Float64, strict=False))
        keep = [c for c in ("symbol", "datetime", "open", "high", "low", "close", "volume", "amount") if c in df.columns]
        return df.select(keep) if keep else pl.DataFrame()

    def test_dataset(self, dataset: str, symbols: list[str] | None = None) -> dict:
        cfg = self._dataset(dataset)
        test_symbols = symbols or ["000001.SZ"]
        end_time = datetime.now()
        start_time = end_time - timedelta(days=7)
        if dataset == "realtime":
            rows = self._request_rows(cfg)
        elif dataset == "minute":
            override: dict[str, Any] = {}
            if cfg.asset_type_param:
                override[cfg.asset_type_param] = "stock"
            if cfg.freq_param:
                override[cfg.freq_param] = "1m"
            rows = self._request_rows(
                cfg,
                symbols=test_symbols,
                start_time=start_time,
                end_time=end_time,
                override_params=override or None,
                override_body=override or None,
            )
        elif dataset in {"daily", "adj_factor"}:
            rows = self._request_rows(
                cfg,
                symbols=test_symbols,
                start_time=start_time,
                end_time=end_time,
            )
        elif dataset == "financial":
            df = self.get_financials("metrics", test_symbols, latest_only=True)
            return {
                "provider": self.name,
                "dataset": dataset,
                "rows": df.height,
                "columns": df.columns,
                "preview": df.head(5).to_dicts() if not df.is_empty() else [],
            }
        else:
            rows = self._request_rows(cfg, symbols=test_symbols)
        df = self._mapped_frame(cfg, rows)
        return {
            "provider": self.name,
            "dataset": dataset,
            "rows": len(rows),
            "columns": df.columns,
            "preview": df.head(5).to_dicts() if not df.is_empty() else [],
        }

    def _dataset(self, name: str) -> DatasetConfig:
        cfg = self.config.datasets.get(name)
        if not cfg:
            raise ValueError(f"Custom data source '{self.name}' does not configure dataset '{name}'")
        return cfg

    def _mapped_frame(self, cfg: DatasetConfig, rows: list[dict]) -> pl.DataFrame:
        df = map_rows(rows, cfg.field_map)
        return apply_transforms(df, cfg.transforms)

    def _request_rows(
        self,
        cfg: DatasetConfig,
        *,
        symbols: list[str] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        trade_date: datetime | None = None,
        override_params: dict[str, Any] | None = None,
        override_body: dict[str, Any] | None = None,
        override_url: str | None = None,
    ) -> list[dict]:
        headers, auth_params = self._auth_parts()
        params = dict(cfg.params)
        params.update(auth_params)
        if override_params:
            params.update(override_params)
        body = dict(cfg.body)
        if override_body:
            body.update(override_body)
        # body auth: inject token into POST JSON body
        body_auth_token = auth_params.pop("_body_auth_token", None)
        if body_auth_token and cfg.method.upper() != "GET":
            body.setdefault("token", body_auth_token)
        if symbols:
            symbols_value = ",".join(symbols)
            if cfg.symbols_body_path:
                # 支持嵌套路径, 如 "params.ts_code" —— 以逗号分隔字符串写入 (teajoin 等接口)。
                _set_nested(body, cfg.symbols_body_path, symbols_value)
            else:
                body[cfg.symbols_param] = symbols
            if not cfg.symbols_body_path:
                params.setdefault(cfg.symbols_param, symbols_value)
        start_value = datetime_payload(
            start_time, date_only=cfg.date_only, date_format=cfg.date_format or None,
        )
        end_value = datetime_payload(
            end_time, date_only=cfg.date_only, date_format=cfg.date_format or None,
        )
        if start_value:
            if cfg.start_body_path:
                _set_nested(body, cfg.start_body_path, start_value)
            else:
                body[cfg.start_param] = start_value
                params.setdefault(cfg.start_param, start_value)
        if end_value:
            if cfg.end_body_path:
                _set_nested(body, cfg.end_body_path, end_value)
            else:
                body[cfg.end_param] = end_value
                params.setdefault(cfg.end_param, end_value)

        trade_date_value = datetime_payload(
            trade_date,
            date_only=True,
            date_format=cfg.date_format or None,
        )
        if trade_date_value:
            if cfg.trade_date_body_path:
                _set_nested(body, cfg.trade_date_body_path, trade_date_value)
            elif cfg.method.upper() == "GET":
                params.setdefault("trade_date", trade_date_value)
            else:
                body.setdefault("trade_date", trade_date_value)

        method = cfg.method.upper()
        request_kwargs: dict[str, Any] = {"headers": headers, "timeout": cfg.timeout}
        if method == "GET":
            request_kwargs["params"] = params
        else:
            request_kwargs["params"] = auth_params
            request_kwargs["json"] = body
        url = override_url or cfg.url
        for attempt in range(3):
            try:
                resp = self._client.request(method, url, **request_kwargs)
                break
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == 2:
                    raise
                delay = 0.5 * (attempt + 1)
                logger.warning(
                    "custom data source %s transient request failure (%s); retry %d/2 in %.1fs",
                    self.name,
                    type(exc).__name__,
                    attempt + 1,
                    delay,
                )
                time.sleep(delay)
        resp.raise_for_status()
        return extract_rows(resp.json(), cfg.response_path)

    def _auth_parts(self) -> tuple[dict[str, str], dict[str, str]]:
        auth = self.config.auth
        if auth.type == "none":
            return {}, {}
        token = _token_from_env(auth.token_env) if auth.token_env else None
        if not token:
            logger.warning("custom data source %s auth token is not set", self.name)
            return {}, {}
        if auth.type == "bearer":
            return {auth.header: f"Bearer {token}"}, {}
        if auth.type == "header":
            return {auth.header: token}, {}
        if auth.type == "query":
            return {}, {auth.param: token}
        if auth.type == "body":
            # token injected into POST JSON body by _request_rows
            return {}, {"_body_auth_token": token}
        return {}, {}


def _token_from_env(name: str | None) -> str | None:
    if not name:
        return None
    token = os.getenv(name)
    if token:
        return token
    # Deployment convenience without putting credentials in source control:
    # a private data directory can carry one token file per environment name.
    # Environment variables remain the highest-priority source. Never log the
    # token or the file contents.
    for path in (
        settings.data_dir / "private" / name,
        settings.data_dir / "secrets" / name,
        settings.data_dir / f".{name}",
    ):
        try:
            if path.is_file():
                value = path.read_text(encoding="utf-8").strip()
                if value:
                    return value[:4096]
        except OSError:
            continue
    candidates = [settings.data_dir.parent / ".env", Path.cwd() / ".env", Path.cwd().parent / ".env"]
    env_path = next((path for path in candidates if path.exists()), None)
    if env_path is None:
        return None
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, value = text.split("=", 1)
            if key.strip() == name:
                return value.strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001
        return None
    return None
