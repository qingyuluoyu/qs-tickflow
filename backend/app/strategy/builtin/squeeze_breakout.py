"""波动收缩突破 — 布林带收窄后放量向上突破。"""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    matrix_feature,
)
from app.backtest.matrix import valid_shift as shift

META = {
    "id": "squeeze_breakout",
    "name": "波动收缩突破",
    "description": "布林带收窄后放量突破上轨, 跟随波动扩张",
    "tags": ["波动率", "布林", "突破"],
    "asset_types": ["stock", "etf"],
    "timeframes": ["1d"],
    "params": [
        {"id": "use_bandwidth_filter", "label": "启用布林带宽过滤", "type": "bool", "default": True},
        {"id": "bandwidth_max", "label": "最大布林带宽", "type": "float", "default": 0.12, "min": 0.02, "max": 0.5, "step": 0.01},
        {"id": "use_volume_filter", "label": "启用量比过滤", "type": "bool", "default": True},
        {"id": "vol_ratio_min", "label": "最低量比", "type": "float", "default": 1.5, "min": 0.5, "max": 5.0, "step": 0.1},
        {"id": "require_bullish_candle", "label": "要求收阳", "type": "bool", "default": True},
    ],
    "scoring": {"vol_ratio_5d": 0.4, "momentum_20d": 0.3, "change_pct": 0.3},
    "order_by": "score",
    "descending": True,
    "limit": 100,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_boll_breakout_upper"]
EXIT_SIGNALS = ["signal_ma20_breakdown"]
STOP_LOSS = -0.06
MAX_HOLD_DAYS = 15
ALERTS = []


class SqueezeBreakoutMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "close", "volume"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 60

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        ma20 = matrix_feature(market, "ma20")
        upper = matrix_feature(market, "boll_upper")
        lower = matrix_feature(market, "boll_lower")
        bandwidth = np.divide(
            upper - lower,
            np.maximum(np.abs(ma20), 1e-12),
            out=np.full(market.shape, np.nan, dtype=np.float64),
            where=np.isfinite(upper) & np.isfinite(lower) & np.isfinite(ma20),
        )
        entry = market.close > upper
        if params.get("use_bandwidth_filter", True):
            entry &= bandwidth <= float(params.get("bandwidth_max", 0.12))
        if params.get("use_volume_filter", True):
            entry &= matrix_feature(market, "vol_ratio_5d") >= float(params.get("vol_ratio_min", 1.5))
        if params.get("require_bullish_candle", True):
            entry &= market.close > market.open
        exit_ = (market.close < ma20) & (shift(market.close, 1) >= shift(ma20, 1))
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_boll_breakout_upper",),
            exit_signal_ids=("signal_ma20_breakdown",),
        )


MATRIX_STRATEGY = SqueezeBreakoutMatrixStrategy()
