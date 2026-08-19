import polars as pl

from app.services import market_overview_builder as builder
from app.services.ext_data import ExtConfig, ExtConfigStore, ExtField
from app.services.ext_presets import get_preset
from app.services.user_context import UserIdentity, reset_current_user, set_current_user


class _Namespace:
    def __init__(self, **values):
        self.__dict__.update(values)


def test_dimension_rank_exposes_member_source_field(monkeypatch, tmp_path):
    config = _Namespace(
        id="teajoin_concepts",
        fields=[_Namespace(name="所属概念", label="所属概念")],
        symbol_map={},
        code_map={},
    )
    monkeypatch.setattr(
        builder,
        "ExtConfigStore",
        lambda _data_dir: _Namespace(load_all=lambda: [config]),
    )
    monkeypatch.setattr(
        builder,
        "_read_ext_rows",
        lambda _data_dir, _config, _field: [
            {"symbol": "000001.SZ", "所属概念": "人工智能"},
        ],
    )

    repo = _Namespace(store=_Namespace(data_dir=tmp_path))
    rows = [
        {
            "symbol": "000001.SZ",
            "name": "平安银行",
            "change_pct": 0.05,
            "amount": 100.0,
        },
    ]

    result = builder._dimension_rank(rows, repo, "concept")

    assert result["leading"][0]["source_field"] == "teajoin_concepts.所属概念"


def test_dimension_rank_reads_builtin_data_from_shared_root_for_logged_in_user(tmp_path):
    shared_root = tmp_path / "shared"
    personal_root = tmp_path / "users" / "alice"
    shared_root.mkdir(parents=True)
    personal_root.mkdir(parents=True)

    config = get_preset("ext_gn_ths")
    assert config is not None
    ExtConfigStore(shared_root).upsert(config)
    data_dir = shared_root / "ext_data" / config.id
    pl.DataFrame([
        {"symbol": "000001.SZ", "股票代码": "000001.SZ", "所属概念": "人工智能"},
    ]).write_parquet(data_dir / "part.parquet")

    repo = _Namespace(store=_Namespace(data_dir=shared_root))
    rows = [{
        "symbol": "000001.SZ",
        "name": "平安银行",
        "change_pct": 0.05,
        "amount": 100.0,
    }]
    tokens = set_current_user(
        UserIdentity(id="alice", name="Alice", phone="masked"),
        personal_root,
    )
    try:
        result = builder._dimension_rank(rows, repo, "concept")
    finally:
        reset_current_user(tokens)

    assert result["leading"][0]["name"] == "人工智能"


def test_dimension_rank_keeps_custom_extension_data_in_current_user_workspace(tmp_path):
    shared_root = tmp_path / "shared"
    personal_root = tmp_path / "users" / "alice"
    shared_root.mkdir(parents=True)
    personal_root.mkdir(parents=True)

    fields = [
        ExtField("symbol", "string", "标的代码"),
        ExtField("所属概念", "string", "所属概念"),
    ]
    shared_config = ExtConfig(
        id="shared_custom",
        label="共享自定义表",
        mode="snapshot",
        fields=fields,
    )
    personal_config = ExtConfig(
        id="alice_custom",
        label="Alice 私有表",
        mode="snapshot",
        fields=fields,
    )
    ExtConfigStore(shared_root).upsert(shared_config)
    ExtConfigStore(personal_root).upsert(personal_config)
    pl.DataFrame([
        {"symbol": "000001.SZ", "所属概念": "共享外部表"},
    ]).write_parquet(shared_root / "ext_data" / shared_config.id / "part.parquet")
    pl.DataFrame([
        {"symbol": "000001.SZ", "所属概念": "Alice私有概念"},
    ]).write_parquet(personal_root / "ext_data" / personal_config.id / "part.parquet")

    repo = _Namespace(store=_Namespace(data_dir=shared_root))
    rows = [{
        "symbol": "000001.SZ",
        "name": "平安银行",
        "change_pct": 0.05,
        "amount": 100.0,
    }]
    tokens = set_current_user(
        UserIdentity(id="alice", name="Alice", phone="masked"),
        personal_root,
    )
    try:
        result = builder._dimension_rank(rows, repo, "concept")
    finally:
        reset_current_user(tokens)

    assert [item["name"] for item in result["leading"]] == ["Alice私有概念"]
    assert result["leading"][0]["source_field"] == "alice_custom.所属概念"
