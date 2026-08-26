"""涨停反包: 前一日有涨停动能, 次日放量转强但不追锁死涨停。"""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    matrix_feature,
)
from app.backtest.matrix import valid_shift as shift

META = {
    "id": "limit_up_reclaim",
    "status": "retired",
    "retired_reason": "retired after two rolling six-month audits showed persistent negative return and negative risk-adjusted performance; source kept for legacy compatibility",
    "name": "涨停反包",
    "description": "前一日涨停动能后, 今日放量收阳并重新站上短均线; 避开封死涨停。",
    "tags": ["游资", "反包", "涨停", "短线"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "min_previous_boards",
            "label": "前一日最少连板数",
            "type": "int",
            "default": 1,
            "min": 1,
            "max": 5,
            "step": 1,
        },
        {
            "id": "min_change",
            "label": "今日最低涨幅(%)",
            "type": "float",
            "default": 2.0,
            "min": 0.5,
            "max": 10.0,
            "step": 0.5,
        },
        {
            "id": "limit_gap",
            "label": "距涨停保留空间(%)",
            "type": "float",
            "default": 1.0,
            "min": 0.2,
            "max": 5.0,
            "step": 0.2,
        },
        {
            "id": "min_vol_ratio",
            "label": "最低量比",
            "type": "float",
            "default": 1.0,
            "min": 0.5,
            "max": 4.0,
            "step": 0.1,
        },
    ],
    "scoring": {"consecutive_limit_ups": 0.4, "change_pct": 0.3, "vol_ratio_5d": 0.3},
    "order_by": "score",
    "descending": True,
    "limit": 50,
    "research_only": True,
    "validation_status": "待更长样本验证",
    "risk_note": "反包失败的隔夜跳空风险较高, 止损和持仓上限必须保留。",
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_limit_up_reclaim"]
EXIT_SIGNALS = ["signal_ma10_breakdown"]
STOP_LOSS = -0.06
MAX_HOLD_DAYS = 5
ALERTS = []


class LimitUpReclaimMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({
            "open",
            "close",
            "volume",
            "raw_close",
            "consecutive_limit_ups",
            "price_limit_pct",
        })

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 60

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        change = matrix_feature(market, "raw_change_pct")
        previous_boards = shift(matrix_feature(market, "consecutive_limit_ups"), 1)
        limit_pct = matrix_feature(market, "price_limit_pct")
        entry = (
            (previous_boards >= int(params.get("min_previous_boards", 1)))
            & (market.close > market.open)
            & (change >= float(params.get("min_change", 2.0)) / 100.0)
            & (change < limit_pct - float(params.get("limit_gap", 1.0)) / 100.0)
            & (matrix_feature(market, "vol_ratio_5d") >= float(params.get("min_vol_ratio", 1.0)))
            & (market.close > matrix_feature(market, "ma5"))
        )
        ma10 = matrix_feature(market, "ma10")
        exit_ = (market.close < ma10) & (shift(market.close, 1) >= shift(ma10, 1))
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_limit_up_reclaim",),
            exit_signal_ids=("signal_ma10_breakdown",),
        )


MATRIX_STRATEGY = LimitUpReclaimMatrixStrategy()
