"""Mapping helpers for custom data sources."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import polars as pl


def extract_rows(payload: Any, response_path: str = "") -> list[dict]:
    """Extract a list of row dicts from a JSON payload using dot-path lookup.

    兼容两种行格式:
    1. 标准: items 是 list[dict] (直接过滤 dict 项)。
    2. 二维表: payload 或 response_path 指向的节点是 dict, 且同时有
       `fields` (list[str]) 和 `items` (list[list]) —— 将 items 按 fields
       转成 list[dict] 返回 (teajoin 等接口)。
    """
    data = payload
    if response_path:
        for part in response_path.split("."):
            if not part:
                continue
            if isinstance(data, dict):
                data = data.get(part)
            else:
                data = None
                break
    if data is None:
        return []
    if isinstance(data, dict):
        # 二维表格式: {"fields": [...], "items": [[...], ...]}
        fields = data.get("fields")
        items = data.get("items")
        if isinstance(fields, list) and isinstance(items, list) and fields and items:
            # 检查 items 是否为 list[list] (二维表) 而非 list[dict]
            if items and isinstance(items[0], (list, tuple)):
                return [
                    {str(fields[i]): row[i] for i in range(min(len(fields), len(row)))}
                    for row in items
                ]
        # fields/items 是 TeaJoin 风格二维表。空表是合法的「无数据」，不能把
        # 容器对象伪装成一条数据行，否则上层会误报 rows=1 且列为空。
        if isinstance(fields, list) and isinstance(items, list):
            return []
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def map_rows(rows: list[dict], field_map: dict[str, str]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame()
    # Collect all keys across all rows to ensure consistent schema.
    all_keys = list(dict.fromkeys(k for row in rows for k in row.keys()))
    # Build normalized rows: missing keys → None, present keys → str(value)
    # Explicitly use pl.Utf8 schema to prevent Polars from inferring mixed types.
    schema = {k: pl.Utf8 for k in all_keys}
    normalized = []
    for row in rows:
        new_row = {}
        for k in all_keys:
            v = row.get(k)
            new_row[k] = str(v) if v is not None else None
        normalized.append(new_row)
    df = pl.DataFrame(normalized, schema=schema)
    rename = {src: dst for src, dst in field_map.items() if src in df.columns and src != dst}
    if rename:
        df = df.rename(rename)
    keep = list(dict.fromkeys(field_map.values()))
    keep = [col for col in keep if col in df.columns]
    return df.select(keep) if keep else pl.DataFrame()


def apply_transforms(df: pl.DataFrame, transforms: dict[str, str]) -> pl.DataFrame:
    """Apply a small safe transform set. No eval is used."""
    if df.is_empty() or not transforms:
        return df
    out = df
    for col, expr in transforms.items():
        if col not in out.columns:
            continue
        text = expr.strip()
        if text == "value * 100":
            out = out.with_columns((pl.col(col).cast(pl.Float64, strict=False) * 100).alias(col))
        elif text == "value * 1000":
            out = out.with_columns((pl.col(col).cast(pl.Float64, strict=False) * 1000).alias(col))
        elif text == "value / 100":
            out = out.with_columns((pl.col(col).cast(pl.Float64, strict=False) / 100).alias(col))
        elif text == "value / 10000":
            out = out.with_columns((pl.col(col).cast(pl.Float64, strict=False) / 10000).alias(col))
        elif text.startswith("parse_date("):
            fmt = _extract_format(text) or "%Y-%m-%d"
            out = out.with_columns(
                pl.col(col).cast(pl.Utf8, strict=False).str.strptime(pl.Date, format=fmt, strict=False).alias(col)
            )
        elif text.startswith("parse_datetime("):
            fmt = _extract_format(text) or "%Y-%m-%d %H:%M:%S"
            out = out.with_columns(
                pl.col(col).cast(pl.Utf8, strict=False).str.strptime(pl.Datetime, format=fmt, strict=False).alias(col)
            )
    return out


def _extract_format(expr: str) -> str | None:
    for quote in ("'", '"'):
        if quote in expr:
            parts = expr.split(quote)
            if len(parts) >= 3:
                return parts[1]
    return None


def datetime_payload(
    value: datetime | None,
    *,
    date_only: bool = False,
    date_format: str | None = None,
) -> str | None:
    # 日频 HTTP 源通常要求日期，不接受 Python 的 ISO T 分隔时间；分钟数据仍
    # 保留秒级时间。以零点 datetime 表示调用方请求日频数据。
    if value is None:
        return None
    if date_format:
        return value.strftime(date_format)
    if date_only or value.time().isoformat() == "00:00:00":
        return value.date().isoformat()
    return value.strftime("%Y-%m-%d %H:%M:%S")
