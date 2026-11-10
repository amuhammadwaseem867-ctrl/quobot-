"""Command line entry point.

    python -m today_trader scan                 # analyse default watchlist once
    python -m today_trader scan EURUSD BTCUSDT -i 1m
    python -m today_trader watch -i 1m          # re-scan at every new candle
    python -m today_trader backtest EURUSD -i 5m --expiry 1
    python -m today_trader scan --demo          # offline, synthetic data
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone

import requests

from . import data
from .backtest import backtest
from .signals import DEFAULT_THRESHOLD, analyze

DISCLAIMER = (
    "Not financial advice. These are indicator readings on public market data, "
    "not predictions. Quotex OTC prices are set by the broker and may differ "
    "from these feeds. Binary options are high risk; most traders lose money."
)

DEFAULT_WATCHLIST = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "EURJPY", "XAUUSD", "BTCUSDT", "ETHUSDT"]
INTERVAL_SECONDS = {"1m": 60, "2m": 120, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}


def fmt_price(p: float) -> str:
    return f"{p:,.2f}" if p >= 100 else f"{p:.5f}"


def bar(score: float, width: int = 20) -> str:
    half = width // 2
    n = round(abs(score) / 100 * half)
    left = " " * half if score >= 0 else " " * (half - n) + "<" * n
    right = ">" * n + " " * (half - n) if score >= 0 else " " * half
    return f"[{left}|{right}]"


def run_scan(symbols, interval, threshold, demo, verbose):
    results = []
    for sym in symbols:
        try:
            df = data.fetch(sym, interval, 300, demo=demo)
            results.append(analyze(df, sym, interval, threshold))
        except Exception as e:  # keep going if one feed fails
            print(f"  {sym:<9} error: {e}", file=sys.stderr)
    results.sort(key=lambda s: -abs(s.score))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\nToday Trader market scan  |  {interval} candles  |  {now}" + ("  |  DEMO DATA" if demo else ""))
    print("-" * 78)
    print(f"{'Asset':<9} {'Price':>12}  {'Score':>6}  {'Bias':<11} {'Regime':<9} {'RSI':>4}  Strength")
    for s in results:
        print(f"{s.symbol:<9} {fmt_price(s.price):>12}  {s.score:>+6.0f}  {s.direction:<11} {s.regime:<9} "
              f"{s.rsi:>4.0f}  {bar(s.score)}")
        if verbose or s.direction != "WAIT":
            for r in s.reasons:
                print(f"{'':12}- {r}")
    print("-" * 78)
    print(DISCLAIMER + "\n")
    return results


def send_telegram(text: str) -> None:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": text}, timeout=15)
    except requests.RequestException as e:
        print(f"Telegram send failed: {e}", file=sys.stderr)


def cmd_watch(args):
    step = INTERVAL_SECONDS.get(args.interval, 60)
    last_alert: dict[str, str] = {}
    print(f"Watching {', '.join(args.symbols)} on {args.interval}. Ctrl+C to stop.")
    while True:
        results = run_scan(args.symbols, args.interval, args.threshold, args.demo, args.verbose)
        for s in results:
            if s.direction != "WAIT" and last_alert.get(s.symbol) != s.direction:
                send_telegram(
                    f"{s.symbol} {s.interval}: {s.direction} bias, score {s.score:+.0f} "
                    f"({s.regime}, RSI {s.rsi:.0f}) at {fmt_price(s.price)}\n\n{DISCLAIMER}"
                )
            last_alert[s.symbol] = s.direction
        # sleep until a few seconds after the next candle closes
        wait = step - (time.time() % step) + 3
        time.sleep(wait)


def cmd_backtest(args):
    print(f"\nBacktest | {args.interval} candles | expiry {args.expiry} candle(s) | "
          f"threshold {args.threshold} | payout {args.payout:.0%}")
    print("-" * 70)
    print(f"{'Asset':<9} {'Signals':>8} {'Wins':>6} {'Win rate':>9} {'Break-even':>11} {'Net units':>10}")
    for sym in args.symbols:
        try:
            df = data.fetch(sym, args.interval, 1000, demo=args.demo)
            r = backtest(df, sym, args.expiry, args.threshold, args.payout)
            print(f"{sym:<9} {r.signals:>8} {r.wins:>6} {r.win_rate:>9.1%} {r.breakeven:>11.1%} {r.net_units:>+10.1f}")
        except Exception as e:
            print(f"{sym:<9} error: {e}", file=sys.stderr)
    print("-" * 70)
    print("A win rate below break-even means the signals lost money on this history.")
    print(DISCLAIMER + "\n")


def main(argv=None):
    p = argparse.ArgumentParser(prog="today_trader", description="Market analysis signals for the assets you trade.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("symbols", nargs="*", default=DEFAULT_WATCHLIST,
                        help="e.g. EURUSD GBPJPY XAUUSD BTCUSDT (default: a forex + crypto watchlist)")
        sp.add_argument("-i", "--interval", default="5m", choices=list(INTERVAL_SECONDS))
        sp.add_argument("-t", "--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help="minimum |score| (0-100) before a direction is shown")
        sp.add_argument("--demo", action="store_true", help="use synthetic offline data")

    s = sub.add_parser("scan", help="analyse assets once")
    common(s)
    s.add_argument("-v", "--verbose", action="store_true", help="show reasons for every asset")
    s.set_defaults(func=lambda a: run_scan(a.symbols, a.interval, a.threshold, a.demo, a.verbose))

    w = sub.add_parser("watch", help="re-scan at every candle close, optional Telegram alerts")
    common(w)
    w.add_argument("-v", "--verbose", action="store_true")
    w.set_defaults(func=cmd_watch)

    b = sub.add_parser("backtest", help="measure how past signals would have done")
    common(b)
    b.add_argument("--expiry", type=int, default=1, help="expiry in candles (1 = one candle ahead)")
    b.add_argument("--payout", type=float, default=0.85, help="broker payout, e.g. 0.85 for 85%%")
    b.set_defaults(func=cmd_backtest)

    args = p.parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
