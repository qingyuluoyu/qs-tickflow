from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth, strategy
from app.api import settings as settings_api
from app.config import settings
from app.main import auth_middleware
from app.services.account_store import get_account_store
from app.services.user_context import reset_current_user, set_current_user


def _master_key() -> str:
    return base64.urlsafe_b64encode(b"1" * 32).decode("ascii")


def _test_app(data_dir: Path) -> FastAPI:
    app = FastAPI()
    app.middleware("http")(auth_middleware)
    app.include_router(auth.router)
    app.include_router(settings_api.router)
    app.state.repo = SimpleNamespace(store=SimpleNamespace(data_dir=data_dir))
    app.state.account_directory = None
    return app


def _enter(client: TestClient, *, name: str, phone: str) -> None:
    response = client.post(
        "/api/auth/entry",
        json={"name": name, "phone": phone, "password": f"{phone}-password"},
    )
    assert response.status_code == 200


def test_custom_ai_settings_are_private_and_server_default_is_not_mutated(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "user_secrets_master_key", _master_key(), raising=False)
    monkeypatch.setattr(settings, "ai_provider", "openai_compat")
    monkeypatch.setattr(settings, "ai_base_url", "https://server.example/v1")
    monkeypatch.setattr(settings, "ai_api_key", "server-api-key")
    monkeypatch.setattr(settings, "ai_model", "server-model")
    app = _test_app(tmp_path)

    with TestClient(app) as alice, TestClient(app) as bob:
        _enter(alice, name="Alice", phone="alice-phone")
        _enter(bob, name="Bob", phone="bob-phone")

        saved = alice.post(
            "/api/settings/ai",
            json={
                "provider": "openai_compat",
                "base_url": "https://8.8.8.8/v1",
                "api_key": "alice-private-key",
                "model": "alice-model",
                "user_agent": "Alice Agent",
            },
        )
        assert saved.status_code == 200
        assert saved.json()["ai_source"] == "user_override"
        assert saved.json()["ai_model"] == "alice-model"

        alice_settings = alice.get("/api/settings")
        bob_settings = bob.get("/api/settings")
        assert alice_settings.status_code == 200
        assert bob_settings.status_code == 200
        assert alice_settings.json()["ai_source"] == "user_override"
        assert alice_settings.json()["ai_model"] == "alice-model"
        assert bob_settings.json()["ai_source"] == "server_default"
        assert bob_settings.json()["ai_model"] == "server-model"
        assert bob_settings.json()["ai_api_key_masked"] == ""
        assert settings.ai_model == "server-model"

        store = get_account_store(tmp_path)
        alice_id = store.list_active_identities()[0]
        bob_id = store.list_active_identities()[1]
        tokens = set_current_user(alice_id, store.workspace(alice_id.id))
        try:
            assert strategy.ai_status(SimpleNamespace())["has_key"] is True
        finally:
            reset_current_user(tokens)
        tokens = set_current_user(bob_id, store.workspace(bob_id.id))
        try:
            assert strategy.ai_status(SimpleNamespace())["has_key"] is False
        finally:
            reset_current_user(tokens)


def test_only_the_owner_can_clear_its_ai_override(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "user_secrets_master_key", _master_key(), raising=False)
    monkeypatch.setattr(settings, "ai_api_key", "server-api-key")
    monkeypatch.setattr(settings, "ai_model", "server-model")
    app = _test_app(tmp_path)

    with TestClient(app) as alice, TestClient(app) as bob:
        _enter(alice, name="Alice", phone="alice-phone")
        _enter(bob, name="Bob", phone="bob-phone")
        assert alice.post(
            "/api/settings/ai",
            json={
                "provider": "openai_compat",
                "base_url": "https://8.8.8.8/v1",
                "api_key": "alice-private-key",
                "model": "alice-model",
            },
        ).status_code == 200

        cleared = alice.delete("/api/settings/ai")
        assert cleared.status_code == 200
        assert cleared.json()["ai_source"] == "server_default"
        assert bob.get("/api/settings").json()["ai_source"] == "server_default"
