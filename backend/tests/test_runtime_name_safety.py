from datetime import date
from pathlib import Path
from types import SimpleNamespace

import polars as pl

from app.api import screener as screener_api
from app.indicators import pipeline


def test_ext_value_map_reads_the_explicit_user_workspace(monkeypatch, tmp_path: Path) -> None:
    shared_root = tmp_path / "shared"
    user_root = tmp_path / "users" / "alice"
    captured: dict[str, Path] = {}
    config = SimpleNamespace(id="private", fields=[])

    class _ConfigStore:
        def __init__(self, data_dir: Path) -> None:
            captured["data_dir"] = data_dir

        def load_all(self) -> list[object]:
            return [config]

    monkeypatch.setattr("app.services.ext_data.ExtConfigStore", _ConfigStore)
    monkeypatch.setattr(screener_api, "_ext_parquet_signature", lambda *_args: None)
    monkeypatch.setattr(
        "app.api.ext_data._read_ext_dataframe",
        lambda _config, _data_dir: (
            pl.DataFrame({"symbol": ["000001.SZ"], "tag": ["用户标签"]}),
            None,
        ),
    )
    repo = SimpleNamespace(store=SimpleNamespace(data_dir=shared_root, db=object()))

    result = screener_api._load_ext_value_maps(
        repo,
        "private.tag",
        data_dir=user_root,
    )

    assert captured["data_dir"] == user_root
    assert result == {"private__tag": {"000001.SZ": "用户标签"}}


def test_recent_enriched_history_can_be_loaded(tmp_path: Path) -> None:
    enriched = tmp_path / "enriched"
    partition = enriched / f"date={date.today().isoformat()}"
    partition.mkdir(parents=True)
    pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "date": [date.today()],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [100.0],
            "amount": [1000.0],
            "raw_close": [10.5],
            "raw_high": [11.0],
            "raw_low": [9.0],
            "turnover_rate": [0.1],
            "consecutive_limit_ups": [0],
            "consecutive_limit_downs": [0],
            "quote_ts": [0],
        }
    ).write_parquet(partition / "part.parquet")

    result = pipeline._load_recent_history(enriched, ["000001.SZ"], days=5)

    assert result.height == 1
    assert result["symbol"].to_list() == ["000001.SZ"]
