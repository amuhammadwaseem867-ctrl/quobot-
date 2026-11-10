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

from . import data, risk, telegram
from .market_read import format_read, read_market
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


def run_scan(symbols, interval, threshold, demo, verbose, min_confluence=0):
    results = []
    for sym in symbols:
        try:
            df = data.fetch(sym, interval, demo=demo)
            sig = analyze(df, sym, interval, threshold, crypto=data.is_crypto(sym))
            if sig.direction != "WAIT" and sig.confluence < min_confluence:
                sig.warnings.append(f"Only {sig.confluence}/4 groups agree (need {min_confluence})")
                sig.direction = "WAIT"
            results.append(sig)
        except Exception as e:  # keep going if one feed fails
            print(f"  {sym:<9} error: {e}", file=sys.stderr)
    results.sort(key=lambda s: -abs(s.score))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\nQuobot market scan  |  {interval} candles  |  {now}" + ("  |  DEMO DATA" if demo else ""))
    print("-" * 86)
    print(f"{'Asset':<9} {'Price':>12}  {'Score':>6}  {'Bias':<11} {'Agree':<5} {'Regime':<9} {'RSI':>4}  Strength")
    for s in results:
        print(f"{s.symbol:<9} {fmt_price(s.price):>12}  {s.score:>+6.0f}  {s.direction:<11} {s.confluence}/4   "
              f"{s.regime:<9} {s.rsi:>4.0f}  {bar(s.score)}")
        if verbose or s.direction != "WAIT":
            for r in s.reasons:
                print(f"{'':12}- {r}")
            if s.supports or s.resistances:
                sup = ", ".join(f"{fmt_price(p)} ({n}x)" for p, n in s.supports) or "none nearby"
                res = ", ".join(f"{fmt_price(p)} ({n}x)" for p, n in s.resistances) or "none nearby"
                print(f"{'':12}- Support: {sup} | Resistance: {res}")
            for w in s.warnings:
                print(f"{'':12}! {w}")
    print("-" * 86)
    print("Agree = how many of the 4 groups (trend, momentum, reversal, price action) back the bias.")
    print(DISCLAIMER + "\n")
    return results


def cmd_telegram_chatid(_args):
    token, _ = telegram.credentials()
    if not token:
        sys.exit("Set TELEGRAM_BOT_TOKEN first (in .env or the environment).")
    try:
        chats = telegram.find_chat_ids(token)
    except RuntimeError as e:
        sys.exit(f"{e}\n{telegram.UNREACHABLE_HINT}")
    if not chats:
        sys.exit("No messages found. Open your bot in Telegram, send it any message, then run this again.")
    print("Chats that messaged your bot:")
    for cid, name in chats:
        print(f"  TELEGRAM_CHAT_ID={cid}    ({name})")


def cmd_telegram_test(_args):
    token, chat = telegram.credentials()
    if not (token and chat):
        sys.exit("Set both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID first (in .env or the environment).")
    if telegram.send("Quobot is connected. You'll get alerts here when an asset's bias changes.\n\n" + DISCLAIMER):
        print("Test message sent. Check Telegram.")
    else:
        sys.exit(1)


def cmd_watch(args):
    step = INTERVAL_SECONDS.get(args.interval, 60)
    last_alert: dict[str, str] = {}
    alerts = "Telegram alerts ON" if all(telegram.credentials()) else "Telegram alerts off (no token/chat id)"
    print(f"Watching {', '.join(args.symbols)} on {args.interval}. {alerts}. Ctrl+C to stop.")
    while True:
        results = run_scan(args.symbols, args.interval, args.threshold, args.demo, args.verbose, args.min_agree)
        for s in results:
            if s.direction != "WAIT" and last_alert.get(s.symbol) != s.direction:
                try:
                    df = data.fetch(s.symbol, s.interval, 1000, demo=args.demo)
                    m = read_market(df, s.symbol, s.interval, data.is_crypto(s.symbol), 1, args.threshold)
                    text = format_read(m)
                except Exception:
                    text = f"{s.symbol} {s.interval}: {s.direction}, score {s.score:+.0f}"
                telegram.send(f"{text}\n\n{DISCLAIMER}")
            last_alert[s.symbol] = s.direction
        # sleep until a few seconds after the next candle closes
        wait = step - (time.time() % step) + 3
        time.sleep(wait)


