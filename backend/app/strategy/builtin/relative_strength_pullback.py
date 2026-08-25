"""相对强势回踩 — 中长期趋势向上时买入 MA20 附近的收复。"""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    matrix_feature,
)
from app.backtest.matrix import valid_shift as shift

META = {
    "id": "relative_strength_pullback",
    "name": "相对强势回踩",
    "description": "MA60 上方、20/60日动量为正, 回踩 MA20 后重新收强",
    "tags": ["趋势", "回踩", "动量"],
    "asset_types": ["stock", "etf"],
    "timeframes": ["1d"],
    "params": [
        {"id": "ma_proximity", "label": "MA20偏离度%", "type": "float", "default": 2.0, "min": 0.5, "max": 6.0, "step": 0.5},
        {"id": "momentum_20d_min", "label": "最低20日动量%", "type": "float", "default": 0.0, "min": -20.0, "max": 30.0, "step": 1.0},
        {"id": "momentum_60d_min", "label": "最低60日动量%", "type": "float", "default": 0.0, "min": -30.0, "max": 60.0, "step": 1.0},
        {"id": "require_bullish_candle", "label": "要求收阳", "type": "bool", "default": True},
    ],
    "scoring": {"momentum_60d": 0.4, "momentum_20d": 0.3, "change_pct": 0.3},
    "order_by": "score",
    "descending": True,
    "limit": 100,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_ma20_breakout"]
EXIT_SIGNALS = ["signal_ma20_breakdown", "signal_ma_dead_5_20"]
STOP_LOSS = -0.06
MAX_HOLD_DAYS = 20
ALERTS = []


class RelativeStrengthPullbackMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "close"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 60

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        ma5 = matrix_feature(market, "ma5")
        ma20 = matrix_feature(market, "ma20")
        ma60 = matrix_feature(market, "ma60")
        momentum_20d = matrix_feature(market, "momentum_20d")
        momentum_60d = matrix_feature(market, "momentum_60d")
        proximity = float(params.get("ma_proximity", 2.0)) / 100.0
        entry = (
            (market.close > ma60)
            & (ma20 > ma60)
            & (market.close >= ma20 * (1.0 - proximity))
            & (market.close <= ma20 * (1.0 + proximity))
            & (momentum_20d >= float(params.get("momentum_20d_min", 0.0)) / 100.0)
            & (momentum_60d >= float(params.get("momentum_60d_min", 0.0)) / 100.0)
        )
        if params.get("require_bullish_candle", True):
            entry &= market.close > market.open
        exit_ = (
            ((market.close < ma20) & (shift(market.close, 1) >= shift(ma20, 1)))
            | ((ma5 < ma20) & (shift(ma5, 1) >= shift(ma20, 1)))
        )
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_ma20_breakout",),
            exit_signal_ids=("signal_ma20_breakdown", "signal_ma_dead_5_20"),
        )


MATRIX_STRATEGY = RelativeStrengthPullbackMatrixStrategy()
