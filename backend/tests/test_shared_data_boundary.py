"""账户模式下的共享/个人数据边界回归测试。

- regime 是全市场聚合数据, 管道写共享根 → API 必须读共享根(V6 修复)。
- /api/overview/market 的 5s 进程缓存必须按用户分键,
  否则 B 用户会拿到 A 用户的个性化扩展表排名(V4 修复)。
"""
from __future__ import annotations

from types import SimpleNamespace

from app.api import overview, regime


def _request(user_id: str | None, shared_root):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(
            repo=SimpleNamespace(store=SimpleNamespace(data_dir=shared_root)),
            quote_service=None,
            depth_service=None,
            market_overview_preloader=None,
        )),
        state=SimpleNamespace(
            user=SimpleNamespace(id=user_id) if user_id else None,
        ),
    )


def test_regime_api_reads_shared_root_not_personal_workspace(tmp_path):
    shared = tmp_path / "shared"
    request = _request("user-a", shared)
    assert regime._data_dir(request) == shared


def test_overview_cache_is_keyed_per_user(monkeypatch, tmp_path):
    shared = tmp_path / "shared"
    built_for: list[str] = []

    def fake_build(request, as_of=None, *, local_only=False):
        uid = request.state.user.id
        built_for.append(uid)
        return {"for": uid}

    monkeypatch.setattr(overview, "_build_overview", fake_build)
    monkeypatch.setattr(overview, "_cache", {})

    r_a = overview.market_overview(_request("user-a", shared), local_only=True)
    r_b = overview.market_overview(_request("user-b", shared), local_only=True)
    r_a2 = overview.market_overview(_request("user-a", shared), local_only=True)

    assert r_a == {"for": "user-a"}
    assert r_b == {"for": "user-b"}  # 不得命中 A 的缓存
    assert r_a2 == {"for": "user-a"}  # 同用户命中自己的缓存
    assert built_for == ["user-a", "user-b"]


def test_pipeline_switches_are_server_scoped(monkeypatch, tmp_path):
    """管道拉取开关/调度时间是全局管道的行为, 必须存服务器级配置,
    否则账户模式下用户在 UI 的修改不会被后台管道读到(V3 修复)。"""
    from app.config import settings
    from app.services import preferences

    monkeypatch.setattr(settings, "data_dir", tmp_path)

    # 写入(模拟任意登录用户的设置请求, 无用户上下文也能生效)
    preferences.set_pipeline_pull_types({"pipeline_pull_etf": True})
    preferences.set_pipeline_schedule(16, 45)
    preferences.set_depth_finalize_time(15, 30)
    preferences.set_pipeline_index_symbols("000001.SH, 399001.SZ")

    # 后台管道语境(无用户上下文)读取 — 修复前会回落 legacy 文件读不到上面的值
    assert preferences.get_pipeline_pull_etf() is True
    assert preferences.get_pipeline_schedule() == {"hour": 16, "minute": 45}
    assert preferences.get_depth_finalize_time() == {"hour": 15, "minute": 30}
    assert preferences.get_pipeline_index_symbols() == "000001.SH, 399001.SZ"

    # 落盘位置确实是服务器级配置文件
    import json
    stored = json.loads((tmp_path / "server_config.json").read_text(encoding="utf-8"))
    assert stored["pipeline_pull_etf"] is True
    assert stored["pipeline_schedule"] == {"hour": 16, "minute": 45}


# ============================================================
# AI 平台默认配置与误写入修复
# ============================================================

def _ai_master_key() -> str:
    import base64
    return base64.urlsafe_b64encode(b"0" * 32).decode("ascii")


def _ai_create_user(data_dir, *, name: str, phone: str):
    from app.services.account_store import get_account_store
    result = get_account_store(data_dir).enter(name, phone, f"{phone}-password")
    assert result is not None
    return result.user


def test_server_default_ai_profile_reads_shared_secrets(monkeypatch, tmp_path):
    """平台默认 AI 配置: env 为空时回落共享 secrets.json (部署方的 deepseek),
    任何用户登录都默认用它, 不需要往个人配置里拷贝。"""
    import json
    from app.config import settings
    from app.services import ai_profiles
    from app.services.user_context import reset_current_user, set_current_user
    from app.services.account_store import get_account_store

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "user_secrets_master_key", _ai_master_key(), raising=False)
    monkeypatch.setattr(settings, "ai_api_key", "")
    monkeypatch.setattr(settings, "ai_base_url", "https://api.zhaji.dev/v1")
    monkeypatch.setattr(settings, "ai_model", "gpt-5.5")
    legacy_dir = tmp_path / "user_data"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "secrets.json").write_text(json.dumps({
        "ai_provider": "openai_compat",
        "ai_base_url": "https://api.deepseek.com",
        "ai_api_key": "platform-deepseek-key",
        "ai_model": "deepseek-chat",
    }), encoding="utf-8")

    user = _ai_create_user(tmp_path, name="u1", phone="u1-phone")
    tokens = set_current_user(user, get_account_store(tmp_path).workspace(user.id))
    try:
        profile = ai_profiles.resolve_current_profile()
    finally:
        reset_current_user(tokens)

    assert profile.source == "server_default"
    assert profile.api_key == "platform-deepseek-key"
    assert profile.model == "deepseek-chat"
    # 且不得在个人账户里留下覆盖配置
    from app.services.account_store import get_account_store as gas
    assert gas(tmp_path).get_user_ai_profile(user.id) is None


def test_legacy_ai_migration_skipped_in_multi_user_deployment(monkeypatch, tmp_path):
    """多账户服务器: 共享 secrets.json 里的平台 key 绝不复制进新登录用户的
    个人配置 (此前每个新用户首次解析都会被写入一份, 永远 pinned)。"""
    import json
    from app.config import settings
    from app.services import ai_profiles
    from app.services.user_context import reset_current_user, set_current_user
    from app.services.account_store import get_account_store

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "user_secrets_master_key", _ai_master_key(), raising=False)
    monkeypatch.setattr(settings, "ai_api_key", "")
    legacy_dir = tmp_path / "user_data"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "secrets.json").write_text(json.dumps({
        "ai_base_url": "https://api.deepseek.com",
        "ai_api_key": "platform-deepseek-key",
        "ai_model": "deepseek-chat",
    }), encoding="utf-8")

    _ai_create_user(tmp_path, name="first", phone="first-phone")
    second = _ai_create_user(tmp_path, name="second", phone="second-phone")
    tokens = set_current_user(second, get_account_store(tmp_path).workspace(second.id))
    try:
        profile = ai_profiles.resolve_current_profile()
    finally:
        reset_current_user(tokens)

    assert profile.source == "server_default"
    assert get_account_store(tmp_path).get_user_ai_profile(second.id) is None


def test_require_admin_gate():
    """服务器级写操作的管理员闸门。"""
    from fastapi import HTTPException
    from app.api.deps import require_admin

    admin_req = SimpleNamespace(state=SimpleNamespace(
        user=SimpleNamespace(id="a", is_admin=True)))
    user_req = SimpleNamespace(state=SimpleNamespace(
        user=SimpleNamespace(id="u", is_admin=False)))
    anon_req = SimpleNamespace(state=SimpleNamespace(user=None))

    assert require_admin(admin_req).id == "a"
    for req in (user_req, anon_req):
        try:
            require_admin(req)
            raise AssertionError("should have raised")
        except HTTPException as e:
            assert e.status_code in (401, 403)
