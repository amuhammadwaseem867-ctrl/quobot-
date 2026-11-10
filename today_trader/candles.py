"""Candlestick pattern recognition.

Each detector returns a Series of +1 (bullish), -1 (bearish) or 0 for every
candle, using only that candle and the ones before it (no look-ahead).
Patterns are the classic price-action set day traders use most: engulfing,
pin bars (hammer / shooting star), doji, morning / evening star, three
soldiers / crows, piercing / dark cloud and inside-bar breakouts.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _parts(df: pd.DataFrame):
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = (c - o).abs()
    rng = (h - l).replace(0, np.nan)
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - l
    avg_body = body.rolling(14, min_periods=5).mean()
    return o, h, l, c, body, rng, upper, lower, avg_body


def _trend(c: pd.Series, n: int = 5) -> pd.Series:
    """+1 if the last n closes fell into this candle (down move before it), etc."""
    return np.sign(c.shift(1) - c.shift(n + 1))


def engulfing(df):
    o, h, l, c, body, *_ = _parts(df)
    po, pc = o.shift(), c.shift()
    bull = (pc < po) & (c > o) & (c >= po) & (o <= pc) & (body > (pc - po).abs())
    bear = (pc > po) & (c < o) & (c <= po) & (o >= pc) & (body > (pc - po).abs())
    return bull.astype(int) - bear.astype(int)


def pin_bar(df):
    """Hammer after a fall (bullish) / shooting star after a rise (bearish)."""
    o, h, l, c, body, rng, upper, lower, _ = _parts(df)
    tr = _trend(c)
    small = body <= 0.35 * rng
    hammer = small & (lower >= 2 * body) & (upper <= 0.25 * rng) & (tr < 0)
    star = small & (upper >= 2 * body) & (lower <= 0.25 * rng) & (tr > 0)
    return hammer.astype(int) - star.astype(int)


def doji(df):
    """Doji = indecision. Signed against the prior move (possible reversal)."""
    o, h, l, c, body, rng, *_ = _parts(df)
    is_doji = body <= 0.1 * rng
    return (is_doji * -_trend(c)).fillna(0).astype(int)


def star(df):
    """Morning star (bullish) / evening star (bearish), 3 candles."""
    o, h, l, c, body, rng, upper, lower, avg = _parts(df)
    o2, c2, b2 = o.shift(2), c.shift(2), body.shift(2)
    b1 = body.shift(1)
    mid2 = (o2 + c2) / 2
    morning = (c2 < o2) & (b2 > avg) & (b1 < 0.5 * b2) & (c > o) & (c > mid2)
    evening = (c2 > o2) & (b2 > avg) & (b1 < 0.5 * b2) & (c < o) & (c < mid2)
    return morning.astype(int) - evening.astype(int)


def three_soldiers(df):
    """Three white soldiers / three black crows."""
    o, h, l, c, body, rng, upper, lower, avg = _parts(df)
    up = (c > o) & (body > 0.6 * avg) & (upper < 0.4 * body)
    dn = (c < o) & (body > 0.6 * avg) & (lower < 0.4 * body)
    rising = (c > c.shift()) & (c.shift() > c.shift(2))
    falling = (c < c.shift()) & (c.shift() < c.shift(2))
    soldiers = up & up.shift(1, fill_value=False) & up.shift(2, fill_value=False) & rising
    crows = dn & dn.shift(1, fill_value=False) & dn.shift(2, fill_value=False) & falling
    return soldiers.astype(int) - crows.astype(int)


def piercing(df):
    """Piercing line (bullish) / dark cloud cover (bearish)."""
    o, h, l, c, *_ = _parts(df)
    po, pc = o.shift(), c.shift()
    mid = (po + pc) / 2
    pierce = (pc < po) & (c > o) & (o < pc) & (c > mid) & (c < po)
    cloud = (pc > po) & (c < o) & (o > pc) & (c < mid) & (c > po)
    return pierce.astype(int) - cloud.astype(int)


def inside_bar_break(df):
    """Candle closes outside the range of a previous inside bar."""
    h, l, c = df["high"], df["low"], df["close"]
    inside = (h.shift(1) <= h.shift(2)) & (l.shift(1) >= l.shift(2))
    up = inside & (c > h.shift(2))
    dn = inside & (c < l.shift(2))
    return up.astype(int) - dn.astype(int)


PATTERNS = {
    "Engulfing": engulfing,
    "Pin bar": pin_bar,
    "Doji": doji,
    "Morning/Evening star": star,
    "Three soldiers/crows": three_soldiers,
    "Piercing/Dark cloud": piercing,
    "Inside-bar breakout": inside_bar_break,
}

# strength of each pattern when it appears
PATTERN_WEIGHT = {
    "Engulfing": 1.0, "Pin bar": 1.0, "Doji": 0.4, "Morning/Evening star": 1.2,
    "Three soldiers/crows": 0.8, "Piercing/Dark cloud": 0.8, "Inside-bar breakout": 0.8,
}


def detect_all(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({name: fn(df).fillna(0).astype(int) for name, fn in PATTERNS.items()}, index=df.index)


def pattern_score(df: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    """Weighted pattern vote, clipped to -1..1, plus the raw pattern table."""
    pats = detect_all(df)
    total = sum(pats[n] * w for n, w in PATTERN_WEIGHT.items())
    return total.clip(-1, 1), pats


def names_on_last(pats: pd.DataFrame) -> list[str]:
    row = pats.iloc[-1]
    return [f"{'Bullish' if v > 0 else 'Bearish'} {n.lower()}" for n, v in row.items() if v != 0]
