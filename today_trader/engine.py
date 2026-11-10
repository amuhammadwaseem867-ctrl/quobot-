"""Analyse many assets at once (in parallel), skipping closed markets."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from . import data
from .signals import DEFAULT_THRESHOLD, Signal, analyze


def mark_closed(sig: Signal) -> Signal:
    sig.direction = "WAIT"
    sig.warnings.insert(0, "Market closed or no fresh prices right now")
    return sig


def analyze_symbol(sym: str, interval: str, threshold: float = DEFAULT_THRESHOLD,
                   demo: bool = False, min_agree: int = 0) -> Signal:
    df = data.fetch(sym, interval, demo=demo)
    sig = analyze(df, sym, interval, threshold, crypto=data.is_crypto(sym))
    if not demo and not data.is_fresh(df, interval):
        return mark_closed(sig)
    if sig.direction != "WAIT" and sig.confluence < min_agree:
        sig.warnings.append(f"Only {sig.confluence}/4 groups agree (need {min_agree})")
        sig.direction = "WAIT"
    return sig


def analyze_many(symbols, interval, threshold=DEFAULT_THRESHOLD, demo=False, min_agree=0, workers=8):
    """Returns (signals sorted strongest first, {symbol: error})."""
    def one(sym):
        try:
            return sym, analyze_symbol(sym, interval, threshold, demo, min_agree), None
        except Exception as e:  # keep going if one feed fails
            return sym, None, f"{type(e).__name__}: {e}"[:120]

    with ThreadPoolExecutor(max_workers=workers) as ex:
        out = list(ex.map(one, symbols))
    sigs = [s for _, s, _ in out if s is not None]
    errors = {sym: e for sym, _, e in out if e}
    sigs.sort(key=lambda s: (s.direction == "WAIT", -abs(s.score)))
    return sigs, errors
