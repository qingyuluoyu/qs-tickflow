"""受限逆势反转 - 作为马丁格尔的风险对照, 不实现无限补仓。"""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    matrix_feature,
)
from app.backtest.matrix import valid_shift as shift

META = {
    "id": "risk_capped_reversal",
    "name": "受限逆势反转",
    "description": "RSI 超卖、接近60日低位后收复 MA5 的单次反转信号; 不做无限马丁加仓",
    "tags": ["反转", "RSI", "风险封顶", "马丁格尔对照"],
    "asset_types": ["stock", "etf"],
    "timeframes": ["1d"],
    "params": [
        {"id": "rsi_max", "label": "RSI上限", "type": "float", "default": 28.0, "min": 10.0, "max": 45.0, "step": 1.0},
        {"id": "low_proximity", "label": "距60日低点空间%", "type": "float", "default": 3.0, "min": 0.5, "max": 10.0, "step": 0.5},
        {"id": "use_volume_filter", "label": "启用量比过滤", "type": "bool", "default": True},
        {"id": "vol_ratio_min", "label": "最低量比", "type": "float", "default": 1.2, "min": 0.5, "max": 4.0, "step": 0.1},
    ],
    "scoring": {"change_pct": 0.4, "rsi_14": 0.3, "momentum_5d": 0.3},
    "order_by": "score",
    "descending": True,
    "limit": 100,
    "risk_note": "本策略是单次入场的风险封顶反转, 不是无限加仓马丁格尔; 真正分层补仓需要独立撮合契约。",
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_n_day_low"]
EXIT_SIGNALS = ["signal_ma20_breakdown"]
STOP_LOSS = -0.04
MAX_HOLD_DAYS = 10
ALERTS = []


class RiskCappedReversalMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "close"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 60

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        low_60d = matrix_feature(market, "low_60d")
        ma5 = matrix_feature(market, "ma5")
        ma20 = matrix_feature(market, "ma20")
        close_above_low = market.close <= low_60d * (1.0 + float(params.get("low_proximity", 3.0)) / 100.0)
        entry = (
            (matrix_feature(market, "rsi_14") < float(params.get("rsi_max", 28.0)))
            & close_above_low
            & (market.close > ma5)
            & (market.close > market.open)
        )
        if params.get("use_volume_filter", True):
            entry &= matrix_feature(market, "vol_ratio_5d") >= float(params.get("vol_ratio_min", 1.2))
        exit_ = (market.close < ma20) & (shift(market.close, 1) >= shift(ma20, 1))
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_n_day_low",),
            exit_signal_ids=("signal_ma20_breakdown",),
        )


MATRIX_STRATEGY = RiskCappedReversalMatrixStrategy()
