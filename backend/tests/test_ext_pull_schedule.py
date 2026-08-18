import time

from app.services.ext_presets import get_preset
from app.services.ext_pull import PullScheduler, seconds_until_next_pull


def test_fresh_server_snapshot_is_not_downloaded_again_on_restart(tmp_path):
    config = get_preset("ext_gn_ths")
    assert config is not None and config.pull is not None
    part = tmp_path / "ext_data" / config.id / "part.parquet"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"cached")
    now = time.time()

    delay = seconds_until_next_pull(config, tmp_path, now_ts=now)

    assert delay > (config.pull.schedule_minutes * 60) - 5


def test_missing_server_snapshot_is_preloaded_immediately(tmp_path):
    config = get_preset("ext_hy_ths")
    assert config is not None

    assert seconds_until_next_pull(config, tmp_path, now_ts=time.time()) == 0


class _FakeTask:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class _FakeLoop:
    def create_task(self, coro):
        coro.close()  # 不真正执行拉取循环
        return _FakeTask()


def _make_scheduler() -> PullScheduler:
    s = PullScheduler()
    s._running = True
    s._loop = _FakeLoop()
    s._submit = lambda fn, *args: fn(*args)  # 同步执行, 绕过事件循环
    return s


def test_pull_scheduler_refresh_is_scoped_to_data_root(tmp_path):
    """账户模式隔离回归(V1): 用户根的 refresh 不得取消共享根的定时任务,
    反之亦然; 同 id 配置在不同根下是独立任务。"""
    from app.services.ext_data import ExtConfigStore

    shared = tmp_path / "shared"
    user = tmp_path / "users" / "u1"
    ExtConfigStore(shared).upsert(get_preset("ext_gn_ths"))
    ExtConfigStore(user).upsert(get_preset("ext_hy_ths"))

    s = _make_scheduler()
    s.refresh(shared)
    s.refresh(user)

    assert set(s._tasks) == {
        (str(shared), "ext_gn_ths"),
        (str(user), "ext_hy_ths"),
    }

    # 用户根里看不到共享预设 -> 旧实现会把共享任务当作"已删除"取消
    s.refresh(user)
    assert set(s._tasks) == {
        (str(shared), "ext_gn_ths"),
        (str(user), "ext_hy_ths"),
    }
    assert not s._tasks[(str(shared), "ext_gn_ths")].cancelled

    # 共享根删掉预设 -> 只移除共享根的任务, 用户根不受影响
    ExtConfigStore(shared).delete("ext_gn_ths")
    s.refresh(shared)
    assert set(s._tasks) == {(str(user), "ext_hy_ths")}
