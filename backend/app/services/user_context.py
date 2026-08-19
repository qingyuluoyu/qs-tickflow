"""Request-scoped account context and personal data directory resolution.

Market data remains rooted at the shared repository directory. Personal files
use a mirrored ``data/users/<user_id>/`` workspace so existing service APIs can
continue receiving a data-root path without exposing another user's files.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class UserIdentity:
    id: str
    name: str
    phone: str
    role: str = "user"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


_current_user: ContextVar[UserIdentity | None] = ContextVar("tickflow_current_user", default=None)
_current_root: ContextVar[Path | None] = ContextVar("tickflow_current_user_root", default=None)


def set_current_user(user: UserIdentity, data_root: Path) -> tuple[Any, Any]:
    """Bind a user for the duration of one request/task."""
    return _current_user.set(user), _current_root.set(Path(data_root))


def reset_current_user(tokens: tuple[Any, Any]) -> None:
    user_token, root_token = tokens
    _current_root.reset(root_token)
    _current_user.reset(user_token)


def current_user() -> UserIdentity | None:
    return _current_user.get()


def personal_data_root(shared_root: Path) -> Path:
    """Return the active user's mirrored data root, or shared root outside requests."""
    return _current_root.get() or Path(shared_root)


def personal_user_data_dir(shared_root: Path) -> Path:
    """Return the active user's ``user_data`` directory and create it lazily."""
    path = personal_data_root(shared_root) / "user_data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def request_data_root(request, *, shared_root: Path | None = None) -> Path:
    """Resolve a request's personal root, with a safe shared fallback for tests."""
    root = getattr(getattr(request, "state", None), "user_data_root", None)
    if root is not None:
        return Path(root)
    if shared_root is not None:
        return Path(shared_root)
    repo = getattr(getattr(request, "app", None), "state", None)
    store = getattr(repo, "repo", None)
    data_store = getattr(store, "store", None)
    data_dir = getattr(data_store, "data_dir", None)
    if data_dir is None:
        raise RuntimeError("request data root is not initialized")
    return Path(data_dir)
