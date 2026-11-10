"""Public market data feeds.

- Forex, metals, indices, stocks: Yahoo Finance chart endpoint (no key needed).
- Crypto: Binance public klines (no key needed).
- Demo: synthetic random-walk candles, for trying the bot offline.

Quotex "OTC" assets are priced by the broker itself and are not available from
any public feed, so they can't be analysed here. Use the regular market pairs.
"""
from __future__ import annotations

import zlib

import numpy as np
import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (today-trader market analysis)"}

from .assets import YAHOO as YAHOO_ALIASES  # noqa: E402

CRYPTO_QUOTES = ("USDT", "USDC", "BUSD", "FDUSD")

# Yahoo needs a range big enough for the interval
# Yahoo's limits: 1m data for the last 30 days, max 7 days per request;
# 2m-30m for the last 60 days; hourly for about 2 years.
YAHOO_RANGE = {"1m": "7d", "2m": "60d", "5m": "60d", "15m": "60d", "30m": "60d", "1h": "2y", "1d": "10y"}
YAHOO_INTERVAL = {"1h": "60m"}


def is_crypto(symbol: str) -> bool:
    return symbol.upper().endswith(CRYPTO_QUOTES)


def yahoo_ticker(symbol: str) -> str:
    s = symbol.upper().replace("/", "")
    if s in YAHOO_ALIASES:
        return YAHOO_ALIASES[s]
    if len(s) == 6 and s.isalpha():  # EURUSD -> EURUSD=X
        return f"{s}=X"
    return symbol


def _yahoo_request(ticker: str, params: dict) -> pd.DataFrame:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    r = requests.get(url, params=params, headers=UA, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    if "timestamp" not in res:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    q = res["indicators"]["quote"][0]
    return pd.DataFrame(
        {k: q[k] for k in ("open", "high", "low", "close", "volume")},
        index=pd.to_datetime(res["timestamp"], unit="s", utc=True),
    ).dropna(subset=["open", "high", "low", "close"])


def fetch_yahoo(symbol: str, interval: str = "5m", limit: int = 300) -> pd.DataFrame:
    ticker = yahoo_ticker(symbol)
    iv = YAHOO_INTERVAL.get(interval, interval)
    df = _yahoo_request(ticker, {"interval": iv, "range": YAHOO_RANGE.get(interval, "5d")})
    if interval == "1m" and len(df) < limit:
        # page back in 7-day chunks (Yahoo keeps 1m data for ~30 days)
        frames = [df]
        end = int(df.index[0].timestamp()) if len(df) else int(pd.Timestamp.now(tz="UTC").timestamp())
        for _ in range(3):
            start = end - 7 * 86400
            try:
                part = _yahoo_request(ticker, {"interval": iv, "period1": start, "period2": end})
            except Exception:
                break
            if part.empty:
                break
            frames.insert(0, part)
            end = int(part.index[0].timestamp())
            if sum(len(f) for f in frames) >= limit:
                break
        df = pd.concat(frames)
        df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.tail(limit)


def fetch_binance(symbol: str, interval: str = "5m", limit: int = 300) -> pd.DataFrame:
    """Binance gives 1000 candles per request; page backwards for more."""
    url = "https://api.binance.com/api/v3/klines"
    sym = symbol.upper().replace("/", "")
    rows: list = []
    end = None
    while len(rows) < limit:
        params = {"symbol": sym, "interval": interval, "limit": min(1000, limit - len(rows))}
        if end is not None:
            params["endTime"] = end
        r = requests.get(url, params=params, headers=UA, timeout=30)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows = batch + rows
        end = batch[0][0] - 1
        if len(batch) < params["limit"]:
            break
    df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume", *range(6)])
    df.index = pd.to_datetime(df["t"], unit="ms", utc=True)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def demo_candles(symbol: str = "DEMO", n: int = 300, seed: int | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    drift = rng.normal(0, 0.0002)
    rets = rng.normal(drift, 0.001, n)
    close = 1.1 * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]]
    spread = np.abs(rng.normal(0, 0.0006, n)) * close
    # demo candles are placed on a weekday afternoon (London/NY overlap)
    end = pd.Timestamp("2026-11-10 15:00", tz="UTC")
    idx = pd.date_range(end=end, periods=n, freq="5min")
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + spread,
            "low": np.minimum(open_, close) - spread,
            "close": close,
            "volume": rng.integers(100, 1000, n).astype(float),
        },
        index=idx,
    )


INTERVAL_DELTA = {"1m": "1min", "2m": "2min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "1d": "1D"}


def drop_open_candle(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    """Remove the last candle if it hasn't closed yet. Analysing a half-formed
    candle gives signals that change before the candle ends."""
    if df.empty:
        return df
    end = df.index[-1] + pd.Timedelta(INTERVAL_DELTA.get(interval, "1min"))
    if end > pd.Timestamp.now(tz="UTC"):
        return df.iloc[:-1]
    return df


def fetch(symbol: str, interval: str = "5m", limit: int = 600, demo: bool = False) -> pd.DataFrame:
    if demo:
        return demo_candles(symbol, limit, seed=zlib.crc32(symbol.encode()))
    if is_crypto(symbol):
        df = fetch_binance(symbol, interval, limit + 1)
    else:
        df = fetch_yahoo(symbol, interval, limit + 1)
    return drop_open_candle(df, interval).tail(limit)


def is_fresh(df: pd.DataFrame, interval: str, candles: int = 5) -> bool:
    """False when the newest candle is old: the market is closed (stocks at
    night, forex at weekends) or the feed has stalled."""
    if df.empty:
        return False
    age = pd.Timestamp.now(tz="UTC") - df.index[-1]
    return age <= pd.Timedelta(INTERVAL_DELTA.get(interval, "1min")) * candles
