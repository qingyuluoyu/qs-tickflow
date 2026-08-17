import time

from app.services.ext_presets import get_preset
from app.services.ext_pull import seconds_until_next_pull


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
