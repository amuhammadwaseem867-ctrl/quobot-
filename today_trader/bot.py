"""Two-way Telegram bot: sends alerts at every candle close and answers your
messages in between. It only answers the chat id in your .env, so strangers
who find your bot can't use it."""
from __future__ import annotations

import sys
import time

from . import data, risk, telegram
from .market_read import format_read, read_market
from .signals import DEFAULT_THRESHOLD, analyze

HELP = """Quobot commands:
EURUSD          market read for an asset (any asset name works)
EURUSD 5m       same, on another timeframe (1m 2m 5m 15m 30m 1h)
/scan           signals for your whole watchlist
/risk 100       stake size and daily stop for a balance of 100
/watchlist      show the assets being watched
/help           this message

You also get an automatic alert when a strong signal appears."""

INTERVALS = {"1m", "2m", "5m", "15m", "30m", "1h"}


class QuobotChat:
    def __init__(self, symbols, interval, threshold=DEFAULT_THRESHOLD, min_agree=2,
                 history=4000, demo=False, disclaimer=""):
        self.symbols, self.interval = list(symbols), interval
        self.threshold, self.min_agree = threshold, min_agree
        self.history, self.demo, self.disclaimer = history, demo, disclaimer

    # ---- replies --------------------------------------------------------
    def read_text(self, symbol: str, interval: str | None = None) -> str:
        iv = interval or self.interval
        df = data.fetch(symbol, iv, self.history, demo=self.demo)
        m = read_market(df, symbol, iv, data.is_crypto(symbol), 1, self.threshold)
        return format_read(m)

    def scan_text(self) -> str:
        lines = [f"Scan ({self.interval}):"]
        rows = []
        for sym in self.symbols:
            try:
                df = data.fetch(sym, self.interval, demo=self.demo)
                s = analyze(df, sym, self.interval, self.threshold, crypto=data.is_crypto(sym))
                rows.append(s)
            except Exception as e:
                lines.append(f"{sym}: error ({type(e).__name__})")
        for s in sorted(rows, key=lambda s: -abs(s.score)):
            lines.append(f"{s.symbol}: {s.direction}, score {s.score:+.0f}, {s.confluence}/4 agree")
        lines.append("\nSend an asset name for the full read.")
        return "\n".join(lines)

    def reply(self, text: str) -> str:
        parts = text.strip().split()
        if not parts:
            return HELP
        cmd = parts[0].lower().split("@")[0]
        if cmd in ("/start", "/help", "help"):
            return HELP
        if cmd == "/scan":
            return self.scan_text()
        if cmd == "/watchlist":
            return "Watching: " + ", ".join(self.symbols) + f" on {self.interval}"
        if cmd == "/risk":
            try:
                bal = float(parts[1])
            except (IndexError, ValueError):
                return "Send it like this: /risk 100"
            return risk.RiskPlan(bal).summary()
        symbol = parts[0].upper().lstrip("/")
        interval = parts[1].lower() if len(parts) > 1 and parts[1].lower() in INTERVALS else None
        try:
            return self.read_text(symbol, interval)
        except Exception as e:
            return f"Couldn't analyse {symbol} ({type(e).__name__}). Check the name, e.g. EURUSD, XAUUSD, BTCUSDT."

    # ---- main loop ------------------------------------------------------
    def run(self, step_seconds: int, alert_fn) -> None:
        token, chat = telegram.credentials()
        if not (token and chat):
            sys.exit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env first.")
        offset = None
        # skip messages sent while the bot was off
        try:
            old = telegram.get_updates(token, None, 0)
            if old:
                offset = old[-1]["update_id"] + 1
        except RuntimeError as e:
            sys.exit(f"{e}\n{telegram.UNREACHABLE_HINT}")
        telegram.send("Quobot is online. Send /help to see what I can do.")
        print("Bot running: answering Telegram messages and sending alerts. Ctrl+C to stop.")
        next_alert = 0.0
        while True:
            now = time.time()
            if now >= next_alert:
                alert_fn()
                next_alert = now - (now % step_seconds) + step_seconds + 3
            wait = int(min(25, max(1, next_alert - time.time())))
            try:
                updates = telegram.get_updates(token, offset, wait)
            except RuntimeError as e:
                print(f"Telegram: {e}; retrying in 10s", file=sys.stderr)
                time.sleep(10)
                continue
            for u in updates:
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                if str(msg.get("chat", {}).get("id")) != str(chat) or "text" not in msg:
                    continue  # ignore anyone who isn't you
                print(f"> {msg['text']}")
                try:
                    answer = self.reply(msg["text"])
                except Exception as e:
                    answer = f"Something went wrong ({type(e).__name__})."
                try:
                    telegram.send_to(chat, answer + ("\n\n" + self.disclaimer if self.disclaimer else ""))
                except RuntimeError as e:
                    print(f"Telegram send failed: {e}", file=sys.stderr)
