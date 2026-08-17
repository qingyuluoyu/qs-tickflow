"""Request-scoped AI configuration with encrypted user overrides.

The server deployment supplies the default model/API configuration. A logged-in
user may opt into an OpenAI-compatible profile of their own; that profile is
stored encrypted and resolved only while that user's context is bound.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.services.account_store import get_account_store
from app.services.user_context import current_user

OPENAI_COMPAT_PROVIDER = "openai_compat"
CODEX_CLI_PROVIDER = "codex_cli"
_MASTER_KEY_FILENAME = ".user-secrets.master"


@dataclass(frozen=True)
class ResolvedAiProfile:
    provider: str
    base_url: str
    api_key: str
    model: str
    user_agent: str
    codex_command: str
    codex_reasoning_effort: str
    source: str


def _server_default() -> ResolvedAiProfile:
    return ResolvedAiProfile(
        provider=settings.ai_provider or OPENAI_COMPAT_PROVIDER,
        base_url=settings.ai_base_url,
        api_key=settings.ai_api_key,
        model=settings.ai_model,
        user_agent=settings.ai_user_agent,
        codex_command=settings.ai_codex_command,
        codex_reasoning_effort=settings.ai_codex_reasoning_effort,
        source="server_default",
    )


def _master_key_path() -> Path:
    return Path(settings.data_dir) / _MASTER_KEY_FILENAME


def _fernet() -> Fernet:
    configured = settings.user_secrets_master_key.strip()
    if configured:
        return Fernet(configured.encode("ascii"))

    path = _master_key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        key = path.read_bytes().strip()
    except FileNotFoundError:
        key = Fernet.generate_key()
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            key = path.read_bytes().strip()
        else:
            with os.fdopen(fd, "wb") as handle:
                handle.write(key)
                handle.flush()
                os.fsync(handle.fileno())
    try:
        return Fernet(key)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("用户密钥加密主密钥无效") from exc


def _validate_user_base_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("个人 AI API 地址必须是无凭据的 HTTPS 地址")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise ValueError("个人 AI API 地址不能指向本机或局域网主机")
    port = parsed.port or 443
    try:
        addresses = _resolve_public_addresses(host, port)
    except OSError as exc:
        raise ValueError("个人 AI API 地址无法解析") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("个人 AI API 地址不能指向私有网络地址")
    return value


def _resolve_public_addresses(host: str, port: int) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve all endpoint addresses before persisting a user-controlled URL."""
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        return list({ipaddress.ip_address(record[4][0]) for record in records})
    return [literal]


def _require_current_user_id() -> str:
    user = current_user()
    if user is None:
        raise RuntimeError("用户 AI 配置必须在已认证的用户上下文中访问")
    return user.id


def resolve_current_profile() -> ResolvedAiProfile:
    """Resolve a user override, falling back to the deployment default."""
    user = current_user()
    if user is None:
        return _server_default()
    record = get_account_store(settings.data_dir).get_user_ai_profile(user.id)
    if record is None:
        _migrate_legacy_current_override()
        record = get_account_store(settings.data_dir).get_user_ai_profile(user.id)
    if record is None:
        return _server_default()
    if record.provider != OPENAI_COMPAT_PROVIDER or not record.encrypted_api_key:
        return _server_default()
    try:
        api_key = _fernet().decrypt(record.encrypted_api_key).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise RuntimeError("个人 AI 配置无法解密，请重新保存") from exc
    return ResolvedAiProfile(
        provider=record.provider,
        base_url=record.base_url,
        api_key=api_key,
        model=record.model,
        user_agent=record.user_agent or settings.ai_user_agent,
        codex_command=record.codex_command,
        codex_reasoning_effort=record.codex_reasoning_effort,
        source="user_override",
    )


def _migrate_legacy_current_override() -> None:
    """Copy a valid pre-database personal AI configuration once, never delete it.

    The original ``secrets.json`` stays untouched as a rollback source. Invalid
    or unsupported legacy entries simply keep using the server default instead
    of blocking an authenticated request.
    """
    from app import secrets_store

    legacy = secrets_store.load()
    key = str(legacy.get("ai_api_key") or "").strip()
    if not key:
        return
    try:
        save_current_override(
            provider=str(legacy.get("ai_provider") or OPENAI_COMPAT_PROVIDER),
            base_url=str(legacy.get("ai_base_url") or ""),
            api_key=key,
            model=str(legacy.get("ai_model") or ""),
            user_agent=str(legacy.get("ai_user_agent") or ""),
            codex_command=str(legacy.get("ai_codex_command") or ""),
            codex_reasoning_effort=str(legacy.get("ai_codex_reasoning_effort") or ""),
        )
    except ValueError:
        return


def save_current_override(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    user_agent: str,
    codex_command: str = "",
    codex_reasoning_effort: str = "",
) -> ResolvedAiProfile:
    """Encrypt and persist an OpenAI-compatible override for the current user."""
    user_id = _require_current_user_id()
    if provider != OPENAI_COMPAT_PROVIDER:
        raise ValueError("个人 API 配置目前仅支持 OpenAI 兼容协议")
    normalized_url = _validate_user_base_url(base_url)
    store = get_account_store(settings.data_dir)
    existing = store.get_user_ai_profile(user_id)
    if api_key.strip():
        encrypted = _fernet().encrypt(api_key.strip().encode("utf-8"))
    elif existing is not None and existing.encrypted_api_key:
        encrypted = existing.encrypted_api_key
    else:
        raise ValueError("使用个人 AI 配置时必须填写 API Key")
    if not model.strip():
        raise ValueError("使用个人 AI 配置时必须填写模型名称")
    store.save_user_ai_profile(
        user_id,
        provider=provider,
        base_url=normalized_url,
        model=model.strip(),
        encrypted_api_key=encrypted,
        user_agent=user_agent.strip(),
        codex_command=codex_command.strip(),
        codex_reasoning_effort=codex_reasoning_effort.strip(),
    )
    return resolve_current_profile()


def clear_current_override() -> bool:
    return get_account_store(settings.data_dir).clear_user_ai_profile(_require_current_user_id())


def has_current_override() -> bool:
    user = current_user()
    return bool(user and get_account_store(settings.data_dir).get_user_ai_profile(user.id))


def masked_current_override_key() -> str:
    profile = resolve_current_profile()
    if profile.source != "user_override" or not profile.api_key:
        return ""
    key = profile.api_key
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}{'•' * 6}{key[-4:]}"
