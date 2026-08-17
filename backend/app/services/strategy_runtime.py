"""Per-account strategy engine registry.

Built-in strategies are shared read-only code. User-authored strategy files and
overrides are loaded from the authenticated user's workspace, preventing one
account's custom strategy list from appearing in another account's screener.
"""
from __future__ import annotations

import threading
from pathlib import Path

from app.strategy import config as strategy_config
from app.strategy.engine import StrategyEngine

_lock = threading.RLock()


def get_user_strategy_engine(request) -> StrategyEngine:
    user = getattr(getattr(request, "state", None), "user", None)
    if user is None:
        engine = getattr(request.app.state, "strategy_engine", None)
        if engine is None:
            raise RuntimeError("strategy engine is not initialized")
        return engine
    root = Path(request.state.user_data_root)
    registry = getattr(request.app.state, "user_strategy_engines", None)
    if registry is None:
        registry = {}
        request.app.state.user_strategy_engines = registry
    with _lock:
        engine = registry.get(user.id)
        if engine is None:
            builtin = Path(__file__).resolve().parent.parent / "strategy" / "builtin"
            dirs = [builtin, *(root / "strategies" / source for source in ("custom", "ai", "composite"))]
            engine = StrategyEngine(
                strategy_dirs=dirs,
                override_loader=lambda sid, data_root=root: strategy_config.load_override(data_root, sid),
            )
            registry[user.id] = engine
        return engine


def invalidate_user_strategy_engine(request) -> None:
    user = getattr(getattr(request, "state", None), "user", None)
    registry = getattr(request.app.state, "user_strategy_engines", None)
    if not user or not registry:
        return
    with _lock:
        engine = registry.get(user.id)
        if engine is not None:
            engine.reload()
