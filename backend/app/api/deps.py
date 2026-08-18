"""API 级共享依赖。

require_admin: 服务器级写操作(数据源管理、provider 切换、清空行情、
手动触发全局管道、服务器级偏好)只允许管理员账户执行。
账户角色存 users.role (migration 006), 由 auth_middleware 解析会话后
挂在 request.state.user 上。
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from app.services.user_context import UserIdentity


def require_admin(request: Request) -> UserIdentity:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
