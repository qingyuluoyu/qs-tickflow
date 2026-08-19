"""访问认证 API。

端点:
  GET  /api/auth/status        — 是否已设密码、当前会话是否有效
  POST /api/auth/setup         — 首次设置密码(仅限本机/内网, 防公网抢占)
  POST /api/auth/login         — 登录(密码 → 会话 token, 含限流)
  POST /api/auth/logout        — 注销当前会话
  POST /api/auth/change-password — 改密码(需已登录)

安全:
  - setup 端点只接受本机/内网请求(request.client.host), 公网请求 403。
    否则黑客可比用户更早扫到域名, 抢先设密码, 反客为主。
  - login 限流: 同一来源 IP 连续失败 5 次, 锁 5 分钟(内存计数)。
  - 会话 token 通过 HttpOnly cookie 下发, 前端无需手动管理。
"""
from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.config import settings
from app.services import auth
from app.services.account_store import RegistrationRateLimitError, get_account_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_NAME = "tf_session"
_COOKIE_MAX_AGE = 30 * 24 * 3600  # 与 SESSION_TTL 一致

def _is_local_network(host: str | None) -> bool:
    """是否本机或内网请求。

    反向代理(Nginx)场景下 request.client.host 是代理本身(127.0.0.1),
    需信任 X-Forwarded-For 的最左(原始客户端)。本项目部署若经反代,
    请在反代配置正确的 X-Forwarded-For(标准做法)。
    """
    if not host:
        return False
    if host in ("127.0.0.1", "::1", "localhost"):
        return True
    # 内网网段: 10.x / 172.16-31.x / 192.168.x
    if host.startswith("10.") or host.startswith("192.168."):
        return True
    if host.startswith("172."):
        try:
            second = int(host.split(".")[1])
            if 16 <= second <= 31:
                return True
        except (IndexError, ValueError):
            pass
    return False


def _client_ip(request: Request) -> str:
    """取真实客户端 IP。

    安全关键: 仅当直连 peer(request.client.host)本身是回环/内网地址
    (即请求确实经过同机/内网的可信反代)时, 才采信 X-Forwarded-For。
    否则公网请求可伪造 `X-Forwarded-For: 127.0.0.1` 冒充内网, 绕过
    「未设密码仅本机可访问」闸门、抢占 setup 端点、并绕过登录限流。
    """
    direct = request.client.host if request.client else ""
    xff = request.headers.get("x-forwarded-for")
    if xff and direct and _is_local_network(direct):
        return xff.split(",")[0].strip()
    return direct or "unknown"


def _auth_attempt_key(ip: str) -> str:
    """Hash the client address before persisting it in SQLite."""
    return hashlib.sha256(f"auth:{ip}".encode()).hexdigest()


def _registration_attempt_key(ip: str) -> str:
    """Hash registration throttling identifiers independently from login failures."""
    return hashlib.sha256(f"registration:{ip}".encode()).hexdigest()


def _is_https(request: Request) -> bool:
    """Trust forwarded HTTPS only when the direct peer is a local proxy."""
    if request.url.scheme.lower() == "https":
        return True
    direct = request.client.host if request.client else ""
    forwarded = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    return bool(forwarded == "https" and _is_local_network(direct))


def _check_login_rate_limit(store, ip: str) -> None:
    remaining = store.check_login_lock(_auth_attempt_key(ip))
    if remaining > 0:
        raise HTTPException(
            status_code=429,
            detail=f"登录失败次数过多, 请 {remaining} 秒后重试",
        )


def _record_login_fail(store, ip: str) -> None:
    count = store.record_login_failure(_auth_attempt_key(ip))
    if count >= 5:
        logger.warning("auth login locked for client %s after %d fails", ip, count)


def _clear_login_fails(store, ip: str) -> None:
    store.clear_login_failures(_auth_attempt_key(ip))


# ================================================================
# 端点
# ================================================================

class PasswordIn(BaseModel):
    password: str = Field(min_length=6, max_length=128)


class LoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class AccountEntryIn(BaseModel):
    """Embedded account entry form.

    No business format or length rules are applied. The HTTP layer still
    rejects an unusually large request body before parsing it as a resource
    exhaustion guard; submitted values are never truncated or normalized.
    """

    name: str = ""
    phone: str
    password: str


def _accounts():
    return get_account_store(settings.data_dir)


@router.get("/status")
def auth_status(request: Request) -> dict:
    """认证状态和当前账户身份。"""
    token = request.cookies.get(COOKIE_NAME)
    store = _accounts()
    user = store.user_for_token(token)
    return {
        "configured": store.has_users(),
        "authenticated": user is not None,
        "user": ({"id": user.id, "name": user.name, "phone": user.phone, "role": user.role} if user else None),
    }


@router.get("/me")
def current_account(request: Request) -> dict:
    """Return only the current session's identity; never another account."""
    user = _accounts().user_for_token(request.cookies.get(COOKIE_NAME))
    if user is None:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
    return {"user": {"id": user.id, "name": user.name, "phone": user.phone, "role": user.role}}


