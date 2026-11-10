"""Forex trading sessions. Signals are most reliable when the market is
liquid (London, New York and their overlap) and least reliable in the quiet
hours between the New York close and Tokyo open."""
from __future__ import annotations

import pandas as pd

# UTC hours (approximate, ignoring daylight-saving shifts)
SESSIONS = {
    "Sydney": (21, 6),
    "Tokyo": (0, 9),
    "London": (7, 16),
    "New York": (12, 21),
}


def _in(hour: int, start: int, end: int) -> bool:
    return start <= hour < end if start < end else hour >= start or hour < end


def active_sessions(ts: pd.Timestamp) -> list[str]:
    h = ts.tz_convert("UTC").hour if ts.tzinfo else ts.hour
    return [n for n, (a, b) in SESSIONS.items() if _in(h, a, b)]


def session_quality(ts: pd.Timestamp, crypto: bool = False) -> tuple[float, str]:
    """(multiplier for signal confidence, label)."""
    if crypto:
        return 1.0, "24/7 market"
    if ts.weekday() >= 5:
        return 0.0, "weekend: forex closed (Quotex shows OTC only)"
    act = active_sessions(ts)
    if "London" in act and "New York" in act:
        return 1.0, "London/New York overlap (best liquidity)"
    if "London" in act or "New York" in act:
        return 0.9, f"{' + '.join(act)} session"
    if "Tokyo" in act:
        return 0.75, "Asian session (quieter, more ranging)"
    return 0.6, "low liquidity hours"
