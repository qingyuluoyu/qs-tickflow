"""Server-scoped runtime preferences.

Provider selection and background refresh settings describe the running
service, not an authenticated user's private workspace.  This module keeps
those values outside the request-scoped ``preferences.json`` while preserving
an explicit one-time migration path for older single-user installations.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_FILENAME = "server_config.json"
_lock = threading.RLock()


def _path() -> Path:
    return Path(settings.data_dir) / _FILENAME


def load() -> dict[str, Any]:
    path = _path()
    with _lock:
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("server_config.json malformed: %s", path)
            return {}
    return value if isinstance(value, dict) else {}


def save(updates: dict[str, Any]) -> dict[str, Any]:
    """Merge updates using an atomic same-directory replacement."""
    if not isinstance(updates, dict):
        raise TypeError("updates must be a dict")
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        current = load()
        current.update(updates)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(current, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary)
    return current


def get_provider(dataset: str, default: str = "tickflow") -> str:
    key = f"{dataset}_data_provider"
    values = load()
    # Before server_config.json exists, read only the old shared file. Do not
    # call request-scoped preferences.load() from a background thread.
    value = values[key] if key in values else _legacy_load().get(key, default)
    return str(value or default).lower()


def get(key: str, default: Any = None) -> Any:
    """Read a server value with a legacy shared-file fallback."""
    values = load()
    return values[key] if key in values else _legacy_load().get(key, default)


def get_quote_interval(default: float = 6.0) -> float:
    values = load()
    value = values.get("realtime_quote_interval")
    if value is None:
        value = _legacy_load().get("realtime_quote_interval", default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def get_financial_schedule(default: dict[str, Any] | None = None) -> dict[str, Any]:
    fallback = dict(default or {"enabled": False, "interval_days": 7})
    value = load().get("financial_schedule")
    return dict(value) if isinstance(value, dict) else fallback


def migrate_legacy() -> bool:
    """Copy only server-level keys from the old shared preferences once."""
    path = _path()
    if path.exists():
        return False
    legacy = Path(settings.data_dir) / "user_data" / "preferences.json"
    if not legacy.exists():
        return False
    legacy_values = _legacy_load()
    keys = {
        "daily_data_provider",
        "adj_factor_provider",
        "minute_data_provider",
        "realtime_data_provider",
        "financial_data_provider",
        "realtime_quote_interval",
    }
    updates = {key: legacy_values[key] for key in keys if key in legacy_values}
    if not updates:
        return False
    save(updates)
    logger.info("migrated %d server preference keys from legacy preferences", len(updates))
    return True


def _legacy_load() -> dict[str, Any]:
    path = Path(settings.data_dir) / "user_data" / "preferences.json"
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("legacy preferences migration skipped: %s", path)
        return {}
    return value if isinstance(value, dict) else {}
