"""Process-local registry for the Vibe-Research news providers."""
from __future__ import annotations

import logging
from pathlib import Path

from app.config import settings
from app.data_providers.vibe_public_config import load_config
from app.data_providers.vibe_public_provider import VibePublicProvider
from app.data_providers.vibe_research_provider import VibeResearchProvider

logger = logging.getLogger(__name__)

_PROVIDER: VibePublicProvider | VibeResearchProvider | None = None
_ERRORS: list[dict[str, str]] = []
_LOADED = False


def config_path() -> Path:
    return settings.data_dir / "data_sources" / "vibe_public.yaml"


def load(path: Path | None = None) -> None:
    """Load an operator API config or the original Vibe public source adapter.

    The original Vibe-Research project already ships the Eastmoney public
    announcement/news implementation and this repository contains its
    maintained port under ``app.services.stock_insight``.  Use that source
    when no operator config exists; an explicitly present disabled config still
    turns the feature off, and an invalid config never silently falls back.
    """
    global _PROVIDER, _ERRORS, _LOADED
    if _PROVIDER is not None:
        _PROVIDER.close()
    _PROVIDER = None
    _ERRORS = []
    _LOADED = True

    selected = path or config_path()
    if not selected.exists():
        _PROVIDER = VibeResearchProvider()
        logger.info("Vibe-Research built-in public news provider enabled")
        return
    try:
        config = load_config(selected)
        provider = VibePublicProvider(config)
        errors = provider.validate()
        if errors:
            _ERRORS = [{"path": str(selected), "message": error} for error in errors]
            provider.close()
            return
        if not config.enabled or not config.datasets:
            provider.close()
            return
        _PROVIDER = provider
    except Exception as exc:
        logger.warning("VibePublic news provider load failed: %s", exc)
        _ERRORS = [{"path": str(selected), "message": str(exc)}]


def get_provider(*, reload: bool = False) -> VibePublicProvider | None:
    if reload or not _LOADED:
        load()
    return _PROVIDER


def errors() -> list[dict[str, str]]:
    return list(_ERRORS)


def status() -> dict[str, object]:
    provider = get_provider()
    return {
        "configured": provider is not None,
        "name": provider.name if provider else None,
        "capabilities": {"news": bool(provider and provider.capabilities.news)},
        "errors": errors(),
    }


def close() -> None:
    global _PROVIDER, _LOADED
    if _PROVIDER is not None:
        _PROVIDER.close()
    _PROVIDER = None
    _LOADED = False
