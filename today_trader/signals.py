"""Turns market data into a directional bias (CALL / PUT / WAIT).

The score works like a day trader's checklist:

1. Indicator votes. Each rule votes +1 (up), -1 (down) or 0, with a weight.
   Trend rules count more when ADX says the market trends, and reversal rules
   count more when it ranges.
     - Trend:      EMA 9/21, price vs EMA 50, +DI/-DI, Supertrend, Heikin Ashi
     - Momentum:   MACD histogram and its slope
     - Reversal:   RSI 30/70, Bollinger bands, Stochastic, CCI +-100, Williams %R
     - Price action: candlestick patterns, support/resistance bounce or breakout,
                   RSI divergence
2. Filters scale the raw score down when conditions are poor:
     - Higher timeframe: halved if the higher-timeframe trend disagrees
     - Volatility: reduced in very quiet or spiking markets
     - Session: reduced outside London / New York hours, zero on forex weekends
3. Confluence: how many of the four groups agree with the final direction.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import candles, levels
from .indicators import add_all, ema
from .sessions import session_quality

DEFAULT_THRESHOLD = 40  # |score| needed before suggesting a direction
HTF_FACTOR = 5          # higher timeframe = 5x the trading timeframe (1m -> 5m, 5m -> 25m)
GROUPS = {
    "trend": ["ema_stack", "ema50", "di", "supertrend", "heikin_ashi"],
    "momentum": ["macd", "macd_slope"],
    "reversal": ["rsi", "bb", "stoch", "cci", "willr"],
    "price_action": ["candles", "levels", "divergence"],
}


@dataclass
class Signal:
    symbol: str
    interval: str
    time: pd.Timestamp
    price: float
    score: float
    direction: str
    regime: str
    confluence: int = 0
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    supports: list = field(default_factory=list)
    resistances: list = field(default_factory=list)
    rsi: float = float("nan")
    adx: float = float("nan")
    atr: float = float("nan")


def higher_tf_trend(df: pd.DataFrame, factor: int = HTF_FACTOR) -> pd.Series:
    """Trend of the higher timeframe (+1/-1), as known at the close of each
    base candle. Only completed higher-timeframe candles are used."""
    if len(df) < 3:
        return pd.Series(0, index=df.index)
    step = pd.Timedelta(df.index.to_series().diff().median())
    period = step * factor
    htf = df["close"].resample(period, label="right", closed="left").last().dropna()
    trend = np.sign(ema(htf, 9) - ema(htf, 21))
    trend[ema(htf, 21).index[:21]] = 0  # warm-up
    base_close_time = df.index + step
    aligned = trend.reindex(trend.index.union(base_close_time)).ffill().reindex(base_close_time)
    return pd.Series(aligned.fillna(0).values, index=df.index)


def score_frame(df: pd.DataFrame, crypto: bool = False, use_filters: bool = True) -> pd.DataFrame:
    """Adds `score` (-100..100), `raw_score`, `regime`, filter columns and
    every vote to each row. Uses only information available at that candle."""
    d = add_all(df)
    n = len(d)
    trending = d["adx"] > 25
    trend_w = np.where(trending, 1.5, 0.75)
    revert_w = np.where(trending, 0.5, 1.25)
    one = np.ones(n)

    cdl, pats = candles.pattern_score(d)
    lvl = levels.level_vote(d, d["atr"])
    div = levels.rsi_divergence(d, d["rsi"])

    votes = {
        "ema_stack": (np.sign(d["ema9"] - d["ema21"]), trend_w),
        "ema50": (np.sign(d["close"] - d["ema50"]), trend_w * 0.75),
        "di": (np.sign(d["plus_di"] - d["minus_di"]), trend_w * 0.75),
        "supertrend": (d["supertrend"], trend_w),
        "heikin_ashi": (d["ha_trend"], one * 0.5),
        "macd": (np.sign(d["macd_hist"]), one),
        "macd_slope": (np.sign(d["macd_hist"].diff()), one * 0.5),
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
        "cci": (np.select([d["cci"] < -100, d["cci"] > 100], [1, -1], 0), revert_w * 0.5),
        "willr": (np.select([d["willr"] < -80, d["willr"] > -20], [1, -1], 0), revert_w * 0.5),
        "candles": (cdl, one * 1.5),
        "levels": (lvl, one * 1.5),
        "divergence": (div, one * 1.25),
    }
    total = sum(np.nan_to_num(np.asarray(v, float)) * w for v, w in votes.values())
    max_total = sum(np.asarray(w, float) for _, w in votes.values())
    d["raw_score"] = 100 * total / max_total
    for name, (v, _) in votes.items():
        d[f"vote_{name}"] = np.nan_to_num(np.asarray(v, float))
    for g, members in GROUPS.items():
        d[f"group_{g}"] = np.sign(sum(d[f"vote_{m}"] for m in members))
    for name in pats.columns:
        d[f"pat_{name}"] = pats[name]

    # --- filters ---------------------------------------------------------
    d["htf_trend"] = higher_tf_trend(d)
    if use_filters:
        htf_mult = np.where(np.sign(d["raw_score"]) * d["htf_trend"] < 0, 0.5, 1.0)
        vol_mult = np.select([d["atr_pct"] < 0.15, d["atr_pct"] > 0.95], [0.5, 0.7], 1.0)
        sess = [session_quality(t, crypto)[0] for t in d.index]
        d["filter_mult"] = htf_mult * vol_mult * np.asarray(sess)
    else:
        d["filter_mult"] = 1.0
    d["score"] = (d["raw_score"] * d["filter_mult"]).clip(-100, 100)
    d["regime"] = np.where(trending, "trending", "ranging")
    return d


def _reasons(row: pd.Series) -> list[str]:
    r = []
    r.append("EMA 9 above EMA 21 (short-term uptrend)" if row["ema9"] > row["ema21"]
             else "EMA 9 below EMA 21 (short-term downtrend)")
    r.append(f"Supertrend {'up' if row['supertrend'] > 0 else 'down'}, price "
             f"{'above' if row['close'] > row['ema50'] else 'below'} EMA 50")
    r.append(f"MACD histogram {'positive' if row['macd_hist'] > 0 else 'negative'}"
             f" and {'rising' if row['vote_macd_slope'] > 0 else 'falling'}")
    zone = "oversold" if row["rsi"] < 30 else "overbought" if row["rsi"] > 70 else "neutral"
    r.append(f"RSI {row['rsi']:.0f}: {zone}")
    if row["close"] < row["bb_low"]:
        r.append("Close below lower Bollinger band")
    elif row["close"] > row["bb_high"]:
        r.append("Close above upper Bollinger band")
    if row["vote_stoch"] > 0:
        r.append("Stochastic turning up from oversold")
    elif row["vote_stoch"] < 0:
        r.append("Stochastic turning down from overbought")
    pats = [f"{'Bullish' if row[c] > 0 else 'Bearish'} {c[4:].lower()}"
            for c in row.index if c.startswith("pat_") and row[c] != 0]
    if pats:
        r.append("Candles: " + ", ".join(pats))
    if row["vote_levels"] > 0:
        r.append("Bounce off support / breakout above resistance")
    elif row["vote_levels"] < 0:
        r.append("Rejected at resistance / breakdown below support")
    if row["vote_divergence"] > 0:
        r.append("Bullish RSI divergence")
    elif row["vote_divergence"] < 0:
        r.append("Bearish RSI divergence")
    htf = {1: "up", -1: "down"}.get(int(row["htf_trend"]), "unclear")
    r.append(f"Higher timeframe trend: {htf}")
    r.append(f"ADX {row['adx']:.0f}: {'trending' if row['adx'] > 25 else 'ranging / weak trend'}")
    return r


def _warnings(row: pd.Series, crypto: bool) -> list[str]:
    w = []
    if np.sign(row["raw_score"]) * row["htf_trend"] < 0:
        w.append("Against the higher-timeframe trend (score halved)")
    if row["atr_pct"] < 0.15:
        w.append("Very quiet market: small moves, signals unreliable")
    elif row["atr_pct"] > 0.95:
        w.append("Volatility spike (news?): wait for it to settle")
    mult, label = session_quality(row.name, crypto)
    if mult < 0.9:
        w.append(f"Session: {label}")
    return w


def direction_for(score: float, threshold: float = DEFAULT_THRESHOLD) -> str:
    if score >= threshold:
        return "CALL (up)"
    if score <= -threshold:
        return "PUT (down)"
    return "WAIT"


def analyze(df: pd.DataFrame, symbol: str, interval: str, threshold: float = DEFAULT_THRESHOLD,
            crypto: bool = False) -> Signal:
    if len(df) < 60:
        raise ValueError(f"{symbol}: need at least 60 candles, got {len(df)}")
    d = score_frame(df, crypto=crypto)
    row = d.iloc[-1]
    direction = direction_for(row["score"], threshold)
    sign = np.sign(row["score"])
    confluence = int(sum(row[f"group_{g}"] == sign for g in GROUPS)) if sign else 0
    sup, res = levels.nearest_levels(df, atr=d["atr"])
    return Signal(
        symbol=symbol, interval=interval, time=d.index[-1], price=float(row["close"]),
        score=float(row["score"]), direction=direction, regime=row["regime"],
        confluence=confluence, reasons=_reasons(row), warnings=_warnings(row, crypto),
        supports=sup[:2], resistances=res[:2],
        rsi=float(row["rsi"]), adx=float(row["adx"]), atr=float(row["atr"]),
    )
