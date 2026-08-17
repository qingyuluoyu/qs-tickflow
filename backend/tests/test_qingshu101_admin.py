from app.api import qingshu101
from starlette.requests import Request


def _request(host: str) -> Request:
    return Request({
        "type": "http",
        "scheme": "https",
        "path": "/api/qingshu101/status",
        "raw_path": b"/api/qingshu101/status",
        "query_string": b"",
        "headers": [(b"host", host.encode())],
        "client": ("127.0.0.1", 1234),
        "server": (host, 443),
    })


def test_admin_cookie_is_signed_and_expires(monkeypatch):
    monkeypatch.setattr(qingshu101.settings, "qingshu101_admin_key", "local-secret-for-test")
    cookie = qingshu101._make_cookie(now=100)

    assert qingshu101._cookie_valid(cookie, now=101)
    assert not qingshu101._cookie_valid(cookie, now=100 + qingshu101._ADMIN_TTL_SECONDS)
    assert not qingshu101._cookie_valid(f"{cookie}x", now=101)


def test_admin_host_must_match_explicit_production_host(monkeypatch):
    monkeypatch.setattr(qingshu101.settings, "qingshu101_admin_key", "local-secret-for-test")
    monkeypatch.setattr(qingshu101.settings, "qingshu101_host", "ops.example.com")

    assert qingshu101._host_allowed(_request("ops.example.com")) is True
    assert qingshu101._host_allowed(_request("qingshu101.example.com")) is False


def test_admin_attempt_lock_uses_shared_account_store(monkeypatch, tmp_path):
    from app.services.account_store import AccountStore

    monkeypatch.setattr(qingshu101.settings, "qingshu101_admin_key", "local-secret-for-test")
    monkeypatch.setattr(qingshu101.settings, "qingshu101_host", "ops.example.com")
    monkeypatch.setattr(qingshu101.settings, "data_dir", tmp_path)
    request = _request("ops.example.com")
    store = AccountStore(tmp_path)
    key = qingshu101._admin_attempt_key(request)
    for _ in range(5):
        store.record_login_failure(key, now=100.0)

    assert qingshu101._admin_lock_remaining(request, store=store, now=101.0) > 0
