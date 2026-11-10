"""Your local time zone. Set TIMEZONE in .env (default Asia/Karachi, UTC+5)."""
from __future__ import annotations

import os
from datetime import timedelta, timezone

import pandas as pd


def tz():
    name = os.getenv("TIMEZONE", "Asia/Karachi")
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:  # no tz database (Windows without tzdata): fall back to UTC+5
        return timezone(timedelta(hours=5), "PKT")


def label() -> str:
    now = pd.Timestamp.now(tz=tz())
    off = now.utcoffset()
    hours = off.total_seconds() / 3600 if off is not None else 0
    abbr = now.tzname() or ""
    if abbr.startswith(("+", "-")) or not abbr:
        abbr = "local"
    return f"{abbr}, UTC{hours:+g}"


def local(ts: pd.Timestamp) -> pd.Timestamp:
    return ts.tz_convert(tz()) if ts.tzinfo else ts.tz_localize("UTC").tz_convert(tz())


def hhmm(ts: pd.Timestamp) -> str:
    return local(ts).strftime("%I:%M %p").lstrip("0")


def utc_hour_range_to_local(h0: int, h1: int) -> str:
    """'16-20 UTC' -> '9 PM-1 AM' in local time."""
    base = pd.Timestamp("2026-01-05", tz="UTC")
    a, b = local(base + pd.Timedelta(hours=h0)), local(base + pd.Timedelta(hours=h1))
    f = lambda t: t.strftime("%I %p").lstrip("0")
    return f"{f(a)}-{f(b)}"


def session_times_local() -> list[tuple[str, str]]:
    from .sessions import SESSIONS
    return [(n, utc_hour_range_to_local(a, b)) for n, (a, b) in SESSIONS.items()]
