"""Technical indicators computed with pandas. Each takes a DataFrame with
open/high/low/close columns (or a close Series) and returns Series."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(100.0).where(loss.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0):
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std(ddof=0)
    return mid - k * sd, mid, mid + k * sd


def stochastic(df: pd.DataFrame, n: int = 14, d: int = 3):
    lo = df["low"].rolling(n).min()
    hi = df["high"].rolling(n).max()
    k = 100 * (df["close"] - lo) / (hi - lo).replace(0, np.nan)
    return k, k.rolling(d).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift()
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adx(df: pd.DataFrame, n: int = 14):
    """Returns (adx, +DI, -DI). ADX above ~25 means a trending market."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = atr(df, n)
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / tr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean(), plus_di, minus_di


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0) -> pd.Series:
    """Supertrend direction: +1 uptrend, -1 downtrend."""
    a = atr(df, n).to_numpy()
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy()
    c = df["close"].to_numpy()
    upper, lower = hl2 + mult * a, hl2 - mult * a
    fu, fl = upper.copy(), lower.copy()
    direction = np.ones(len(df))
    for i in range(1, len(df)):
        fu[i] = upper[i] if upper[i] < fu[i - 1] or c[i - 1] > fu[i - 1] else fu[i - 1]
        fl[i] = lower[i] if lower[i] > fl[i - 1] or c[i - 1] < fl[i - 1] else fl[i - 1]
        if c[i] > fu[i - 1]:
            direction[i] = 1
        elif c[i] < fl[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
    return pd.Series(direction, index=df.index)


def cci(df: pd.DataFrame, n: int = 20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    ma = tp.rolling(n).mean()
    md = tp.rolling(n).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - ma) / (0.015 * md.replace(0, np.nan))


def williams_r(df: pd.DataFrame, n: int = 14) -> pd.Series:
    hi, lo = df["high"].rolling(n).max(), df["low"].rolling(n).min()
    return -100 * (hi - df["close"]) / (hi - lo).replace(0, np.nan)


def heikin_ashi_trend(df: pd.DataFrame) -> pd.Series:
    """+1 when the Heikin Ashi candle is green, -1 when red."""
    ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
    ha_open = ha_close.copy()
    ha_open.iloc[0] = (df["open"].iloc[0] + df["close"].iloc[0]) / 2
    vals = ha_open.to_numpy(copy=True)
    hc = ha_close.to_numpy()
    for i in range(1, len(df)):
        vals[i] = (vals[i - 1] + hc[i - 1]) / 2
    return np.sign(pd.Series(hc - vals, index=df.index))


def add_all(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    c = out["close"]
    out["ema9"], out["ema21"], out["ema50"] = ema(c, 9), ema(c, 21), ema(c, 50)
    out["rsi"] = rsi(c)
    out["macd"], out["macd_signal"], out["macd_hist"] = macd(c)
    out["bb_low"], out["bb_mid"], out["bb_high"] = bollinger(c)
    out["stoch_k"], out["stoch_d"] = stochastic(out)
    out["atr"] = atr(out)
    out["adx"], out["plus_di"], out["minus_di"] = adx(out)
    out["supertrend"] = supertrend(out)
    out["cci"] = cci(out)
    out["willr"] = williams_r(out)
    out["ha_trend"] = heikin_ashi_trend(out)
    # volatility percentile: how today's ATR compares to the last 100 candles
    rel = out["atr"] / c
    out["atr_pct"] = rel.rolling(100, min_periods=30).rank(pct=True)
    return out
