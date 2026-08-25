"""Capped martingale sizing for research-only backtests."""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    matrix_feature,
)
from app.backtest.matrix import valid_shift as shift

META = {
    "id": "martingale_capped",
    "name": "受限马丁格尔",
    "description": "RSI超卖后的反弹候选; 亏损后按有限层级增加下一笔仓位, 盈利即重置",
    "tags": ["马丁格尔", "反转", "风险封顶"],
    "asset_types": ["stock", "etf"],
    "timeframes": ["1d"],
    "position_sizing": "martingale_capped",
    "research_only": True,
    "validation_status": "待样本外验证",
    "risk_note": (
        "这是交易之间的有限递增仓位, 不是同一标的无限补仓; 最多 2 层, "
        "仍受现金、最大持仓和总暴露约束, 不能消除连续亏损风险。"
    ),
    "params": [
        {"id": "rsi_max", "label": "RSI上限", "type": "float", "default": 25.0, "min": 10.0, "max": 45.0, "step": 1.0},
        {"id": "vol_ratio_min", "label": "最低量比", "type": "float", "default": 1.2, "min": 0.5, "max": 5.0, "step": 0.1},
        {"id": "base_position_pct", "label": "基础仓位占比", "type": "float", "default": 0.1, "min": 0.02, "max": 0.5, "step": 0.01},
        {"id": "multiplier", "label": "亏损后加仓倍数", "type": "float", "default": 2.0, "min": 1.0, "max": 3.0, "step": 0.1},
        {"id": "max_levels", "label": "最大递增层数", "type": "int", "default": 2, "min": 0, "max": 4, "step": 1},
    ],
    "scoring": {"rsi_14": 0.4, "vol_ratio_5d": 0.3, "momentum_5d": 0.3},
    "order_by": "score",
    "descending": True,
    "limit": 50,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_martingale_reversal"]
EXIT_SIGNALS = ["signal_ma20_breakdown"]
STOP_LOSS = -0.04
MAX_HOLD_DAYS = 8
ALERTS = []


class CappedMartingaleMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "close", "volume"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 60

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        ma5 = matrix_feature(market, "ma5")
        ma20 = matrix_feature(market, "ma20")
        entry = (
            (matrix_feature(market, "rsi_14") <= float(params.get("rsi_max", 25.0)))
            & (market.close > market.open)
            & (market.close > ma5)
            & (matrix_feature(market, "vol_ratio_5d") >= float(params.get("vol_ratio_min", 1.2)))
        )
        exit_ = (market.close < ma20) & (shift(market.close, 1) >= shift(ma20, 1))
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_martingale_reversal",),
            exit_signal_ids=("signal_ma20_breakdown",),
        )


MATRIX_STRATEGY = CappedMartingaleMatrixStrategy()
