"""Two-way Telegram bot: sends alerts at every candle close and answers your
messages in between. It only answers the chat id in your .env, so strangers
who find your bot can't use it."""
from __future__ import annotations

import sys
import time

import pandas as pd

from . import assets, data, risk, telegram
from .engine import analyze_many, mark_closed
from .market_read import read_market
from .study import load_study
from .tg_format import HELP_MESSAGE, assets_message, read_message, risk_message, scan_message, sessions_message, study_message
from .signals import DEFAULT_THRESHOLD, analyze

INTERVALS = {"1m", "2m", "5m", "15m", "30m", "1h"}


class QuobotChat:
    def __init__(self, symbols, interval, threshold=DEFAULT_THRESHOLD, min_agree=2,
                 history=10000, demo=False, disclaimer="", study_fn=None,
                 picks_every=5, picks_from=None, top=3, send_empty=True, min_winrate=0.0):
        self.symbols, self.interval = list(symbols), interval
        self.threshold, self.min_agree = threshold, min_agree
        self.history, self.demo, self.disclaimer = history, demo, disclaimer
        self.study_fn = study_fn
        self.picks_every, self.top, self.send_empty = picks_every, top, send_empty
        self.picks_from = list(picks_from) if picks_from else list(symbols)
        self.pending: list = []
        self.min_winrate = min_winrate

    # ---- replies --------------------------------------------------------
    def read_text(self, symbol: str, interval: str | None = None) -> str:
        iv = interval or self.interval
        df = data.fetch(symbol, iv, self.history, demo=self.demo)
        learned = load_study(symbol, iv)
        expiry = learned["best"]["expiry"] if learned and learned.get("best") else 1
        m = read_market(df, symbol, iv, data.is_crypto(symbol), expiry, self.threshold)
        if not self.demo and not data.is_fresh(df, iv):
            mark_closed(m.signal)
        return read_message(m)

    def scan_text(self, group: str | None = None) -> str:
        symbols = assets.expand([group]) if group else self.symbols
        title = f"Scan: {group}" if group else "Watchlist scan"
        rows, errors = analyze_many(symbols, self.interval, self.threshold, self.demo)
        return scan_message(rows, self.interval, errors, title)

    def reply(self, text: str) -> str:
        parts = text.strip().split()
        if not parts:
            return HELP_MESSAGE
        cmd = parts[0].lower().split("@")[0]
        if cmd in ("/start", "/help", "help"):
            return HELP_MESSAGE
        if cmd == "/scan":
            return self.scan_text(parts[1] if len(parts) > 1 else None)
        if cmd == "/picks":
            return self.picks_job(send=False)
        if cmd == "/results":
            from .picks import today_results
            from .tg_format import results_message
            return results_message(today_results())
        if cmd == "/assets":
            return assets_message()
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
            return ("👀 <b>Watchlist</b> · " + self.interval + f" · {len(self.symbols)} assets\n"
                    + ", ".join(self.symbols) + "\n\nI send an alert when any of these gives a signal.")
        if cmd == "/risk":
            try:
                bal = float(parts[1])
            except (IndexError, ValueError):
                return "Send it like this: <code>/risk 100</code>"
            return risk_message(risk.RiskPlan(bal))
        symbol = assets.normalize(parts[0].lstrip("/"))
        interval = parts[1].lower() if len(parts) > 1 and parts[1].lower() in INTERVALS else None
        try:
            return self.read_text(symbol, interval)
        except Exception as e:
            return (f"🤔 Couldn't analyse <b>{symbol}</b> ({type(e).__name__}).\n"
                    "Check the name, e.g. <code>EURUSD</code>, <code>XAUUSD</code>, <code>BTCUSDT</code>. Send /help for commands.")

    # ---- main loop ------------------------------------------------------
    # ---- automatic picks -------------------------------------------------
    def picks_job(self, send=True) -> str:
        from .picks import find_picks, log_pick
        from .tg_format import picks_message
        found, stats = find_picks(self.picks_from, self.interval, self.top, self.threshold,
                                  self.demo, self.history, study_fn=self.study_fn, min_winrate=self.min_winrate)
        for p, _ in found:
            if not any(q.symbol == p.symbol and q.end_time == p.end_time for q in self.pending):
                self.pending.append(p)
        nxt = None
        if self.picks_every:
            now = pd.Timestamp.now(tz="UTC")
            nxt = now.floor(f"{self.picks_every}min") + pd.Timedelta(minutes=self.picks_every)
        text = picks_message(found, stats, self.interval, nxt)
        if send and (found or self.send_empty):
            telegram.send(text, html=True)
        print(f"[picks] {len(found)} pick(s), {stats}")
        return text

    def results_job(self) -> None:
        from .picks import check_result, log_pick, today_results
        from .tg_format import result_message
        still = []
        for p in self.pending:
            try:
                done = check_result(p, self.demo)
            except Exception:
                done = None
            if done is None:
                still.append(p)
                continue
            log_pick(done)
            telegram.send(result_message(done, today_results()), html=True)
        self.pending = still

    # ---- main loop ------------------------------------------------------
    def run(self, step_seconds: int, alert_fn=None) -> None:
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
        lines = ["🤖 <b>Quobot is online</b>"]
        if self.picks_every:
            lines.append(f"🎯 Every {self.picks_every} min I check {len(self.picks_from)} assets and send the "
                         f"top {self.top} safe trades, then the result of each one.")
        if alert_fn:
            lines.append(f"🔔 Alerts on for: {', '.join(self.symbols)}")
        lines.append("Send /help to see what I can do.")
        telegram.send("\n".join(lines), html=True)
        print("Bot running. Ctrl+C to stop.")

        jobs = []  # [period_seconds, next_run, fn]
        if alert_fn:
            jobs.append([step_seconds, 0.0, alert_fn])
        if self.picks_every:
            jobs.append([self.picks_every * 60, 0.0, self.picks_job])
        jobs.append([15, 0.0, self.results_job])
        while True:
            now = time.time()
            for job in jobs:
                if now >= job[1]:
                    try:
                        job[2]()
                    except Exception as e:  # a failed round must not stop the bot
                        print(f"job error: {type(e).__name__}: {e}", file=sys.stderr)
                    job[1] = now - (now % job[0]) + job[0] + 3
            wait = int(min(25, max(1, min(j[1] for j in jobs) - time.time())))
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
