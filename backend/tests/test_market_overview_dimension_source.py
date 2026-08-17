from app.services import market_overview_builder as builder


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
