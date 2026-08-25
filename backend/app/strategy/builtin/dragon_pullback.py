"""龙头回踩再起: 连板后缩量回踩, 出现阳线再参与。"""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    matrix_feature,
)
from app.backtest.matrix import valid_shift as shift

META = {
    "id": "dragon_pullback",
    "name": "龙头回踩再起",
    "description": "连板动能后回踩均线、量能收缩, 重新收阳确认再参与。",
    "tags": ["游资", "龙头", "回踩", "二波"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "min_previous_boards",
            "label": "前期最少连板数",
            "type": "int",
            "default": 1,
            "min": 1,
            "max": 6,
            "step": 1,
        },
        {
            "id": "pullback_band",
            "label": "距MA20回踩上限(%)",
            "type": "float",
            "default": 5.0,
            "min": 0.5,
            "max": 10.0,
            "step": 0.5,
        },
        {
            "id": "min_rebound",
            "label": "反弹最低涨幅(%)",
            "type": "float",
            "default": 2.0,
            "min": 0.2,
            "max": 8.0,
            "step": 0.2,
        },
        {
            "id": "max_vol_ratio",
            "label": "回踩最大量比",
            "type": "float",
            "default": 1.5,
            "min": 0.5,
            "max": 4.0,
            "step": 0.1,
        },
        {
            "id": "min_momentum_20d",
            "label": "20日最低动量(%)",
            "type": "float",
            "default": 3.0,
            "min": 0.0,
            "max": 30.0,
            "step": 0.5,
        },
    ],
    "scoring": {"momentum_20d": 0.4, "consecutive_limit_ups": 0.3, "change_pct": 0.3},
    "order_by": "score",
    "descending": True,
    "limit": 50,
    "research_only": True,
    "validation_status": "待更长样本验证",
    "risk_note": "二波策略依赖题材持续性, 回踩失守MA20应退出, 不采用加仓摊平。",
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_dragon_pullback"]
EXIT_SIGNALS = ["signal_ma20_breakdown"]
STOP_LOSS = -0.07
MAX_HOLD_DAYS = 10
ALERTS = []


class DragonPullbackMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "close", "volume", "raw_close", "consecutive_limit_ups"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 60

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        ma20 = matrix_feature(market, "ma20")
        previous_ma20 = shift(ma20, 1)
        previous_boards = shift(matrix_feature(market, "consecutive_limit_ups"), 1)
        change = matrix_feature(market, "raw_change_pct")
        entry = (
            (previous_boards >= int(params.get("min_previous_boards", 1)))
            & (market.close > market.open)
            & (change >= float(params.get("min_rebound", 1.0)) / 100.0)
            & (market.close <= ma20 * (1.0 + float(params.get("pullback_band", 5.0)) / 100.0))
            & (matrix_feature(market, "vol_ratio_5d") <= float(params.get("max_vol_ratio", 1.5)))
            & (
                matrix_feature(market, "momentum_20d")
                >= float(params.get("min_momentum_20d", 3.0)) / 100.0
            )
            & (shift(market.close, 1) >= previous_ma20)
        )
        exit_ = (market.close < ma20) & (shift(market.close, 1) >= previous_ma20)
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_dragon_pullback",),
            exit_signal_ids=("signal_ma20_breakdown",),
        )


MATRIX_STRATEGY = DragonPullbackMatrixStrategy()
