"""A plain-language market read: what the market is doing, which way the bot
leans for the next candles, why, what would prove it wrong, and how often the
same kind of setup worked on this asset's recent history."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .signals import DEFAULT_THRESHOLD, Signal, analyze, score_frame


@dataclass
class MarketRead:
    signal: Signal
    prediction: str
    expiry: int
    story: list[str] = field(default_factory=list)
    why: list[str] = field(default_factory=list)
    against: list[str] = field(default_factory=list)
    invalidation: str = ""
    expected_move: str = ""
    hit_rate: float = float("nan")
    samples: int = 0
    hit_by_expiry: dict = field(default_factory=dict)
    groups: dict = field(default_factory=dict)
    lean: int = 0
    stop: float = float("nan")
    similar: object = None   # study.SimilarResult
    learned: dict | None = None


def _fmt(p: float) -> str:
    return f"{p:,.2f}" if p >= 100 else f"{p:.5f}"


def _hit_rate(d: pd.DataFrame, sign: int, threshold: float, expiry: int):
    """How often a signal in the same direction and at least as strong was
    right `expiry` candles later, on this data (excluding warm-up)."""
    from .signals import lead
    h = d.iloc[100:]
    L = lead()
    base = h["close"].shift(-L)
    fut = h["close"].shift(-(L + expiry))
    mask = (np.sign(h["score"]) == sign) & (h["score"].abs() >= threshold) & fut.notna()
    if sign == 0 or mask.sum() == 0:
        return float("nan"), 0
    right = (fut[mask] > base[mask]) if sign > 0 else (fut[mask] < base[mask])
    return float(right.mean()), int(mask.sum())


def read_market(df: pd.DataFrame, symbol: str, interval: str, crypto: bool = False,
                expiry: int = 1, threshold: float = DEFAULT_THRESHOLD) -> MarketRead:
    sig = analyze(df, symbol, interval, threshold, crypto=crypto)
    d = score_frame(df, crypto=crypto)
    row = d.iloc[-1]
    sign = int(np.sign(sig.score)) if sig.direction != "WAIT" else 0
    price = sig.price

    # ---- what the market is doing --------------------------------------
    story = []
    trend_votes = [row["vote_ema_stack"], row["vote_ema50"], row["vote_di"], row["vote_supertrend"]]
    t = sum(trend_votes)
    if t >= 3:
        story.append("Trend: clear uptrend. Fast EMAs are above slow ones and Supertrend is up.")
    elif t <= -3:
        story.append("Trend: clear downtrend. Fast EMAs are below slow ones and Supertrend is down.")
    else:
        story.append("Trend: mixed. Trend tools disagree, so there's no clean direction.")
    story.append(
        f"Strength: ADX {row['adx']:.0f}, "
        + ("a strong trend, so trend-following setups work better." if row["adx"] > 25
           else "a weak trend or a range, so bounces off levels work better than breakouts.")
    )
    htf = {1: "up", -1: "down"}.get(int(row["htf_trend"]), "unclear")
    story.append(f"Bigger picture: the higher timeframe trend is {htf}.")
    mom = "building up" if row["macd_hist"] > 0 and row["vote_macd_slope"] > 0 else \
          "fading after a rise" if row["macd_hist"] > 0 else \
          "building down" if row["vote_macd_slope"] < 0 else "fading after a fall"
    story.append(f"Momentum: {mom} (MACD), RSI {row['rsi']:.0f}.")
    if sig.supports or sig.resistances:
        s = f"nearest support {_fmt(sig.supports[0][0])}" if sig.supports else "no support nearby"
        r = f"nearest resistance {_fmt(sig.resistances[0][0])}" if sig.resistances else "no resistance nearby"
        story.append(f"Levels: price {_fmt(price)}, {s}, {r}.")
    pats = [f"{'bullish' if row[c] > 0 else 'bearish'} {c[4:].lower()}"
            for c in row.index if c.startswith("pat_") and row[c] != 0]
    if pats:
        story.append("Last candle: " + ", ".join(pats) + ".")
    vol = "very quiet" if row["atr_pct"] < 0.15 else "spiking" if row["atr_pct"] > 0.95 else "normal"
    story.append(f"Volatility: {vol}.")

    # ---- why: votes for and against the call ---------------------------
    labels = {
        "ema_stack": ("EMA 9 above EMA 21", "EMA 9 below EMA 21"),
        "ema50": ("price above EMA 50", "price below EMA 50"),
        "di": ("buyers stronger (+DI > -DI)", "sellers stronger (-DI > +DI)"),
        "supertrend": ("Supertrend up", "Supertrend down"),
        "heikin_ashi": ("Heikin Ashi candle green", "Heikin Ashi candle red"),
        "macd": ("MACD positive", "MACD negative"),
        "macd_slope": ("MACD rising", "MACD falling"),
        "rsi": ("RSI oversold", "RSI overbought"),
        "bb": ("below lower Bollinger band (stretched down)", "above upper Bollinger band (stretched up)"),
        "stoch": ("Stochastic turning up from oversold", "Stochastic turning down from overbought"),
        "cci": ("CCI below -100", "CCI above +100"),
        "willr": ("Williams %R oversold", "Williams %R overbought"),
        "candles": ("bullish candle pattern", "bearish candle pattern"),
        "levels": ("bounce off support / break above resistance", "rejection at resistance / break below support"),
        "divergence": ("bullish RSI divergence", "bearish RSI divergence"),
    }
    lean = sign or int(np.sign(sig.score))
    why, against = [], []
    for k, (up, down) in labels.items():
        v = row[f"vote_{k}"]
        if v == 0 or lean == 0:
            continue
        (why if np.sign(v) == lean else against).append(up if v > 0 else down)

    # ---- prediction, invalidation, expected move ------------------------
    hit_by = {e: _hit_rate(d, lean, threshold, e) for e in (1, 2, 3, 5)} if lean else {}
    hr, n = hit_by.get(expiry, (float("nan"), 0))
    move = row["atr"] * np.sqrt(expiry)
    if sign > 0:
        pred = f"UP over the next {expiry} candle(s)"
        stop = sig.supports[0][0] if sig.supports else min(row["ema21"], price - row["atr"])
        inval = f"Wrong if a candle closes below {_fmt(stop)}."
    elif sign < 0:
        pred = f"DOWN over the next {expiry} candle(s)"
        stop = sig.resistances[0][0] if sig.resistances else max(row["ema21"], price + row["atr"])
        inval = f"Wrong if a candle closes above {_fmt(stop)}."
    else:
        pred = "NO CLEAR EDGE: wait for a better setup"
        if lean:
            pred += f" (slight lean {'up' if lean > 0 else 'down'}, too weak to call)"
        inval = ""
    exp = f"Typical move over {expiry} candle(s): about {_fmt(move)} (from ATR)."

    from .signals import GROUPS
    from .study import load_study, similar_setups
    sim = similar_setups(df, expiry, crypto=crypto, d=d)
    return MarketRead(sig, pred, expiry, story, why, against, inval, exp, hr, n,
                      {e: v for e, v in hit_by.items()},
                      groups={g: int(row[f"group_{g}"]) for g in GROUPS}, lean=lean,
                      stop=float(stop) if sign else float("nan"),
                      similar=sim if sim.matches else None, learned=load_study(symbol, interval))


def format_read(m: MarketRead, payout: float = 0.85) -> str:
    s = m.signal
    be = 1 / (1 + payout)
    out = [f"{s.symbol} {s.interval} | price {_fmt(s.price)} | score {s.score:+.0f} | {s.confluence}/4 groups agree",
           "", "What the market is doing:"]
    out += [f"  - {x}" for x in m.story]
    out += ["", f"Prediction: {m.prediction}"]
    if m.why:
        out += ["Why:"] + [f"  + {x}" for x in m.why]
    if m.against:
        out += ["Against it:"] + [f"  - {x}" for x in m.against]
    if m.invalidation:
        out.append(m.invalidation)
    out.append(m.expected_move)
    if m.samples >= 20:
        verdict = "above" if m.hit_rate > be else "BELOW"
        out.append(f"Track record on this asset: strong signals in this direction were right {m.hit_rate:.0%} of the time "
                   f"({m.samples} cases), {verdict} the {be:.0%} needed to break even.")
        others = ", ".join(f"{e} candle(s) {v[0]:.0%}" for e, v in m.hit_by_expiry.items() if v[1] >= 20)
        if others:
            out.append(f"By expiry: {others}.")
    elif m.samples:
        out.append(f"Track record: only {m.samples} similar cases in the loaded history, too few to judge.")
    if m.similar is not None:
        sm = m.similar
        out.append(f"Similar past moments: {sm.matches} closest matches out of {sm.history} candles; price went UP "
                   f"{sm.up_rate:.0%} of the time over {sm.expiry} candle(s) (likely range {sm.low:.0%}-{sm.high:.0%}).")
    if m.learned:
        out.append(f"Study: {m.learned['verdict']}")
    for w in s.warnings:
        out.append(f"! {w}")
    return "\n".join(out)
