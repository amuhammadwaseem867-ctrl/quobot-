"""Support / resistance levels and RSI divergence.

Swing highs and lows are pivots with `k` lower highs (or higher lows) on each
side. A pivot is only *known* k candles after it happens, so every value here
is shifted by k: the bot never uses a level it could not have seen at the time
(the "look-ahead bias" mistake that makes many backtests look too good).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def pivots(df: pd.DataFrame, k: int = 3):
    """Boolean Series (swing_high, swing_low), confirmed k candles later."""
    h, l = df["high"], df["low"]
    win = 2 * k + 1
    sh = h == h.rolling(win, center=True).max()
    sl = l == l.rolling(win, center=True).min()
    # confirmation delay: a pivot at t is known at t+k
    return sh.shift(k, fill_value=False), sl.shift(k, fill_value=False)


def nearest_levels(df: pd.DataFrame, k: int = 3, lookback: int = 150, tol_atr: float = 0.5,
                   atr: pd.Series | None = None):
    """Support and resistance for the LAST candle: clusters of recent swing
    points, returned as (supports, resistances), each a list of (price, touches)
    sorted nearest first."""
    d = df.tail(lookback + k)
    h, l = d["high"], d["low"]
    win = 2 * k + 1
    sh = (h == h.rolling(win, center=True).max()).iloc[:-k]
    sl = (l == l.rolling(win, center=True).min()).iloc[:-k]
    points = np.r_[h.iloc[:-k][sh].values, l.iloc[:-k][sl].values]
    if len(points) == 0:
        return [], []
    tol = float(atr.iloc[-1]) * tol_atr if atr is not None else float(d["close"].iloc[-1]) * 0.0005
    points.sort()
    clusters: list[list[float]] = [[points[0]]]
    for p in points[1:]:
        if p - np.mean(clusters[-1]) <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    levels = [(float(np.mean(cl)), len(cl)) for cl in clusters]
    price = float(d["close"].iloc[-1])
    sup = sorted([lv for lv in levels if lv[0] < price], key=lambda x: price - x[0])
    res = sorted([lv for lv in levels if lv[0] >= price], key=lambda x: x[0] - price)
    return sup, res


def level_vote(df: pd.DataFrame, atr: pd.Series, k: int = 3, lookback: int = 60, near_atr: float = 0.6) -> pd.Series:
    """Rolling S/R vote for every candle, using only confirmed pivots:
    +1 bouncing off support (low touched it, close back above),
    -1 rejected at resistance, +1/-1 for a clean close-through breakout."""
    sh, sl = pivots(df, k)
    # price of the most recent confirmed swing high / low (as known at each candle)
    last_high = df["high"].shift(k).where(sh).ffill()
    last_low = df["low"].shift(k).where(sl).ffill()
    near = near_atr * atr
    h, l, c = df["high"], df["low"], df["close"]
    bounce = (l <= last_low + near) & (c > last_low) & (c > df["open"])
    reject = (h >= last_high - near) & (c < last_high) & (c < df["open"])
    breakout_up = (c > last_high + 0.2 * atr) & (c.shift() <= last_high)
    breakout_dn = (c < last_low - 0.2 * atr) & (c.shift() >= last_low)
    vote = bounce.astype(int) - reject.astype(int) + breakout_up.astype(int) - breakout_dn.astype(int)
    return vote.clip(-1, 1)


def rsi_divergence(df: pd.DataFrame, rsi: pd.Series, k: int = 3) -> pd.Series:
    """+1 bullish divergence (price lower low, RSI higher low),
    -1 bearish divergence (price higher high, RSI lower high).
    Compares the two most recent confirmed swing points; the signal lasts a few
    candles after the second pivot is confirmed."""
    sh, sl = pivots(df, k)

    def diverge(mask, price, osc, bullish):
        pts = pd.DataFrame({"p": price.shift(k)[mask], "r": osc.shift(k)[mask]}).dropna()
        prev = pts.shift()
        if bullish:
            hit = (pts["p"] < prev["p"]) & (pts["r"] > prev["r"])
        else:
            hit = (pts["p"] > prev["p"]) & (pts["r"] < prev["r"])
        return hit.reindex(df.index, fill_value=False)

    bull = diverge(sl, df["low"], rsi, True)
    bear = diverge(sh, df["high"], rsi, False)
    raw = bull.astype(int) - bear.astype(int)
    # keep the divergence "live" for 3 candles after confirmation
    return raw.replace(0, np.nan).ffill(limit=3).fillna(0).astype(int)
