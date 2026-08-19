from datetime import date

import polars as pl
import pytest
from fastapi import HTTPException

from app.api import ext_data
from app.api.ext_data import _filter_dimension_member_rows


def test_filter_dimension_member_rows_matches_complete_tags() -> None:
    rows = pl.DataFrame({
        "symbol": ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"],
        "所属概念": ["人工智能;芯片", "人工智能体;机器人", "芯片 / 人工智能", None],
    })

    result = _filter_dimension_member_rows(rows, "所属概念", "人工智能")

    assert result.get_column("symbol").to_list() == ["000001.SZ", "000003.SZ"]


def test_filter_dimension_member_rows_matches_industry_hierarchy() -> None:
    rows = pl.DataFrame({
        "symbol": ["000001.SZ", "000002.SZ", "000003.SZ"],
        "所属行业": ["金融-银行-股份制银行", "电子-半导体-数字芯片", "电子元件"],
    })

    result = _filter_dimension_member_rows(rows, "所属行业", "电子")

    assert result.get_column("symbol").to_list() == ["000002.SZ"]


def test_filter_dimension_member_rows_rejects_unknown_field() -> None:
    rows = pl.DataFrame({"symbol": ["000001.SZ"]})

    with pytest.raises(HTTPException, match="字段 '所属行业' 不存在"):
        _filter_dimension_member_rows(rows, "所属行业", "银行")


def test_ext_data_freshness_marks_default_old_snapshot_but_not_explicit_history(monkeypatch):
    monkeypatch.setattr(ext_data, "cn_today", lambda: date(2026, 8, 19))

    stale = ext_data._data_freshness("2026-08-18 22:21:52", explicit_date=False)
    historical = ext_data._data_freshness("2026-08-18", explicit_date=True)

    assert stale == {
        "snapshot_date": "2026-08-18",
        "current_date": "2026-08-19",
        "is_stale": True,
        "calendar_basis": "weekday_fallback",
    }
    assert historical["is_stale"] is False