def cmd_backtest(args):
    print(f"\nBacktest | {args.interval} candles | expiry {args.expiry} candle(s) | "
          f"threshold {args.threshold} | payout {args.payout:.0%}")
    print("-" * 84)
    print(f"{'Asset':<9} {'Signals':>8} {'Win rate':>9} {'Net units':>10}   "
          f"{'No filters: signals':>20} {'win rate':>9} {'net':>7}")
    be = 1 / (1 + args.payout)
    for sym in args.symbols:
        try:
            df = data.fetch(sym, args.interval, 1000, demo=args.demo)
            c = data.is_crypto(sym)
            r = backtest(df, sym, args.expiry, args.threshold, args.payout, crypto=c)
            raw = backtest(df, sym, args.expiry, args.threshold, args.payout, crypto=c, use_filters=False)
            print(f"{sym:<9} {r.signals:>8} {r.win_rate:>9.1%} {r.net_units:>+10.1f}   "
                  f"{raw.signals:>20} {raw.win_rate:>9.1%} {raw.net_units:>+7.1f}")
        except Exception as e:
            print(f"{sym:<9} error: {e}", file=sys.stderr)
    print("-" * 84)
    print(f"Break-even win rate at {args.payout:.0%} payout: {be:.1%}. Below that, the signals lost money.")
    print("'No filters' ignores the higher-timeframe, volatility and session filters, for comparison.")
    print(DISCLAIMER + "\n")


def cmd_read(args):
    for sym in args.symbols:
        try:
            df = data.fetch(sym, args.interval, 1000, demo=args.demo)
            m = read_market(df, sym, args.interval, data.is_crypto(sym), args.expiry, args.threshold)
            print("\n" + "=" * 78 + "\n" + format_read(m, args.payout))
        except Exception as e:
            print(f"{sym}: error: {e}", file=sys.stderr)
    print("=" * 78 + "\n" + DISCLAIMER + "\n")


def cmd_risk(args):
    plan = risk.RiskPlan(args.balance, args.risk, args.daily_loss, args.max_losses, args.payout)
    print("\nRisk plan\n" + "-" * 60)
    print(plan.summary())
    print("-" * 60 + "\n" + DISCLAIMER + "\n")


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
    s.add_argument("--min-agree", type=int, default=0, help="only show CALL/PUT when this many of 4 groups agree")
    s.set_defaults(func=lambda a: run_scan(a.symbols, a.interval, a.threshold, a.demo, a.verbose, a.min_agree))

    w = sub.add_parser("watch", help="re-scan at every candle close, optional Telegram alerts")
    common(w)
    w.add_argument("-v", "--verbose", action="store_true")
    w.add_argument("--min-agree", type=int, default=2, help="only alert when this many of 4 groups agree (default 2)")
    w.set_defaults(func=cmd_watch)

    b = sub.add_parser("backtest", help="measure how past signals would have done")
    common(b)
    b.add_argument("--expiry", type=int, default=1, help="expiry in candles (1 = one candle ahead)")
    b.add_argument("--payout", type=float, default=0.85, help="broker payout, e.g. 0.85 for 85%%")
    b.set_defaults(func=cmd_backtest)

    rd = sub.add_parser("read", help="plain-language market read: prediction, reasons, invalidation, track record")
    common(rd)
    rd.add_argument("--expiry", type=int, default=1, help="prediction horizon in candles (default 1)")
    rd.add_argument("--payout", type=float, default=0.85)
    rd.set_defaults(func=cmd_read)

    r = sub.add_parser("risk", help="stake size and daily stop for your balance")
    r.add_argument("balance", type=float, help="your account balance")
    r.add_argument("--risk", type=float, default=1.0, help="%% of balance per trade (default 1)")
    r.add_argument("--daily-loss", type=float, default=5.0, help="daily loss limit in %% (default 5)")
    r.add_argument("--max-losses", type=int, default=3, help="stop after this many losses in a row")
    r.add_argument("--payout", type=float, default=0.85)
    r.set_defaults(func=cmd_risk)

    tg = sub.add_parser("telegram-chatid", help="show the chat id of whoever messaged your bot")
    tg.set_defaults(func=cmd_telegram_chatid)
    tt = sub.add_parser("telegram-test", help="send a test alert to Telegram")
    tt.set_defaults(func=cmd_telegram_test)

    telegram.load_env()
    args = p.parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
