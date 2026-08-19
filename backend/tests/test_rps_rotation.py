"""rps_rotation 回归测试: 维度映射缓存命中时不能破坏返回结构。"""
from datetime import date, timedelta
from types import SimpleNamespace

import polars as pl
import pytest

from app.services import rps_rotation
from app.services.rps_rotation import ExtConfigStore


class _StubStore:
    def __init__(self, data_dir):
        self.data_dir = data_dir


class _StubRepo:
    def __init__(self, data_dir, history: pl.DataFrame):
        self.store = _StubStore(data_dir)
        self._enriched_history_cache = history

    def get_enriched_range(self, start, end, columns):
        return self._enriched_history_cache.select(columns)


@pytest.fixture(autouse=True)
def _clear_caches():
    rps_rotation._cache.clear()
    rps_rotation._cache_ts.clear()
    rps_rotation._map_cache.clear()
    rps_rotation._map_ts.clear()
    yield
    rps_rotation._cache.clear()
    rps_rotation._cache_ts.clear()
    rps_rotation._map_cache.clear()
    rps_rotation._map_ts.clear()


def _setup_ext(tmp_path, monkeypatch):
    ext_dir = tmp_path / "ext_data" / "cfg1"
    ext_dir.mkdir(parents=True)
    pl.DataFrame({"symbol": ["600519.SH"], "行业": ["饮料-白酒-白酒"]}).write_parquet(ext_dir / "base.parquet")
    config = SimpleNamespace(
        id="cfg1",
        mode="snapshot",
        fields=[SimpleNamespace(name="行业", label="行业")],
        symbol_map=None,
        code_map=None,
    )
    monkeypatch.setattr(ExtConfigStore, "load_all", lambda self: [config])


def test_map_cache_hit_returns_tuple(tmp_path, monkeypatch):
    """第二次调用命中 _map_cache 时仍须返回 (DataFrame, count), 不能只存 DataFrame。

    回归: 缓存里只存了 map_df, 命中时调用方解包得到两列 Series,
    随后 join 报 TypeError: expected 'DataFrame', not 'Series' (线上 500)。
    """
    _setup_ext(tmp_path, monkeypatch)
    repo = _StubRepo(tmp_path, pl.DataFrame())
    first = rps_rotation._load_concept_map_df(repo, "industry")
    second = rps_rotation._load_concept_map_df(repo, "industry")
    for result in (first, second):
        map_df, count = result
        assert isinstance(map_df, pl.DataFrame)
        assert isinstance(count, int)
    assert not first[0].is_empty()


def test_build_rotation_twice_with_different_levels(tmp_path, monkeypatch):
    """不同 level 的请求走结果缓存未命中 + 映射缓存命中路径, 不应 500。"""
    _setup_ext(tmp_path, monkeypatch)
    latest = date(2026, 8, 18)
    history = pl.DataFrame({
        "symbol": ["600519.SH"] * 3,
        "date": [latest - timedelta(days=2), latest - timedelta(days=1), latest],
        "change_pct": [0.01, -0.02, 0.03],
    })
    repo = _StubRepo(tmp_path, history)

    first = rps_rotation.build_rps_rotation(repo, days=7, kind="industry", level=1)
    assert first["concept_count"] == 1
    assert first["dates"]  # 有数据列

    second = rps_rotation.build_rps_rotation(repo, days=7, kind="industry", level=2)
    assert second["concept_count"] == 1
    assert second["dates"] == first["dates"]
    # level=2 聚合后成员名是第二段 "白酒"
    top = second["columns"][second["dates"][0]][0]
    assert top[0] == "白酒"
