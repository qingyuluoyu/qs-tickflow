from pathlib import Path
from types import SimpleNamespace

import polars as pl

from app.api.ext_data import dimension_members, list_configs
from app.services.ext_data import ExtConfig, ExtConfigStore, ExtField
from app.services.ext_presets import get_preset


def _request(shared_root: Path, personal_root: Path):
    return SimpleNamespace(
        state=SimpleNamespace(user_data_root=personal_root),
        app=SimpleNamespace(
            state=SimpleNamespace(
                repo=SimpleNamespace(store=SimpleNamespace(data_dir=shared_root)),
            ),
        ),
    )


def test_builtin_configs_and_members_are_read_from_shared_server_data(tmp_path: Path):
    shared_root = tmp_path / "shared"
    personal_root = tmp_path / "users" / "alice"
    shared_root.mkdir(parents=True)
    personal_root.mkdir(parents=True)

    builtin = get_preset("ext_gn_ths")
    assert builtin is not None
    ExtConfigStore(shared_root).upsert(builtin)
    builtin_dir = shared_root / "ext_data" / builtin.id
    pl.DataFrame(
        [
            {"symbol": "000001.SZ", "code": "000001", "股票简称": "平安银行", "所属概念": "金融科技;银行"},
            {"symbol": "300059.SZ", "code": "300059", "股票简称": "东方财富", "所属概念": "金融科技;互联网金融"},
            {"symbol": "600000.SH", "code": "600000", "股票简称": "浦发银行", "所属概念": "银行"},
        ],
    ).write_parquet(builtin_dir / "part.parquet")

    custom = ExtConfig(
        id="alice_private",
        label="Alice 私有表",
        mode="snapshot",
        fields=[ExtField("symbol", "string", "标的代码")],
    )
    ExtConfigStore(personal_root).upsert(custom)

    request = _request(shared_root, personal_root)
    listed = list_configs(request)["items"]
    config_ids = {item["id"] for item in listed}
    result = dimension_members(
        request,
        "ext_gn_ths",
        field="所属概念",
        value="金融科技",
        limit=10000,
    )

    assert {"ext_gn_ths", "alice_private"} <= config_ids
    public_builtin = next(item for item in listed if item["id"] == "ext_gn_ths")
    assert public_builtin["pull"] is None
    assert "shy313" not in str(public_builtin)
    assert result["total"] == 2
    assert {(row["symbol"], row["name"]) for row in result["rows"]} == {
        ("000001.SZ", "平安银行"),
        ("300059.SZ", "东方财富"),
    }
