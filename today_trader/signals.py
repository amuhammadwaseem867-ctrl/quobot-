"""Turns indicator values into a directional bias (CALL / PUT / WAIT).

Each rule votes +1 (up), -1 (down) or 0, with a weight. The weighted sum is
scaled to -100..+100. Trend rules count more when ADX says the market is
trending; reversal rules (RSI, Bollinger, Stochastic extremes) count more when
it is ranging.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .indicators import add_all

DEFAULT_THRESHOLD = 40  # |score| needed before suggesting a direction


@dataclass
class Signal:
    symbol: str
    interval: str
    time: pd.Timestamp
    price: float
    score: float
    direction: str
    regime: str
    reasons: list[str] = field(default_factory=list)
    rsi: float = float("nan")
    adx: float = float("nan")
    atr: float = float("nan")


def score_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Adds `score` (-100..100) and `regime` columns to every row."""
    d = add_all(df)
    trending = d["adx"] > 25

    trend_w = np.where(trending, 1.5, 0.75)
    revert_w = np.where(trending, 0.5, 1.25)

    votes = {
        "ema_stack": (np.sign(d["ema9"] - d["ema21"]), trend_w),
        "ema50": (np.sign(d["close"] - d["ema50"]), trend_w * 0.75),
        "macd": (np.sign(d["macd_hist"]), np.full(len(d), 1.0)),
        "macd_slope": (np.sign(d["macd_hist"].diff()), np.full(len(d), 0.5)),
        "di": (np.sign(d["plus_di"] - d["minus_di"]), trend_w * 0.75),
        "rsi": (np.select([d["rsi"] < 30, d["rsi"] > 70], [1, -1], 0), revert_w),
        "bb": (np.select([d["close"] < d["bb_low"], d["close"] > d["bb_high"]], [1, -1], 0), revert_w),
        "stoch": (
            np.select(
                [(d["stoch_k"] < 20) & (d["stoch_k"] > d["stoch_d"]),
                 (d["stoch_k"] > 80) & (d["stoch_k"] < d["stoch_d"])],
                [1, -1], 0,
            ),
            revert_w,
        ),
    }
    total = sum(np.asarray(v, float) * w for v, w in votes.values())
    max_total = sum(np.asarray(w, float) for _, w in votes.values())
    d["score"] = 100 * total / max_total
    d["regime"] = np.where(trending, "trending", "ranging")
    for name, (v, _) in votes.items():
        d[f"vote_{name}"] = v
    return d


def _reasons(row: pd.Series) -> list[str]:
    r = []
    r.append("EMA 9 above EMA 21 (short-term uptrend)" if row["ema9"] > row["ema21"]
             else "EMA 9 below EMA 21 (short-term downtrend)")
    r.append(f"Price {'above' if row['close'] > row['ema50'] else 'below'} EMA 50")
    r.append(f"MACD histogram {'positive' if row['macd_hist'] > 0 else 'negative'}"
             f" and {'rising' if row['vote_macd_slope'] > 0 else 'falling'}")
    if row["rsi"] < 30:
        r.append(f"RSI {row['rsi']:.0f}: oversold")
    elif row["rsi"] > 70:
        r.append(f"RSI {row['rsi']:.0f}: overbought")
    else:
        r.append(f"RSI {row['rsi']:.0f}: neutral")
    if row["close"] < row["bb_low"]:
        r.append("Close below lower Bollinger band")
    elif row["close"] > row["bb_high"]:
        r.append("Close above upper Bollinger band")
    if row["vote_stoch"] > 0:
        r.append("Stochastic turning up from oversold")
    elif row["vote_stoch"] < 0:
        r.append("Stochastic turning down from overbought")
    r.append(f"ADX {row['adx']:.0f}: {'trending' if row['adx'] > 25 else 'ranging / weak trend'}")
    return r


def direction_for(score: float, threshold: float = DEFAULT_THRESHOLD) -> str:
    if score >= threshold:
        return "CALL (up)"
    if score <= -threshold:
        return "PUT (down)"
    return "WAIT"


def analyze(df: pd.DataFrame, symbol: str, interval: str, threshold: float = DEFAULT_THRESHOLD) -> Signal:
    if len(df) < 60:
        raise ValueError(f"{symbol}: need at least 60 candles, got {len(df)}")
    d = score_frame(df)
    row = d.iloc[-1]
    return Signal(
        symbol=symbol, interval=interval, time=d.index[-1], price=float(row["close"]),
        score=float(row["score"]), direction=direction_for(row["score"], threshold),
        regime=row["regime"], reasons=_reasons(row),
        rsi=float(row["rsi"]), adx=float(row["adx"]), atr=float(row["atr"]),
    )
