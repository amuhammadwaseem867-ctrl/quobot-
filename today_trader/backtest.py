"""Checks how often past signals would have been right.

For every candle where |score| >= threshold, look `expiry` candles ahead and
see whether price closed in the suggested direction. This is the honest check:
binary options typically pay ~80-90%, so you need a win rate well above
roughly 53-56% just to break even.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .signals import DEFAULT_THRESHOLD, score_frame


@dataclass
class BacktestResult:
    symbol: str
    signals: int
    wins: int
    payout: float

    @property
    def win_rate(self) -> float:
        return self.wins / self.signals if self.signals else float("nan")

    @property
    def breakeven(self) -> float:
        return 1 / (1 + self.payout)

    @property
    def net_units(self) -> float:
        """Profit in stake units if every signal was taken at a flat stake."""
        return self.wins * self.payout - (self.signals - self.wins)


def backtest(df: pd.DataFrame, symbol: str, expiry: int = 1,
             threshold: float = DEFAULT_THRESHOLD, payout: float = 0.85,
             crypto: bool = False, use_filters: bool = True) -> BacktestResult:
    d = score_frame(df, crypto=crypto, use_filters=use_filters).iloc[100:]  # skip indicator warm-up
    future = d["close"].shift(-expiry)
    d = d.assign(future=future).dropna(subset=["future"])
    call = d["score"] >= threshold
    put = d["score"] <= -threshold
    wins = ((call & (d["future"] > d["close"])) | (put & (d["future"] < d["close"]))).sum()
    return BacktestResult(symbol, int((call | put).sum()), int(wins), payout)
