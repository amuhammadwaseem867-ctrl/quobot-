"""Forex mode for an MT5 broker such as XM: BUY/SELL signals with a stop-loss,
a take-profit and a lot size that fits your balance.

Signals only. Nothing here places orders: you copy the trade into MT5 yourself.

How the numbers are made
  - direction: the same indicator engine as the Quotex signals, but on longer
    candles (default 15m) because spreads eat most of a 1-minute move
  - stop-loss: behind the nearest support/resistance if it is 1-3 ATR away,
    otherwise 1.5 ATR, and never closer than 5x the typical spread
  - take-profit: stop distance x reward:risk (default 2)
  - lot size: risk % of balance / (stop distance x value of one lot)
  - track record: on this asset's history, how often signals like this hit
    the take-profit before the stop-loss (spread included)
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import data
from .engine import mark_closed
from .market_read import read_market
from .signals import DEFAULT_THRESHOLD, score_frame
from .study import _confluence, wilson

# XM account types. Micro: 1 lot = 1,000 units and symbols end in "micro".
# Standard (and Ultra Low): 1 lot = 100,000 units. Check the exact names in
# your MT5 "Market Watch" (right click > Symbols); they can differ per server.
ACCOUNTS = {
    "micro": {"units": 1_000, "suffix": "micro", "gold_units": 1, "silver_units": 50},
    "standard": {"units": 100_000, "suffix": "", "gold_units": 100, "silver_units": 5_000},
}
METALS = {"XAUUSD": ("GOLD", "gold_units"), "XAGUSD": ("SILVER", "silver_units")}
MIN_LOT, LOT_STEP = 0.01, 0.01

# rough typical XM spreads (in price units) used for safety margins and the
# track record; real spreads change during news and at night
SPREAD_PIPS = {"EURUSD": 1.7, "GBPUSD": 2.0, "USDJPY": 1.9, "USDCHF": 2.0, "AUDUSD": 1.8, "USDCAD": 2.2,
               "NZDUSD": 2.3, "EURGBP": 2.0, "EURJPY": 2.6, "GBPJPY": 3.5}
METAL_SPREAD = {"XAUUSD": 0.35, "XAGUSD": 0.035}
FX_PAIRS = {"EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
            "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURCAD", "EURNZD", "GBPJPY", "GBPCHF", "GBPAUD",
            "GBPCAD", "GBPNZD", "AUDJPY", "AUDCAD", "AUDCHF", "AUDNZD", "CADJPY", "CADCHF", "CHFJPY",
            "NZDJPY", "NZDCAD", "NZDCHF"}
FX_DEFAULT = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "EURJPY", "GBPJPY", "XAUUSD"]
# offline approximations, only used with --demo
DEMO_USD = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "JPY": 0.0067, "CHF": 1.12, "AUD": 0.66, "CAD": 0.73, "NZD": 0.6}


def supported(symbol: str) -> bool:
    return symbol.upper() in FX_PAIRS or symbol.upper() in METALS


def pip_size(symbol: str) -> float:
    s = symbol.upper()
    if s in METALS:
        return 0.1 if s == "XAUUSD" else 0.01
    return 0.01 if s.endswith("JPY") else 0.0001


def spread(symbol: str) -> float:
    s = symbol.upper()
    if s in METALS:
        return METAL_SPREAD[s]
    return SPREAD_PIPS.get(s, 3.0) * pip_size(s)


def broker_symbol(symbol: str, account: str = "micro") -> str:
    s = symbol.upper()
    base = METALS[s][0] if s in METALS else s
    return base + ACCOUNTS[account]["suffix"]


def contract_units(symbol: str, account: str = "micro") -> float:
    s = symbol.upper()
    acc = ACCOUNTS[account]
    return acc[METALS[s][1]] if s in METALS else acc["units"]


def usd_rate(ccy: str, demo: bool = False) -> float:
    """US dollars per 1 unit of `ccy`."""
    ccy = ccy.upper()
    if ccy == "USD":
        return 1.0
    if demo:
        return DEMO_USD.get(ccy, 1.0)
    for sym, invert in ((f"{ccy}USD", False), (f"USD{ccy}", True)):
        try:
            px = float(data.fetch(sym, "1h", 5)["close"].iloc[-1])
            return 1 / px if invert else px
        except Exception:
            continue
    raise RuntimeError(f"no USD rate for {ccy}")


@dataclass
class FxPlan:
    symbol: str
    broker_symbol: str
    interval: str
    action: str                 # BUY / SELL / WAIT
    entry: float
    stop: float = float("nan")
    target: float = float("nan")
    stop_pips: float = float("nan")
    target_pips: float = float("nan")
    lots: float = 0.0
    risk_usd: float = 0.0
    reward_usd: float = 0.0
    risk_pct: float = 0.0
    margin_usd: float = 0.0
    balance: float = 50.0
    account: str = "micro"
    leverage: int = 500
    rr: float = 2.0
    hit_rate: float = float("nan")   # TP before SL in history
    hit_low: float = float("nan")
    hit_high: float = float("nan")
    samples: int = 0
    breakeven: float = float("nan")
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skip: str = ""             # why not to take it, if anything
    time: pd.Timestamp | None = None
    score: float = 0.0
    confluence: int = 0


def _round_lot(x: float) -> float:
    return math.floor(x / LOT_STEP + 1e-9) * LOT_STEP


def tp_before_sl(df: pd.DataFrame, threshold: float, rr: float, atr_mult: float, sp: float,
                 crypto: bool = False, horizon: int = 48, min_agree: int = 3):
    """On past candles: of the signals like today's, how many reached the
    take-profit before the stop-loss within `horizon` candles. Entry pays the
    spread. A trade still open after `horizon` counts as a loss."""
    d = score_frame(df, crypto=crypto).iloc[100:]
    d = d.assign(confluence=_confluence(d))
    hi, lo, cl, atr = (d[c].to_numpy() for c in ("high", "low", "close", "atr"))
    sig = np.where((d["score"] >= threshold) & (d["confluence"] >= min_agree), 1,
                   np.where((d["score"] <= -threshold) & (d["confluence"] >= min_agree), -1, 0))
    wins = n = 0
    last = -horizon
    for i in np.flatnonzero(sig):
        if i + 1 >= len(d) or i - last < 3 or not atr[i] > 0:   # skip overlapping repeats
            continue
        last = i
        side = sig[i]
        risk = max(atr_mult * atr[i], 5 * sp)
        entry = cl[i] + side * sp / 2
        sl, tp = entry - side * risk, entry + side * risk * rr
        out = 0
        for j in range(i + 1, min(i + 1 + horizon, len(d))):
            hit_sl = lo[j] <= sl if side > 0 else hi[j] >= sl
            hit_tp = hi[j] >= tp if side > 0 else lo[j] <= tp
            if hit_sl:          # both in one candle: assume the worst
                out = -1
                break
            if hit_tp:
                out = 1
                break
        n += 1
        wins += out == 1
    return (wins / n if n else float("nan")), n


def plan_trade(symbol: str, interval: str = "15m", balance: float = 50.0, risk_pct: float = 1.0,
               account: str = "micro", leverage: int = 500, rr: float = 2.0,
               threshold: float = DEFAULT_THRESHOLD, demo: bool = False, history: int = 5000) -> FxPlan:
    s = symbol.upper()
    if not supported(s):
        raise ValueError(f"{s} isn't in forex mode (forex pairs, XAUUSD and XAGUSD only)")
    df = data.fetch(s, interval, history, demo=demo)
    m = read_market(df, s, interval, False, 1, threshold)
    sig = m.signal
    if not demo and not data.is_fresh(df, interval):
        mark_closed(sig)
    sp = spread(s)
    price = sig.price
    p = FxPlan(s, broker_symbol(s, account), interval, "WAIT", price, balance=balance, account=account,
               leverage=leverage, rr=rr, reasons=list(m.why[:4]), warnings=list(sig.warnings),
               time=sig.time, score=sig.score, confluence=sig.confluence)
    p.breakeven = 1 / (1 + rr)
    p.hit_rate, p.samples = tp_before_sl(df, threshold, rr, 1.5, sp)
    if p.samples:
        p.hit_low, p.hit_high = wilson(p.hit_rate, p.samples)

    if sig.direction == "WAIT":
        p.skip = "no clear direction right now"
        return p
    side = 1 if sig.score > 0 else -1
    p.action = "BUY" if side > 0 else "SELL"
    atr = sig.atr if sig.atr > 0 else price * 0.001
    dist = abs(price - m.stop) if not math.isnan(m.stop) else float("nan")
    if not (atr <= dist <= 3 * atr):
        dist = 1.5 * atr
    dist = max(dist + sp, 5 * sp)          # room for the spread
    p.entry = price + side * sp / 2        # BUY fills at ask, SELL at bid
    p.stop = p.entry - side * dist
    p.target = p.entry + side * dist * rr
    pip = pip_size(s)
    p.stop_pips, p.target_pips = dist / pip, dist * rr / pip

    units = contract_units(s, account)
    base, quote = (s[:3], s[3:]) if s not in METALS else (s[:3], "USD")
    q_usd = usd_rate(quote, demo)
    per_lot = dist * units * q_usd                 # $ lost per 1.0 lot if the stop is hit
    budget = balance * risk_pct / 100
    lots = _round_lot(budget / per_lot) if per_lot > 0 else 0.0
    if lots < MIN_LOT:
        lots = MIN_LOT
    p.lots = round(lots, 2)
    p.risk_usd = p.lots * per_lot
    p.reward_usd = p.risk_usd * rr
    p.risk_pct = 100 * p.risk_usd / balance if balance else float("inf")
    base_usd = price * q_usd if s in METALS else (1.0 if base == "USD" else usd_rate(base, demo))
    p.margin_usd = p.lots * units * base_usd / max(leverage, 1)

    # reasons not to take it
    if sig.confluence < 3:
        p.skip = f"only {sig.confluence}/4 indicator groups agree"
    elif any(w.startswith(("Against the higher", "Volatility spike", "Market closed", "Session"))
             for w in sig.warnings):
        p.skip = "conditions are poor: " + "; ".join(sig.warnings)
    elif p.risk_pct > 2 * risk_pct + 0.5:
        p.skip = (f"even the smallest lot ({MIN_LOT}) risks {p.risk_pct:.1f}% of your balance. "
                  + ("A Micro account fixes this (its lots are 100x smaller)." if account == "standard"
                     else "Wait for a calmer market or use a bigger balance."))
    elif p.samples >= 30 and p.hit_low < p.breakeven and p.hit_rate < p.breakeven + 0.03:
        p.skip = (f"in the past, signals like this reached the target only {p.hit_rate:.0%} of the time "
                  f"(needs {p.breakeven:.0%} to break even)")
    elif p.margin_usd > balance * 0.5:
        p.skip = f"needs ${p.margin_usd:.2f} margin, too much of a ${balance:g} account"
    return p


def settings_from_env() -> dict:
    def f(key, default, cast):
        try:
            return cast(os.getenv(key, default))
        except ValueError:
            return cast(default)
    acc = os.getenv("FX_ACCOUNT", "micro").lower()
    return {"balance": f("FX_BALANCE", 50, float), "risk_pct": f("FX_RISK", 1, float),
            "account": acc if acc in ACCOUNTS else "micro", "leverage": f("FX_LEVERAGE", 500, int),
            "rr": f("FX_RR", 2, float)}


def scan(symbols=None, interval: str = "15m", demo: bool = False, top: int = 3, **settings):
    """Plans for many assets; the valid ones first, best track record first."""
    plans, errors = [], {}
    for s in symbols or FX_DEFAULT:
        try:
            plans.append(plan_trade(s, interval, demo=demo, **settings))
        except Exception as e:
            errors[s] = type(e).__name__
    good = [p for p in plans if p.action != "WAIT" and not p.skip]
    good.sort(key=lambda p: -(0 if math.isnan(p.hit_rate) else p.hit_rate) - abs(p.score) / 1000)
    return good[:top], plans, errors
