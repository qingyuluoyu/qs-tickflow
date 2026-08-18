from __future__ import annotations

import base64
import sqlite3
from pathlib import Path

from app.config import settings
from app.services.account_store import get_account_store
from app.services.user_context import reset_current_user, set_current_user


def _master_key() -> str:
    return base64.urlsafe_b64encode(b"0" * 32).decode("ascii")


def _create_user(data_dir: Path, *, name: str, phone: str):
    store = get_account_store(data_dir)
    result = store.enter(name, phone, f"{phone}-password")
    assert result is not None
    return result.user


def _bind(user, data_dir: Path):
    return set_current_user(user, get_account_store(data_dir).workspace(user.id))


def test_each_user_resolves_only_its_own_ai_override(monkeypatch, tmp_path: Path):
    from app.services import ai_profiles

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "user_secrets_master_key", _master_key(), raising=False)
    monkeypatch.setattr(settings, "ai_provider", "openai_compat")
    monkeypatch.setattr(settings, "ai_base_url", "https://server.example/v1")
    monkeypatch.setattr(settings, "ai_api_key", "server-api-key")
    monkeypatch.setattr(settings, "ai_model", "server-model")

    alice = _create_user(tmp_path, name="Alice", phone="alice-phone")
    bob = _create_user(tmp_path, name="Bob", phone="bob-phone")

    alice_tokens = _bind(alice, tmp_path)
    try:
        ai_profiles.save_current_override(
            provider="openai_compat",
            base_url="https://8.8.8.8/v1",
            api_key="alice-private-key",
            model="alice-model",
            user_agent="Alice Agent",
        )
        alice_profile = ai_profiles.resolve_current_profile()
    finally:
        reset_current_user(alice_tokens)

    bob_tokens = _bind(bob, tmp_path)
    try:
        bob_profile = ai_profiles.resolve_current_profile()
    finally:
        reset_current_user(bob_tokens)

    assert alice_profile.source == "user_override"
    assert alice_profile.model == "alice-model"
    assert alice_profile.api_key == "alice-private-key"
    assert bob_profile.source == "server_default"
    assert bob_profile.model == "server-model"
    assert bob_profile.api_key == "server-api-key"


def test_user_api_key_is_encrypted_in_the_account_database(monkeypatch, tmp_path: Path):
    from app.services import ai_profiles

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "user_secrets_master_key", _master_key(), raising=False)
    user = _create_user(tmp_path, name="Alice", phone="alice-phone")

    tokens = _bind(user, tmp_path)
    try:
        ai_profiles.save_current_override(
            provider="openai_compat",
            base_url="https://8.8.8.8/v1",
            api_key="never-store-me-in-plaintext",
            model="alice-model",
            user_agent="",
        )
    finally:
        reset_current_user(tokens)

    with sqlite3.connect(tmp_path / "accounts.sqlite3") as conn:
        stored = conn.execute(
            "SELECT encrypted_api_key FROM user_ai_profiles WHERE user_id = ?", (user.id,)
        ).fetchone()[0]

    assert stored != "never-store-me-in-plaintext"
    assert b"never-store-me-in-plaintext" not in bytes(stored)


def test_clearing_an_override_returns_only_that_user_to_server_default(monkeypatch, tmp_path: Path):
    from app.services import ai_profiles

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "user_secrets_master_key", _master_key(), raising=False)
    monkeypatch.setattr(settings, "ai_api_key", "server-api-key")
    monkeypatch.setattr(settings, "ai_model", "server-model")
    user = _create_user(tmp_path, name="Alice", phone="alice-phone")

    tokens = _bind(user, tmp_path)
    try:
        ai_profiles.save_current_override(
            provider="openai_compat",
            base_url="https://8.8.8.8/v1",
            api_key="alice-private-key",
            model="alice-model",
            user_agent="",
        )
        ai_profiles.clear_current_override()
        profile = ai_profiles.resolve_current_profile()
    finally:
        reset_current_user(tokens)

    assert profile.source == "server_default"
    assert profile.model == "server-model"


def test_legacy_personal_ai_configuration_is_copied_once_to_the_encrypted_store(monkeypatch, tmp_path: Path):
    from app import secrets_store
    from app.services import ai_profiles

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "user_secrets_master_key", _master_key(), raising=False)
    monkeypatch.setattr(settings, "ai_api_key", "server-api-key")
    monkeypatch.setattr(settings, "ai_model", "server-model")
    user = _create_user(tmp_path, name="Alice", phone="alice-phone")

    tokens = _bind(user, tmp_path)
    try:
        secrets_store.save({
            "ai_provider": "openai_compat",
            "ai_base_url": "https://8.8.8.8/v1",
            "ai_api_key": "legacy-private-key",
            "ai_model": "legacy-model",
        })
        profile = ai_profiles.resolve_current_profile()
    finally:
        reset_current_user(tokens)

    assert profile.source == "user_override"
    assert profile.model == "legacy-model"
    assert profile.api_key == "legacy-private-key"


def test_clearing_override_with_legacy_config_does_not_resurrect(monkeypatch, tmp_path: Path):
    """显式删除个人覆盖后, 旧版 secrets.json 不得在下次读取时复活覆盖配置。"""
    from app import secrets_store
    from app.services import ai_profiles

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "user_secrets_master_key", _master_key(), raising=False)
    monkeypatch.setattr(settings, "ai_api_key", "server-api-key")
    monkeypatch.setattr(settings, "ai_model", "server-model")
    user = _create_user(tmp_path, name="Alice", phone="alice-phone")

    tokens = _bind(user, tmp_path)
    try:
        secrets_store.save({
            "ai_provider": "openai_compat",
            "ai_base_url": "https://8.8.8.8/v1",
            "ai_api_key": "legacy-private-key",
            "ai_model": "legacy-model",
        })
        assert ai_profiles.resolve_current_profile().source == "user_override"

        ai_profiles.clear_current_override()

        assert ai_profiles.resolve_current_profile().source == "server_default"
        assert not ai_profiles.has_current_override()
    finally:
        reset_current_user(tokens)


def test_updating_a_personal_model_without_a_new_key_preserves_its_encrypted_key(monkeypatch, tmp_path: Path):
    from app.services import ai_profiles

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "user_secrets_master_key", _master_key(), raising=False)
    user = _create_user(tmp_path, name="Alice", phone="alice-phone")

    tokens = _bind(user, tmp_path)
    try:
        ai_profiles.save_current_override(
            provider="openai_compat",
            base_url="https://8.8.8.8/v1",
            api_key="alice-private-key",
            model="old-model",
            user_agent="",
        )
        profile = ai_profiles.save_current_override(
            provider="openai_compat",
            base_url="https://8.8.8.8/v1",
            api_key="",
            model="new-model",
            user_agent="",
        )
    finally:
        reset_current_user(tokens)

    assert profile.model == "new-model"
    assert profile.api_key == "alice-private-key"


def test_private_network_hostnames_are_rejected_for_personal_ai_endpoints(monkeypatch):
    import ipaddress

    import pytest

    from app.services import ai_profiles

    monkeypatch.setattr(
        ai_profiles,
        "_resolve_public_addresses",
        lambda _host, _port: [ipaddress.ip_address("127.0.0.1")],
        raising=False,
    )

    with pytest.raises(ValueError, match="私有网络"):
        ai_profiles._validate_user_base_url("https://ai.example/v1")
