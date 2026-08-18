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
