from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api import auth
from app.config import settings


def _request(*, scheme: str = "http", forwarded_proto: str = "", client_host: str = "127.0.0.1") -> Request:
    headers = []
    if forwarded_proto:
        headers.append((b"x-forwarded-proto", forwarded_proto.encode()))
    return Request({
        "type": "http",
        "scheme": scheme,
        "path": "/api/auth/entry",
        "raw_path": b"/api/auth/entry",
        "query_string": b"",
        "headers": headers,
        "client": (client_host, 1234),
        "server": ("localhost", 3018),
    })


def test_auth_cookie_is_secure_for_https_and_trusted_forwarded_https():
    assert auth._is_https(_request(scheme="https")) is True
    assert auth._is_https(_request(forwarded_proto="https")) is True
    assert auth._is_https(_request()) is False
    assert auth._is_https(_request(forwarded_proto="https", client_host="203.0.113.10")) is False


def test_account_entry_persists_ip_lock_and_sets_secure_cookie(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    app = FastAPI()
    app.include_router(auth.router)

    with TestClient(app, base_url="https://testserver") as client:
        first = client.post("/api/auth/entry", json={"name": "Alice", "phone": "A", "password": "pw"})
        assert first.status_code == 200
        assert "Secure" in first.headers["set-cookie"]
        assert "Domain=" not in first.headers["set-cookie"]

        for _ in range(5):
            failed = client.post(
                "/api/auth/entry",
                json={"name": "Alice", "phone": "A", "password": "wrong"},
            )
            assert failed.status_code == 401
        locked = client.post(
            "/api/auth/entry",
            json={"name": "Alice", "phone": "A", "password": "pw"},
        )
        assert locked.status_code == 429


def test_registration_rate_limit_is_persistent_and_does_not_block_login(monkeypatch, tmp_path):
    from app.services import account_store as account_store_module

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    now = [100.0]
    monkeypatch.setattr(account_store_module.time, "time", lambda: now[0])
    app = FastAPI()
    app.include_router(auth.router)

    with TestClient(app) as client:
        for index in range(5):
            created = client.post(
                "/api/auth/entry",
                json={"name": f"User {index}", "phone": f"phone-{index}", "password": "pw"},
            )
            assert created.status_code == 200
            assert created.json()["created"] is True

        limited = client.post(
            "/api/auth/entry",
            json={"name": "Sixth", "phone": "phone-5", "password": "pw"},
        )
        assert limited.status_code == 429
        assert int(limited.headers["retry-after"]) > 0

        # The limiter protects account creation, not normal login for an
        # existing account behind the same office/NAT address.
        login = client.post(
            "/api/auth/entry",
            json={"name": "Ignored", "phone": "phone-0", "password": "pw"},
        )
        assert login.status_code == 200
        assert login.json()["created"] is False

        # A new AccountStore instance observes the same persisted window.
        account_store_module._stores.clear()
        still_limited = client.post(
            "/api/auth/entry",
            json={"name": "Still limited", "phone": "phone-6", "password": "pw"},
        )
        assert still_limited.status_code == 429

        now[0] += 3601
        after_window = client.post(
            "/api/auth/entry",
            json={"name": "After window", "phone": "phone-7", "password": "pw"},
        )
        assert after_window.status_code == 200
        assert after_window.json()["created"] is True
