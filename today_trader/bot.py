"""Two-way Telegram bot: sends alerts at every candle close and answers your
messages in between. It only answers the chat id in your .env, so strangers
who find your bot can't use it."""
from __future__ import annotations

import sys
import time

from . import data, risk, telegram
from .market_read import read_market
from .study import load_study
from .tg_format import HELP_MESSAGE, read_message, risk_message, scan_message, sessions_message, study_message
from .signals import DEFAULT_THRESHOLD, analyze

INTERVALS = {"1m", "2m", "5m", "15m", "30m", "1h"}


class QuobotChat:
    def __init__(self, symbols, interval, threshold=DEFAULT_THRESHOLD, min_agree=2,
                 history=10000, demo=False, disclaimer="", study_fn=None):
        self.symbols, self.interval = list(symbols), interval
        self.threshold, self.min_agree = threshold, min_agree
        self.history, self.demo, self.disclaimer = history, demo, disclaimer
        self.study_fn = study_fn

    # ---- replies --------------------------------------------------------
    def read_text(self, symbol: str, interval: str | None = None) -> str:
        iv = interval or self.interval
        df = data.fetch(symbol, iv, self.history, demo=self.demo)
        learned = load_study(symbol, iv)
        expiry = learned["best"]["expiry"] if learned and learned.get("best") else 1
        m = read_market(df, symbol, iv, data.is_crypto(symbol), expiry, self.threshold)
        return read_message(m)

    def scan_text(self) -> str:
        rows, errors = [], []
        for sym in self.symbols:
            try:
                df = data.fetch(sym, self.interval, demo=self.demo)
                rows.append(analyze(df, sym, self.interval, self.threshold, crypto=data.is_crypto(sym)))
            except Exception as e:
                errors.append(f"⚠️ {sym}: couldn't load data ({type(e).__name__})")
        text = scan_message(sorted(rows, key=lambda s: -abs(s.score)), self.interval)
        return text + ("\n" + "\n".join(errors) if errors else "")

    def reply(self, text: str) -> str:
        parts = text.strip().split()
        if not parts:
            return HELP_MESSAGE
        cmd = parts[0].lower().split("@")[0]
        if cmd in ("/start", "/help", "help"):
            return HELP_MESSAGE
        if cmd == "/scan":
            return self.scan_text()
        if cmd == "/sessions":
            return sessions_message()
        if cmd == "/study":
            if len(parts) < 2:
                return "Send it like this: <code>/study EURUSD</code> (or <code>/study EURUSD 5m</code>)"
            sym = parts[1].upper()
            iv = parts[2].lower() if len(parts) > 2 and parts[2].lower() in INTERVALS else self.interval
            if self.study_fn is None:
                from .study import study
                df = data.fetch(sym, iv, self.history, demo=self.demo)
                return study_message(study(df, sym, iv, data.is_crypto(sym)))
            return study_message(self.study_fn(sym, iv, self.demo))
        if cmd == "/watchlist":
            return "👀 <b>Watchlist</b> · " + self.interval + "\n" + "\n".join(f"• {x}" for x in self.symbols)
        if cmd == "/risk":
            try:
                bal = float(parts[1])
            except (IndexError, ValueError):
                return "Send it like this: <code>/risk 100</code>"
            return risk_message(risk.RiskPlan(bal))
        symbol = parts[0].upper().lstrip("/")
        interval = parts[1].lower() if len(parts) > 1 and parts[1].lower() in INTERVALS else None
        try:
            return self.read_text(symbol, interval)
        except Exception as e:
            return (f"🤔 Couldn't analyse <b>{symbol}</b> ({type(e).__name__}).\n"
                    "Check the name, e.g. <code>EURUSD</code>, <code>XAUUSD</code>, <code>BTCUSDT</code>. Send /help for commands.")

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
        telegram.send("🤖 <b>Quobot is online</b>\nWatching " + ", ".join(self.symbols) + f" on {self.interval}.\n"
                      "I'll message you when a new signal appears. Send /help to see what I can do.", html=True)
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
                    answer = f"😕 Something went wrong ({type(e).__name__}). Try again in a minute."
                try:
                    telegram.send_to(chat, answer, html=True)
                except RuntimeError as e:
                    print(f"Telegram send failed: {e}", file=sys.stderr)
