"""Configuration for the independent Vibe-Research news API adapter.

The adapter deliberately has no endpoint defaults.  A deployment must provide
the real URL and field mapping supplied by the operator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

NewsDatasetName = str


@dataclass(frozen=True)
class NewsAuthConfig:
    type: str = "none"
    token_env: str | None = None
    header: str = "Authorization"
    param: str = "token"


@dataclass(frozen=True)
class NewsEndpointConfig:
    url: str = ""
    method: str = "GET"
    response_path: str = ""
    field_map: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)
    symbols_param: str = "symbols"
    symbols_body_path: str = ""
    symbols_style: str = "list"
    category_param: str = "category"
    category_body_path: str = ""
    start_param: str = "start_time"
    start_body_path: str = ""
    end_param: str = "end_time"
    end_body_path: str = ""
    query_param: str = "query"
    query_body_path: str = ""
    limit_param: str = "limit"
    limit_body_path: str = ""
    cursor_param: str = "cursor"
    cursor_body_path: str = ""
    date_only: bool = False
    date_format: str = ""
    next_cursor_path: str = ""
    timeout: float = 30.0
    data_version: str = "v1"


@dataclass(frozen=True)
class VibePublicConfig:
    name: str = "vibe_public"
    display_name: str = "Vibe 资讯"
    enabled: bool = False
    auth: NewsAuthConfig = field(default_factory=NewsAuthConfig)
    datasets: dict[NewsDatasetName, NewsEndpointConfig] = field(default_factory=dict)
    path: Path | None = None

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.enabled:
            return errors
        for category, endpoint in self.datasets.items():
            if category not in {"announcement", "public_news"}:
                errors.append(f"{category}: unsupported news dataset")
            if not endpoint.url:
                errors.append(f"{category}: url is required")
            if endpoint.method not in {"GET", "POST"}:
                errors.append(f"{category}: method must be GET or POST")
            if endpoint.symbols_style not in {"list", "csv"}:
                errors.append(f"{category}: symbols_style must be list or csv")
            if not endpoint.field_map.get("title"):
                errors.append(f"{category}: field_map must provide title")
            if endpoint.timeout <= 0 or endpoint.timeout > 300:
                errors.append(f"{category}: timeout must be between 0 and 300 seconds")
        if self.auth.type not in {"none", "bearer", "header", "query", "body"}:
            errors.append(f"auth.type unsupported: {self.auth.type}")
        return errors


def _auth_from_dict(raw: dict[str, Any] | None) -> NewsAuthConfig:
    raw = raw or {}
    return NewsAuthConfig(
        type=str(raw.get("type", "none") or "none").lower(),
        token_env=str(raw.get("token_env") or "").strip() or None,
        header=str(raw.get("header", "Authorization") or "Authorization").strip(),
        param=str(raw.get("param", "token") or "token").strip(),
    )


def _endpoint_from_dict(raw: dict[str, Any]) -> NewsEndpointConfig:
    return NewsEndpointConfig(
        url=str(raw.get("url", "") or "").strip(),
        method=str(raw.get("method", "GET") or "GET").upper(),
        response_path=str(raw.get("response_path", "") or "").strip(),
        field_map={str(k): str(v) for k, v in (raw.get("field_map") or {}).items()},
        params=dict(raw.get("params") or {}),
        body=dict(raw.get("body") or {}),
        symbols_param=str(raw.get("symbols_param", "symbols") or "symbols").strip(),
        symbols_body_path=str(raw.get("symbols_body_path", "") or "").strip(),
        symbols_style=str(raw.get("symbols_style", "list") or "list").lower(),
        category_param=str(raw.get("category_param", "category") or "category").strip(),
        category_body_path=str(raw.get("category_body_path", "") or "").strip(),
        start_param=str(raw.get("start_param", "start_time") or "start_time").strip(),
        start_body_path=str(raw.get("start_body_path", "") or "").strip(),
        end_param=str(raw.get("end_param", "end_time") or "end_time").strip(),
        end_body_path=str(raw.get("end_body_path", "") or "").strip(),
        query_param=str(raw.get("query_param", "query") or "query").strip(),
        query_body_path=str(raw.get("query_body_path", "") or "").strip(),
        limit_param=str(raw.get("limit_param", "limit") or "limit").strip(),
        limit_body_path=str(raw.get("limit_body_path", "") or "").strip(),
        cursor_param=str(raw.get("cursor_param", "cursor") or "cursor").strip(),
        cursor_body_path=str(raw.get("cursor_body_path", "") or "").strip(),
        date_only=bool(raw.get("date_only", False)),
        date_format=str(raw.get("date_format", "") or "").strip(),
        next_cursor_path=str(raw.get("next_cursor_path", "") or "").strip(),
        timeout=float(raw.get("timeout", 30.0) or 30.0),
        data_version=str(raw.get("data_version", "v1") or "v1").strip() or "v1",
    )


def config_from_dict(raw: dict[str, Any], path: Path | None = None) -> VibePublicConfig:
    datasets = {
        str(name): _endpoint_from_dict(value)
        for name, value in (raw.get("datasets") or {}).items()
        if str(name) in {"announcement", "public_news"} and isinstance(value, dict)
    }
    default_name = path.stem if path else "vibe_public"
    return VibePublicConfig(
        name=str(raw.get("name", default_name) or default_name).lower(),
        display_name=str(raw.get("display_name", "Vibe 资讯") or "Vibe 资讯"),
        enabled=bool(raw.get("enabled", False)),
        auth=_auth_from_dict(raw.get("auth")),
        datasets=datasets,
        path=path,
    )


def load_config(path: Path) -> VibePublicConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("VibePublic config root must be an object")
    return config_from_dict(raw, path)
