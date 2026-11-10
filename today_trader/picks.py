"""Automatic "safe picks": every few minutes, scan many assets, keep only the
setups that pass every safety check, rank them, and later check whether each
pick won or lost.

A pick must pass ALL of these:
  - a CALL or PUT signal (not WAIT), market open with fresh prices
  - at least 3 of the 4 indicator groups agree
  - not against the higher-timeframe trend, volatility normal, good session
  - if the asset was studied: the learned settings held up on unseen data
  - if there are 20+ similar past signals: their win rate beats break-even
  - the most similar past moments do not lean the other way
"""
from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from . import data
from . import localtime as lt
from .engine import analyze_many
from .market_read import read_market
from .signals import DEFAULT_THRESHOLD
from .study import load_study, study_is_recent

LOG_FILE = Path("quobot_picks.csv")
MINUTES = {"1m": 1, "2m": 2, "5m": 5, "15m": 15, "30m": 30, "1h": 60}


@dataclass
class Pick:
    symbol: str
    direction: str        # CALL / PUT
    interval: str
    expiry: int           # candles
    entry_time: str       # ISO UTC
    end_time: str         # ISO UTC
    entry_price: float
    stop: float
    safety: float
    score: float
    confluence: int
    reasons: str
    result: str = ""      # WIN / LOSS / DRAW
    exit_price: float = float("nan")


def safety_score(m, payout: float = 0.85) -> tuple[float, list[str]]:
    """0-100 (higher = safer) and reasons it was rejected (empty = passes)."""
    s, be = m.signal, 1 / (1 + payout)
    rejects = []
    if s.direction == "WAIT":
        rejects.append("no signal")
    if s.confluence < 3:
        rejects.append(f"only {s.confluence}/4 agree")
    if any(w.startswith(("Against the higher", "Very quiet", "Volatility spike", "Market closed", "Session"))
           for w in s.warnings):
        rejects.append("conditions: " + "; ".join(s.warnings))
    L = m.learned
    if L and L.get("test") and L["test"].get("trades", 0) >= 20 and not L.get("recommended"):
        rejects.append("failed its study on unseen data")
    if m.samples >= 20 and m.hit_rate < be:
        rejects.append(f"track record {m.hit_rate:.0%} < {be:.0%}")
    sm = m.similar
    if sm is not None and sm.matches >= 50:
        if (m.lean > 0 and sm.up_rate < 0.5) or (m.lean < 0 and sm.up_rate > 0.5):
            rejects.append("similar past moments went the other way")
    # ranking: strength, agreement, track record and experience edge
    track = (m.hit_rate - be) if m.samples >= 20 else 0.0
    exp_edge = 0.0
    if sm is not None and sm.matches >= 50:
        exp_edge = (sm.up_rate - 0.5) * (1 if m.lean > 0 else -1)
    test_edge = 0.0
    if L and L.get("test") and L["test"].get("trades", 0) >= 20:
        test_edge = L["test"]["win_rate"] - be
    safety = (0.45 * abs(s.score) + 10 * s.confluence + 100 * max(track, -0.2)
              + 80 * exp_edge + 60 * test_edge)
    return max(0.0, min(100.0, safety)), rejects


def find_picks(symbols, interval: str, top: int = 3, threshold: float = DEFAULT_THRESHOLD,
               demo: bool = False, history: int = 10000, payout: float = 0.85, study_fn=None):
    """Returns (picks, stats) where stats explains how many were filtered."""
    sigs, errors = analyze_many(symbols, interval, threshold, demo, min_agree=3)
    candidates = [s for s in sigs if s.direction != "WAIT"][: max(top * 3, 8)]
    picks: list[tuple[Pick, object]] = []
    rejected = 0
    step = pd.Timedelta(minutes=MINUTES.get(interval, 1))
    for s in candidates:
        try:
            if study_fn is not None and not study_is_recent(s.symbol, interval):
                study_fn(s.symbol, interval, demo)  # learn this asset before trusting it
            df = data.fetch(s.symbol, interval, history, demo=demo)
            learned = load_study(s.symbol, interval)
            expiry = learned["best"]["expiry"] if learned and learned.get("best") else 1
            m = read_market(df, s.symbol, interval, data.is_crypto(s.symbol), expiry, threshold)
        except Exception:
            continue
        safety, rejects = safety_score(m, payout)
        if rejects:
            rejected += 1
            continue
        entry = m.signal.time + step
        p = Pick(
            symbol=s.symbol, direction="CALL" if m.signal.score > 0 else "PUT", interval=interval,
            expiry=expiry, entry_time=entry.isoformat(), end_time=(entry + step * expiry).isoformat(),
            entry_price=m.signal.price, stop=m.stop, safety=round(safety, 1), score=round(m.signal.score, 1),
            confluence=m.signal.confluence, reasons=" | ".join(m.why[:3]),
        )
        picks.append((p, m))
    picks.sort(key=lambda x: -x[0].safety)
    stats = {"scanned": len(sigs) + len(errors), "signals": len(candidates), "rejected": rejected,
             "errors": len(errors)}
    return picks[:top], stats


def check_result(p: Pick, demo: bool = False) -> Pick | None:
    """Fill in WIN/LOSS once the expiry candle has closed. None = not yet."""
    end = pd.Timestamp(p.end_time)
    if pd.Timestamp.now(tz="UTC") < end + pd.Timedelta(seconds=5) and not demo:
        return None
    df = data.fetch(p.symbol, p.interval, 50, demo=demo)
    step = pd.Timedelta(minutes=MINUTES.get(p.interval, 1))
    # the candle that closes at `end` started at end - step
    row = df[df.index <= end - step]
    if row.empty or (not demo and row.index[-1] < end - step):
        # the feed hasn't published the expiry candle yet; give up after 15 minutes
        if pd.Timestamp.now(tz="UTC") > end + pd.Timedelta(minutes=15):
            p.result = "UNKNOWN"
            return p
        return None
    exit_price = float(row["close"].iloc[-1])
    if math.isclose(exit_price, p.entry_price, rel_tol=1e-9):
        res = "DRAW"
    elif (exit_price > p.entry_price) == (p.direction == "CALL"):
        res = "WIN"
    else:
        res = "LOSS"
    p.result, p.exit_price = res, exit_price
    return p


def log_pick(p: Pick, path: Path = LOG_FILE) -> None:
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(p).keys()))
        if new:
            w.writeheader()
        w.writerow(asdict(p))


def today_results(path: Path = LOG_FILE) -> dict:
    """Wins/losses of picks whose entry was today (local time)."""
    if not path.exists():
        return {"wins": 0, "losses": 0, "draws": 0, "rows": []}
    df = pd.read_csv(path)
    if df.empty:
        return {"wins": 0, "losses": 0, "draws": 0, "rows": []}
    t = pd.to_datetime(df["entry_time"], utc=True).dt.tz_convert(lt.tz())
    today = pd.Timestamp.now(tz=lt.tz()).normalize()
    d = df[t >= today]
    return {"wins": int((d["result"] == "WIN").sum()), "losses": int((d["result"] == "LOSS").sum()),
            "draws": int((d["result"] == "DRAW").sum()), "rows": d.tail(15).to_dict("records")}