@router.post("/entry")
def account_entry(req: AccountEntryIn, request: Request, response: Response) -> dict:
    """创建账户或登录已有账户(电话或用户名),作为站点唯一入口。"""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 256 * 1024:
                raise HTTPException(status_code=413, detail="账户信息请求过大")
        except ValueError:
            pass
    ip = _client_ip(request)
    store = _accounts()
    _check_login_rate_limit(store, ip)
    try:
        result = store.enter(
            req.name,
            req.phone,
            req.password,
            registration_key=_registration_attempt_key(ip),
        )
    except RegistrationRateLimitError as exc:
        raise HTTPException(
            status_code=429,
            detail=f"该网络注册账户过于频繁, 请 {exc.retry_after} 秒后重试",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        _record_login_fail(store, ip)
        raise HTTPException(status_code=401, detail="用户名/电话或密码错误")
    _clear_login_fails(store, ip)
    directory = getattr(request.app.state, "account_directory", None)
    if directory is not None:
        try:
            directory.refresh_now()
        except Exception:  # noqa: BLE001
            logger.warning("account directory refresh failed after entry", exc_info=True)
    if result.created:
        # The first account switches the process from legacy single-user mode
        # to per-account workspaces. Drop any legacy shared monitor rules so
        # they cannot be evaluated or broadcast to all accounts.
        monitor_engine = getattr(request.app.state, "monitor_engine", None)
        if monitor_engine is not None:
            monitor_engine.set_rules([])
    monitor_runtime = getattr(request.app.state, "monitor_runtime", None)
    if monitor_runtime is not None:
        try:
            monitor_runtime.refresh_now()
        except Exception:  # noqa: BLE001
            logger.warning("account monitor runtime refresh failed after entry", exc_info=True)
    response.set_cookie(
        key=COOKIE_NAME,
        value=result.token,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
        secure=_is_https(request),
    )
    return {
        "ok": True,
        "created": result.created,
        "authenticated": True,
        "user": {"id": result.user.id, "name": result.user.name, "phone": result.user.phone, "role": result.user.role},
    }


@router.post("/setup")
def setup_password(req: PasswordIn, request: Request) -> dict:
    """首次设置访问密码。仅限本机/内网请求(防公网抢占)。

    若已设置过密码, 返回 409(改密码走 /change-password)。
    """
    if _accounts().has_users():
        raise HTTPException(status_code=410, detail="账户模式已启用，请使用姓名、电话和密码进入")
    # 关键: 限制只有服务器主人(本机/内网)能设密码
    client_ip = _client_ip(request)
    if not _is_local_network(client_ip):
        logger.warning("setup rejected from non-local ip: %s", client_ip)
        raise HTTPException(
            status_code=403,
            detail="首次设置密码仅允许本机或内网访问,请通过 SSH/本地浏览器操作",
        )

    if auth.is_configured():
        raise HTTPException(status_code=409, detail="密码已设置,如需修改请登录后使用改密码功能")

    auth.set_password(req.password)
    logger.info("access password set up from %s", client_ip)
    return {"ok": True, "configured": True}


@router.post("/login")
def login(req: LoginIn, request: Request, response: Response) -> dict:
    """登录: 密码 → 会话 token(写 HttpOnly cookie)。含失败限流。"""
    if _accounts().has_users():
        raise HTTPException(status_code=410, detail="账户模式已启用，请使用姓名、电话和密码进入")
    ip = _client_ip(request)
    store = _accounts()
    _check_login_rate_limit(store, ip)

    if not auth.is_configured():
        raise HTTPException(status_code=409, detail="尚未设置访问密码")

    token = auth.verify_and_create_session(req.password)
    if not token:
        _record_login_fail(store, ip)
        raise HTTPException(status_code=401, detail="密码错误")

    _clear_login_fails(store, ip)
    # HttpOnly: 防 XSS 窃取; SameSite=Lax: 防 CSRF; Path=/: 全站生效
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
        secure=_is_https(request),
    )
    return {"ok": True, "authenticated": True}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    """注销当前会话。"""
    token = request.cookies.get(COOKIE_NAME)
    if token:
        _accounts().revoke(token)
        # Keep legacy sessions revocable for old local deployments.
        auth.revoke_session(token)
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"ok": True}


@router.post("/change-password")
def change_password(req: ChangePasswordIn, request: Request) -> dict:
    """修改密码: 需验证旧密码, 成功后所有会话失效(含当前, 需重新登录)。"""
    token = request.cookies.get(COOKIE_NAME)
    if _accounts().has_users():
        raise HTTPException(status_code=410, detail="账户密码请通过站点入口更换（当前版本不提供独立设置页）")
    if not (token and auth.is_valid_session(token)):
        raise HTTPException(status_code=401, detail="请先登录")

    if not auth.is_configured():
        raise HTTPException(status_code=409, detail="尚未设置访问密码")

    # 验证旧密码
    new_token = auth.verify_and_create_session(req.old_password)
    if not new_token:
        ip = _client_ip(request)
        _record_login_fail(_accounts(), ip)
        raise HTTPException(status_code=401, detail="旧密码错误")
    # 临时 token 用完即弃
    auth.revoke_session(new_token)

    # 改密码(set_password 会清空所有会话)
    auth.set_password(req.new_password)
    return {"ok": True, "message": "密码已修改, 请重新登录"}
