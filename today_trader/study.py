"""Learning from history.

Two tools:

1. similar_setups(): finds the past moments that looked most like right now
   (same indicator votes, RSI, trend strength, volatility, higher-timeframe
   trend, time of day) and counts what price did next. That is the bot's
   "experience" of this exact kind of situation.

2. study(): replays every candle of the loaded history (up to ~10,000) as if
   it were live, tries many setting combinations (signal threshold, how many
   groups must agree, expiry), and keeps the best one. To avoid fooling itself
   it picks settings on the OLDER 70% of the data and then checks them on the
   NEWER 30% it has never seen ("walk-forward" testing). Only the unseen-data
   result says how well the settings are likely to work.

Learned settings are saved to quobot_settings.json and used by the market
read and the Telegram bot.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from .signals import GROUPS, lead, score_frame

SETTINGS_FILE = Path("quobot_settings.json")

FEATURES = [
    "vote_ema_stack", "vote_ema50", "vote_di", "vote_supertrend", "vote_heikin_ashi",
    "vote_macd", "vote_macd_slope", "vote_rsi", "vote_bb", "vote_stoch", "vote_cci",
    "vote_willr", "vote_candles", "vote_levels", "vote_divergence", "htf_trend",
]
CONTINUOUS = ["rsi", "adx", "atr_pct", "stoch_k", "macd_norm", "dist_ema21"]


def wilson(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence range for a win rate measured on n trades."""
    if n == 0:
        return 0.0, 1.0
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def _confluence(d: pd.DataFrame) -> pd.Series:
    sign = np.sign(d["score"])
    return sum((d[f"group_{g}"] == sign).astype(int) for g in GROUPS).where(sign != 0, 0)


# ---------------------------------------------------------------------------
# 1. similar past setups
# ---------------------------------------------------------------------------
@dataclass
class SimilarResult:
    matches: int
    up_rate: float
    low: float
    high: float
    avg_move_atr: float
    expiry: int
    history: int

    @property
    def lean(self) -> str:
        if self.low > 0.5:
            return "UP"
        if self.high < 0.5:
            return "DOWN"
        return "UNCLEAR"


def _feature_matrix(d: pd.DataFrame) -> np.ndarray:
    x = d.copy()
    x["macd_norm"] = x["macd_hist"] / x["atr"].replace(0, np.nan)
    x["dist_ema21"] = (x["close"] - x["ema21"]) / x["atr"].replace(0, np.nan)
    cont = x[CONTINUOUS].astype(float)
    cont = (cont - cont.mean()) / cont.std(ddof=0).replace(0, 1)
    hour = x.index.hour + x.index.minute / 60 if isinstance(x.index, pd.DatetimeIndex) else np.zeros(len(x))
    tod = np.c_[np.sin(2 * np.pi * np.asarray(hour) / 24), np.cos(2 * np.pi * np.asarray(hour) / 24)] * 0.5
    return np.c_[x[FEATURES].astype(float).values, cont.values, tod]


def similar_setups(df: pd.DataFrame, expiry: int = 1, k: int = 150, crypto: bool = False,
                   d: pd.DataFrame | None = None) -> SimilarResult:
    """What happened after the k past candles most similar to the latest one."""
    d = score_frame(df, crypto=crypto) if d is None else d
    d = d.iloc[100:]
    X = np.nan_to_num(_feature_matrix(d))
    now = X[-1]
    L = lead()
    past = X[:-(expiry + L) - 1] if len(X) > expiry + L + 1 else X[:0]
    if len(past) < 50:
        return SimilarResult(0, float("nan"), 0, 1, float("nan"), expiry, len(d))
    close = d["close"].values
    fut = close[L + expiry:len(past) + L + expiry] - close[L:len(past) + L]
    dist = np.sqrt(((past - now) ** 2).sum(axis=1))
    k = min(k, len(past))
    idx = np.argpartition(dist, k - 1)[:k]
    moved = fut[idx]
    atr = d["atr"].values[idx]
    keep = moved != 0
    moved, atr = moved[keep], atr[keep]
    if len(moved) == 0:
        return SimilarResult(0, float("nan"), 0, 1, float("nan"), expiry, len(d))
    up = float((moved > 0).mean())
    lo, hi = wilson(up, len(moved))
    avg = float(np.nanmean(moved / np.where(atr == 0, np.nan, atr)))
    return SimilarResult(len(moved), up, lo, hi, avg, expiry, len(d))


# ---------------------------------------------------------------------------
# 2. study: test settings, keep the best, check on unseen data
# ---------------------------------------------------------------------------
@dataclass
class Trial:
    threshold: float
    min_agree: int
    expiry: int
    trades: int
    win_rate: float
    net: float


@dataclass
class StudyResult:
    symbol: str
    interval: str
    candles: int
    candles_replayed: int
    combos_tested: int
    payout: float
    best: dict | None = None
    train: dict | None = None
    test: dict | None = None
    test_low: float = 0.0
    test_high: float = 1.0
    recommended: bool = False
    verdict: str = ""
    by_hour: dict = field(default_factory=dict)
    by_regime: dict = field(default_factory=dict)
    by_direction: dict = field(default_factory=dict)


def _evaluate(d: pd.DataFrame, threshold: float, min_agree: int, expiry: int, payout: float) -> Trial:
    L = lead()
    base = d["close"].shift(-L)
    fut = d["close"].shift(-(L + expiry))
    ok = fut.notna()
    call = (d["score"] >= threshold) & (d["confluence"] >= min_agree) & ok
    put = (d["score"] <= -threshold) & (d["confluence"] >= min_agree) & ok
    wins = int(((call & (fut > base)) | (put & (fut < base))).sum())
    n = int((call | put).sum())
    wr = wins / n if n else float("nan")
    return Trial(threshold, min_agree, expiry, n, wr, wins * payout - (n - wins))


