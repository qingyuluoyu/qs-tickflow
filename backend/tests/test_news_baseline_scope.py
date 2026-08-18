from __future__ import annotations

from pathlib import Path

from app.data_providers.base import ProviderCapabilities
from app.services.user_context import (
    UserIdentity,
    current_user,
    reset_current_user,
    set_current_user,
)


def test_news_capability_does_not_grant_market_data_capabilities():
    capabilities = ProviderCapabilities(news=True)

    assert capabilities.news is True
    assert capabilities.daily is False
    assert capabilities.realtime is False
    assert capabilities.financial is False


def test_auth_context_is_reset_after_background_user_job(tmp_path: Path):
    user = UserIdentity(id="alice", name="Alice", phone="13800000000")
    tokens = set_current_user(user, tmp_path / "users" / "alice")
    try:
        assert current_user() == user
    finally:
        reset_current_user(tokens)

    assert current_user() is None
