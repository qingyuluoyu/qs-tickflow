"""游资放量突破: 趋势确认, 放量和 60 日新高同时满足。"""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    matrix_feature,
)
from app.backtest.matrix import valid_shift as shift

META = {
    "id": "hot_money_breakout",
    "status": "retired",
    "retired_reason": "retired after unified six-month return fell below -40%; source kept for legacy compatibility",
    "name": "游资放量突破",
    "description": "趋势向上且接近60日新高, 放量突破后次日开盘跟随; 不追一字涨停。",
    "tags": ["游资", "突破", "放量", "趋势"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "min_change",
            "label": "最低涨幅(%)",
            "type": "float",
            "default": 2.5,
            "min": 0.5,
            "max": 10.0,
            "step": 0.5,
        },
        {
            "id": "min_vol_ratio",
            "label": "最低量比",
            "type": "float",
            "default": 1.5,
            "min": 0.8,
            "max": 5.0,
            "step": 0.1,
        },
        {
            "id": "breakout_tolerance",
            "label": "距60日高点允许回撤(%)",
            "type": "float",
            "default": 1.0,
            "min": 0.0,
            "max": 5.0,
            "step": 0.5,
        },
        {
            "id": "min_momentum_5d",
            "label": "5日最低动量(%)",
            "type": "float",
            "default": 3.0,
            "min": 0.0,
            "max": 20.0,
            "step": 0.5,
        },
        {
            "id": "require_trend",
            "label": "要求站上MA20和MA60",
            "type": "bool",
            "default": True,
        },
    ],
    "scoring": {"momentum_20d": 0.4, "vol_ratio_5d": 0.3, "change_pct": 0.3},
    "order_by": "score",
    "descending": True,
    "limit": 50,
    "research_only": True,
    "validation_status": "待更长样本验证",
    "risk_note": "研究型突破策略; 涨停无法成交时由撮合器拒绝, 不代表可买入。",
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_hot_money_breakout"]
EXIT_SIGNALS = ["signal_ma20_breakdown"]
STOP_LOSS = -0.07
MAX_HOLD_DAYS = 8
ALERTS = []


class HotMoneyBreakoutMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "close", "volume", "raw_close"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 60

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        change = matrix_feature(market, "raw_change_pct")
        momentum_5d = matrix_feature(market, "momentum_5d")
        entry = (
            (market.close > market.open)
            & (change >= float(params.get("min_change", 2.5)) / 100.0)
            & (momentum_5d >= float(params.get("min_momentum_5d", 3.0)) / 100.0)
            & (
                market.close
                >= matrix_feature(market, "high_60d")
                * (1.0 - float(params.get("breakout_tolerance", 1.0)) / 100.0)
            )
            & (
                matrix_feature(market, "vol_ratio_5d")
                >= float(params.get("min_vol_ratio", 1.5))
            )
        )
        if params.get("require_trend", True):
            entry &= (market.close > matrix_feature(market, "ma20")) & (
                matrix_feature(market, "ma20") > matrix_feature(market, "ma60")
            )
        ma20 = matrix_feature(market, "ma20")
        exit_ = (market.close < ma20) & (shift(market.close, 1) >= shift(ma20, 1))
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_hot_money_breakout",),
            exit_signal_ids=("signal_ma20_breakdown",),
        )


MATRIX_STRATEGY = HotMoneyBreakoutMatrixStrategy()