def _breakdown(d: pd.DataFrame, t: Trial) -> tuple[dict, dict, dict]:
    L = lead()
    base = d["close"].shift(-L)
    fut = d["close"].shift(-(L + t.expiry))
    sig = ((d["score"].abs() >= t.threshold) & (d["confluence"] >= t.min_agree) & fut.notna())
    s = d[sig]
    win = np.where(s["score"] > 0, fut[sig] > base[sig], fut[sig] < base[sig])
    s = s.assign(win=win)
    hour = s.groupby((s.index.hour // 4) * 4)["win"].agg(["mean", "count"]) if len(s) else pd.DataFrame()
    by_hour = {f"{h:02d}-{h + 4:02d} UTC": (float(r["mean"]), int(r["count"])) for h, r in hour.iterrows()}
    reg = s.groupby("regime")["win"].agg(["mean", "count"]) if len(s) else pd.DataFrame()
    by_regime = {k: (float(r["mean"]), int(r["count"])) for k, r in reg.iterrows()}
    side = s.groupby(np.where(s["score"] > 0, "CALL", "PUT"))["win"].agg(["mean", "count"]) if len(s) else pd.DataFrame()
    by_dir = {k: (float(r["mean"]), int(r["count"])) for k, r in side.iterrows()}
    return by_hour, by_regime, by_dir


def study(df: pd.DataFrame, symbol: str, interval: str, crypto: bool = False, payout: float = 0.85,
          train_frac: float = 0.7, min_trades: int = 30) -> StudyResult:
    d = score_frame(df, crypto=crypto).iloc[100:]
    d = d.assign(confluence=_confluence(d))
    split = int(len(d) * train_frac)
    train, test = d.iloc[:split], d.iloc[split:]
    grid = list(product([30, 40, 50, 60], [0, 2, 3], [1, 2, 3, 5]))
    res = StudyResult(symbol, interval, len(df), len(d), len(grid), payout)
    be = 1 / (1 + payout)

    trials = [_evaluate(train, th, ma, ex, payout) for th, ma, ex in grid]
    trials = [t for t in trials if t.trades >= min_trades]
    if not trials:
        res.verdict = "Not enough signals in the history to learn from. Load more candles or use a longer timeframe."
        return res
    best = max(trials, key=lambda t: (t.net / max(t.trades, 1), t.trades))  # profit per trade
    tst = _evaluate(test, best.threshold, best.min_agree, best.expiry, payout)
    res.best = {"threshold": best.threshold, "min_agree": best.min_agree, "expiry": best.expiry}
    res.train, res.test = asdict(best), asdict(tst)
    res.test_low, res.test_high = wilson(tst.win_rate, tst.trades) if tst.trades else (0.0, 1.0)
    res.by_hour, res.by_regime, res.by_direction = _breakdown(d, best)

    if tst.trades < 20:
        res.verdict = (f"Best settings found, but only {tst.trades} trades in the unseen part to check them. "
                       "Treat signals on this asset as unproven.")
    elif tst.win_rate > be and res.test_low > 0.5:
        res.recommended = True
        res.verdict = (f"Held up on unseen data: {tst.win_rate:.0%} over {tst.trades} trades "
                       f"(break-even {be:.0%}). Reasonable to follow these settings, with small stakes.")
    elif tst.win_rate > be:
        res.recommended = True
        res.verdict = (f"Above break-even on unseen data ({tst.win_rate:.0%} over {tst.trades} trades), "
                       f"but the range {res.test_low:.0%}-{res.test_high:.0%} still includes losing. Use caution.")
    else:
        res.verdict = (f"Did NOT hold up on unseen data: {tst.win_rate:.0%} over {tst.trades} trades, below the "
                       f"{be:.0%} break-even. The good results were luck. Don't trade this asset/timeframe with the bot.")
    return res


# ---------------------------------------------------------------------------
# saved settings
# ---------------------------------------------------------------------------
def _key(symbol: str, interval: str) -> str:
    return f"{symbol.upper()}|{interval}"


def save_study(res: StudyResult, path: Path = SETTINGS_FILE) -> None:
    try:
        allr = json.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError):
        allr = {}
    allr[_key(res.symbol, res.interval)] = {
        "best": res.best, "recommended": res.recommended, "verdict": res.verdict,
        "test": res.test, "test_low": res.test_low, "test_high": res.test_high,
        "best_hours": _best_hours(res), "lead": lead(),
        "candles": res.candles, "studied_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="minutes"),
    }
    path.write_text(json.dumps(allr, indent=2))


def _best_hours(res) -> str:
    try:
        from .tg_format import best_hours_text
        return best_hours_text(res)
    except Exception:
        return ""


def study_is_recent(symbol: str, interval: str, hours: float = 12, path: Path = SETTINGS_FILE) -> bool:
    rec = load_study(symbol, interval, path)
    if not rec or "studied_at" not in rec or rec.get("lead", 0) != lead():
        return False
    age = pd.Timestamp.now(tz="UTC") - pd.Timestamp(rec["studied_at"])
    return age < pd.Timedelta(hours=hours)


def load_study(symbol: str, interval: str, path: Path = SETTINGS_FILE) -> dict | None:
    try:
        return json.loads(path.read_text()).get(_key(symbol, interval))
    except (OSError, ValueError):
        return None
