"""sina_snapshot: 新浪快照解析与批量拉取(网络层打桩)。"""

from __future__ import annotations

from app.services import sina_snapshot


def _line(code: str, payload: str) -> str:
    return f'var hq_str_{code}="{payload}";'


# 名称,开,昨收,最新,高,低,买,卖,量,额,... (30 字段后到日期/时间)
_STOCK = (
    "平安银行,11.200,11.110,11.100,11.220,11.070,11.100,11.110,"
    "92904344,1031951473.980," + ",".join(["0"] * 20) + ",2026-08-17,15:35:31,00,"
)
_INDEX = (
    "上证指数,3930.1044,3927.1764,3982.6535,3983.5066,3924.4738,0,0,"
    "489834027,1112818620627," + ",".join(["0"] * 20) + ",2026-08-17,15:05:00,00,"
)
_HALT = (
    "停牌股,0.000,0.000,0.000,0.000,0.000,0.000,0.000,"
    "0,0.000," + ",".join(["0"] * 20) + ",2026-08-17,15:35:31,00,"
)


class TestParseLine:
    def test_stock_volume_divided_to_lots(self):
        row = sina_snapshot._parse_line(_line("sz000001", _STOCK), is_index=False)
        assert row is not None
        assert row["open"] == 11.2
        assert row["close"] == 11.1
        assert row["high"] == 11.22
        assert row["low"] == 11.07
        # 新浪股票成交量单位为股, canonical 存储为手
        assert row["volume"] == 929043.44
        assert row["amount"] == 1031951473.98
        assert row["date"] == "2026-08-17"

    def test_index_volume_kept(self):
        row = sina_snapshot._parse_line(_line("sh000001", _INDEX), is_index=True)
        assert row is not None
        # 指数成交量与本地存储同刻度, 不除 100
        assert row["volume"] == 489834027
        assert row["close"] == 3982.6535

    def test_empty_payload_dropped(self):
        assert sina_snapshot._parse_line('var hq_str_bj430047="";', is_index=False) is None

    def test_malformed_dropped(self):
        assert sina_snapshot._parse_line("garbage", is_index=False) is None
        assert sina_snapshot._parse_line(_line("sz000001", "a,b,c"), is_index=False) is None


class TestFetchSpotDaily:
    def test_batch_fetch_and_symbol_mapping(self, monkeypatch):
        payloads = {
            "sz000001": _STOCK,
            "bj920001": _STOCK,
            "sh600519": _HALT,  # 全 0(停牌) 仍返回行, 由调用方 filter_halt_days 过滤
        }

        def fake_get(url, timeout=10.0):
            out = []
            for code in url.split("list=", 1)[1].split(","):
                if code in payloads:
                    out.append(_line(code, payloads[code]))
            return "\n".join(out)

        monkeypatch.setattr(sina_snapshot, "_get", fake_get)
        monkeypatch.setattr(sina_snapshot.time, "sleep", lambda *_a: None)

        df = sina_snapshot.fetch_spot_daily(["000001.SZ", "920001.BJ", "600519.SH", "999999.XX"])
        assert df.height == 3
        got = {r["symbol"]: r for r in df.to_dicts()}
        assert set(got) == {"000001.SZ", "920001.BJ", "600519.SH"}
        assert got["000001.SZ"]["volume"] == 929043.44
        # 无法映射后缀的代码被跳过, 不会发请求也不会出现在结果里
        assert "999999.XX" not in got

    def test_all_batches_failed_returns_empty(self, monkeypatch):
        def boom(url, timeout=10.0):
            raise ConnectionError("rst")

        monkeypatch.setattr(sina_snapshot, "_get", boom)
        monkeypatch.setattr(sina_snapshot.time, "sleep", lambda *_a: None)
        df = sina_snapshot.fetch_spot_daily(["000001.SZ"])
        assert df.is_empty()

    def test_empty_universe_returns_empty(self):
        assert sina_snapshot.fetch_spot_daily([]).is_empty()


class TestMarketSpot:
    def test_parse_line_keeps_name_and_prev_close(self):
        row = sina_snapshot._parse_line(_line("sz000001", _STOCK), is_index=False)
        assert row is not None
        assert row["name"] == "平安银行"
        assert row["prev_close"] == 11.11

    def test_fetch_market_spot_keeps_prev_close_and_name(self, monkeypatch):
        def fake_get(url, timeout=10.0):
            return _line("sz000001", _STOCK)

        monkeypatch.setattr(sina_snapshot, "_get", fake_get)
        monkeypatch.setattr(sina_snapshot.time, "sleep", lambda *_a: None)

        df = sina_snapshot.fetch_market_spot(["000001.SZ"])

        assert {"symbol", "date", "open", "high", "low", "close",
                "prev_close", "volume", "amount", "name"}.issubset(df.columns)
        assert df["prev_close"].item() == 11.11
        assert df["name"].item() == "平安银行"

    def test_fetch_spot_daily_stays_canonical(self, monkeypatch):
        # parquet 落盘调用方的列契约不变: 不携带 prev_close/name。
        def fake_get(url, timeout=10.0):
            return _line("sz000001", _STOCK)

        monkeypatch.setattr(sina_snapshot, "_get", fake_get)
        monkeypatch.setattr(sina_snapshot.time, "sleep", lambda *_a: None)

        df = sina_snapshot.fetch_spot_daily(["000001.SZ"])

        assert df.columns == [
            "symbol", "date", "open", "high", "low", "close", "volume", "amount",
        ]

    def test_fetch_market_spot_empty_universe_returns_empty(self):
        assert sina_snapshot.fetch_market_spot([]).is_empty()
