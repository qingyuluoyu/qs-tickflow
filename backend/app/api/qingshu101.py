"""Protected operator directory for the qingshu101 subdomain.

The route is intentionally not a public "secret URL": it is disabled unless
``QINGSHU101_ADMIN_KEY`` is configured and every data request requires a
short-lived, HttpOnly signed cookie.  Passwords and password hashes are never
returned.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/qingshu101", tags=["qingshu101-admin"])

ADMIN_COOKIE = "qingshu101_admin"
_ADMIN_TTL_SECONDS = 8 * 60 * 60
_MIN_ADMIN_KEY_LENGTH = 16
_MAX_ADMIN_FAILURES = 5


class AdminSessionIn(BaseModel):
    key: str


def _configured_key() -> str:
    key = str(settings.qingshu101_admin_key or "")
    return key if len(key) >= _MIN_ADMIN_KEY_LENGTH else ""


def _host_allowed(request: Request) -> bool:
    host = (request.url.hostname or "").lower().rstrip(".")
    configured = str(getattr(settings, "qingshu101_host", "qingshu101") or "").lower().rstrip(".")
    if configured and host == configured:
        return True
    # Local development does not have DNS for a subdomain. Keep localhost
    # usable, while production deployments should point the real subdomain.
    return host in {"localhost", "127.0.0.1", "::1", "testserver"}


def _is_https(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    if request.url.scheme == "https":
        return True
    if forwarded != "https":
        return False
    # Only trust the proxy header from a local/private reverse proxy. A
    # public client must not be able to influence the cookie Secure flag.
    from app.api.auth import _is_local_network
    direct_host = request.client.host if request.client else ""
    return _is_local_network(direct_host)


def _admin_attempt_key(request: Request) -> str:
    from app.api.auth import _client_ip
    return hashlib.sha256(f"qingshu101:{_client_ip(request)}".encode()).hexdigest()


def _admin_lock_remaining(request: Request, *, store=None, now: float | None = None) -> int:
    if store is None:
        from app.services.account_store import get_account_store
        store = get_account_store(settings.data_dir)
    return store.check_login_lock(_admin_attempt_key(request), now=now)


def _admin_ttl_seconds() -> int:
    value = int(getattr(settings, "qingshu101_cookie_ttl", _ADMIN_TTL_SECONDS) or _ADMIN_TTL_SECONDS)
    return max(300, value)


def _cookie_signature(expires_at: int) -> str:
    key = _configured_key()
    payload = f"qingshu101:{expires_at}".encode()
    return hmac.new(key.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _make_cookie(now: int | None = None) -> str:
    expires_at = int(now if now is not None else time.time()) + _admin_ttl_seconds()
    return f"{expires_at}.{_cookie_signature(expires_at)}"


def _cookie_valid(value: str | None, now: int | None = None) -> bool:
    if not _configured_key() or not value:
        return False
    try:
        expires_text, provided = value.split(".", 1)
        expires_at = int(expires_text)
    except (TypeError, ValueError):
        return False
    current = int(now if now is not None else time.time())
    if expires_at <= current:
        return False
    expected = _cookie_signature(expires_at)
    return hmac.compare_digest(provided, expected)


def _require_admin(request: Request) -> None:
    if not _configured_key() or not _host_allowed(request):
        # Do not reveal that the route exists when it is disabled or called
        # from an unrelated host.
        raise HTTPException(status_code=404, detail="Not found")
    if not _cookie_valid(request.cookies.get(ADMIN_COOKIE)):
        raise HTTPException(status_code=401, detail="管理员会话无效或已过期")


@router.get("/status")
def status(request: Request, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    configured = bool(_configured_key()) and _host_allowed(request)
    directory = getattr(request.app.state, "account_directory", None)
    return {
        "configured": configured,
        "authenticated": configured and _cookie_valid(request.cookies.get(ADMIN_COOKIE)),
        "directory": directory.status() if configured and directory is not None else None,
    }


@router.post("/session")
def create_session(req: AdminSessionIn, request: Request, response: Response) -> dict:
    if not _configured_key() or not _host_allowed(request):
        raise HTTPException(status_code=404, detail="Not found")
    from app.services.account_store import get_account_store
    store = get_account_store(settings.data_dir)
    remaining = _admin_lock_remaining(request, store=store)
    if remaining > 0:
        raise HTTPException(status_code=429, detail=f"管理员密钥尝试过多，请 {remaining} 秒后重试")
    if not hmac.compare_digest(req.key, _configured_key()):
        count = store.record_login_failure(_admin_attempt_key(request))
        if count >= _MAX_ADMIN_FAILURES:
            logger.warning("qingshu101 admin login locked for client")
        raise HTTPException(status_code=401, detail="管理员密钥错误")
    store.clear_login_failures(_admin_attempt_key(request))
    response.set_cookie(
        key=ADMIN_COOKIE,
        value=_make_cookie(),
        max_age=_admin_ttl_seconds(),
        httponly=True,
        secure=_is_https(request),
        samesite="strict",
        path="/",
    )
    return {"ok": True, "expires_in": _admin_ttl_seconds()}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    if not _host_allowed(request):
        raise HTTPException(status_code=404, detail="Not found")
    response.delete_cookie(key=ADMIN_COOKIE, path="/")
    return {"ok": True}


@router.get("/users")
def users(
    request: Request,
    response: Response,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    _require_admin(request)
    response.headers["Cache-Control"] = "no-store"
    directory = getattr(request.app.state, "account_directory", None)
    if directory is None:
        raise HTTPException(status_code=503, detail="注册目录预处理服务未就绪")
    total, rows = directory.page(offset=offset, limit=limit)
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "refreshed_at": directory.refreshed_at,
        "directory_status": directory.status(),
        "users": rows,
    }
