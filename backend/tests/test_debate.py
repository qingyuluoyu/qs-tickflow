from pathlib import Path

import polars as pl

from app.services.debate import _stage_plan, build_dossier, dossier_text, normalize_symbol


class _Repo:
    def __init__(self):
        self.store = type("Store", (), {"data_dir": Path(".")})()

    def get_instruments(self):
        return pl.DataFrame({"code": ["600519"], "symbol": ["600519.SH"]})

    def resolve_asset_type(self, symbol):
        return "stock"

    def get_daily_asset(self, *args):
        return pl.DataFrame()


def test_stage_plan_rounds():
    assert _stage_plan(1) == ["bull", "bear", "referee"]
    assert _stage_plan(2)[-1] == "referee"
    assert len(_stage_plan(2)) == 5


def test_normalize_symbol_accepts_code_and_symbol():
    repo = _Repo()
    assert normalize_symbol(repo, "600519") == "600519.SH"
    assert normalize_symbol(repo, "600519.SH") == "600519.SH"


def test_dossier_marks_unavailable_data_without_fabricating():
    dossier = build_dossier(_Repo(), Path("."), "600519")
    assert "近期公告" in dossier["missing"]
    assert "该数据项目前未接入" in dossier_text(dossier)

