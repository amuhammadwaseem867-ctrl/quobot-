"""Telegram message design (HTML parse mode)."""
from __future__ import annotations

import math
from html import escape

from .market_read import MarketRead
from .risk import RiskPlan

LINE = "━━━━━━━━━━━━━━━━━━"
MINUTES = {"1m": 1, "2m": 2, "5m": 5, "15m": 15, "30m": 30, "1h": 60}
GROUP_NAMES = {"trend": "Trend", "momentum": "Momentum", "reversal": "Reversal", "price_action": "Price action"}

DISCLAIMER_SHORT = ("<i>⚠️ Not financial advice. Indicator readings on public data, not guarantees. "
                    "Quotex OTC prices can differ. Trade small and only what you can afford to lose.</i>")


def _p(x: float) -> str:
    return f"{x:,.2f}" if x >= 100 else f"{x:.5f}"


def strength_bar(score: float, n: int = 10) -> str:
    filled = min(n, round(abs(score) / 100 * n))
    return "▰" * filled + "▱" * (n - filled)


def verdict(m: MarketRead, payout: float = 0.85) -> tuple[str, str]:
    """(emoji + label, plain explanation)."""
    s = m.signal
    be = 1 / (1 + payout)
    if s.direction == "WAIT":
        return "⛔ SKIP", "No clear direction right now. Waiting is a position too."
    if any("weekend" in w for w in s.warnings):
        return "⛔ SKIP", "Forex is closed at weekends; Quotex only shows OTC prices, which this bot can't read."
    if m.samples >= 20 and m.hit_rate < be:
        return "⛔ SKIP", (f"Similar signals on {s.symbol} were right only {m.hit_rate:.0%} of the time, "
                          f"below the {be:.0%} you need to break even.")
    problems = []
    if s.confluence < 3:
        problems.append(f"only {s.confluence} of 4 groups agree")
    if m.samples < 20:
        problems.append("not enough history to check the track record")
    if any("quiet" in w or "spike" in w for w in s.warnings):
        problems.append("volatility is unusual")
    if any("higher-timeframe" in w for w in s.warnings):
        problems.append("it goes against the bigger trend")
    if problems:
        return "🟡 CAUTION", "Possible setup, but " + ", ".join(problems) + ". Use a small stake or skip."
    return "✅ VALID SETUP", (f"{s.confluence} of 4 groups agree and similar signals were right "
                             f"{m.hit_rate:.0%} of the time. Still not guaranteed; stick to your stake size.")


def read_message(m: MarketRead, alert: bool = False, payout: float = 0.85) -> str:
    s = m.signal
    be = 1 / (1 + payout)
    if s.direction.startswith("CALL"):
        head, arrow = "🟢", "CALL ⬆️ (price going UP)"
    elif s.direction.startswith("PUT"):
        head, arrow = "🔴", "PUT ⬇️ (price going DOWN)"
    else:
        head, arrow = "⚪", "WAIT (no clear direction)"
    mins = MINUTES.get(s.interval, 1) * m.expiry
    v_label, v_text = verdict(m, payout)

    out = []
    if alert:
        out.append("🔔 <b>NEW SIGNAL</b>")
    out += [
        f"{head} <b>{escape(s.symbol)}</b> · {s.interval} · <b>{arrow}</b>",
        LINE,
        f"💰 Price: <code>{_p(s.price)}</code>",
        f"📊 Strength: {strength_bar(s.score)} <b>{abs(s.score):.0f}</b>/100",
        f"⏱ Expiry: {m.expiry} candle ({mins} min)",
        "",
        f"<b>🧭 Verdict: {v_label}</b>",
        escape(v_text),
        "",
        "<b>🤝 Agreement</b> <i>(4 groups of indicators; more agreeing = stronger)</i>",
    ]
    lean = m.lean
    for g, name in GROUP_NAMES.items():
        val = m.groups.get(g, 0)
        mark = "✅" if lean and val == lean else "❌" if lean and val == -lean else "➖"
        out.append(f"{mark} {name}")

    out += ["", "<b>📖 What the market is doing</b>"]
    out += [f"• {escape(x)}" for x in m.story]

    word, other_word = ("UP", "DOWN") if lean > 0 else ("DOWN", "UP")
    if s.direction == "WAIT":
        for_h, against_h = f"⬆️ Pointing {word}" if lean > 0 else f"⬇️ Pointing {word}", \
            f"⬇️ Pointing {other_word}" if lean > 0 else f"⬆️ Pointing {other_word}"
    else:
        for_h, against_h = f"👍 Reasons for {word}", "👎 Reasons against"
    if m.why:
        out += ["", f"<b>{for_h}</b>"] + [f"• {escape(x)}" for x in m.why[:8]]
    if m.against:
        out += ["", f"<b>{against_h}</b>"] + [f"• {escape(x)}" for x in m.against[:6]]

    if not math.isnan(m.stop):
        side = "below" if lean > 0 else "above"
        out += ["", "<b>🎯 Plan</b>",
                f"• Idea is wrong if a candle closes {side} <code>{_p(m.stop)}</code>",
                f"• Typical move in {mins} min: about <code>{_p(s.atr * math.sqrt(m.expiry))}</code>"]

    out += ["", "<b>📈 Track record</b> <i>(how often this kind of signal was right on this asset)</i>"]
    if m.samples >= 20:
        ok = "✅" if m.hit_rate > be else "❌"
        out.append(f"{ok} Right <b>{m.hit_rate:.0%}</b> of {m.samples} cases · need {be:.0%} to break even")
        exp = " · ".join(f"{e}c {v[0]:.0%}" for e, v in m.hit_by_expiry.items() if v[1] >= 20)
        if exp:
            out.append(f"By expiry (candles): {exp}")
    elif m.samples:
        out.append(f"➖ Only {m.samples} similar cases so far, too few to judge")
    else:
        out.append("➖ No similar cases in recent history")

    other = [w for w in s.warnings]
    if other:
        out += ["", "<b>⚠️ Watch out</b>"] + [f"• {escape(w)}" for w in other]

    out += ["", DISCLAIMER_SHORT]
    return "\n".join(out)


def scan_message(rows, interval: str) -> str:
    out = [f"📡 <b>Market scan</b> · {interval}", LINE]
    for s in rows:
        icon = "🟢" if s.direction.startswith("CALL") else "🔴" if s.direction.startswith("PUT") else "⚪"
        word = "CALL ⬆️" if icon == "🟢" else "PUT ⬇️" if icon == "🔴" else "WAIT"
        out.append(f"{icon} <b>{escape(s.symbol)}</b>  {word}  {strength_bar(s.score, 5)} {abs(s.score):.0f}  · {s.confluence}/4")
    out += ["", "<i>Strength 0-100 · x/4 = groups agreeing. Send an asset name (e.g. EURUSD) for the full explanation.</i>"]
    return "\n".join(out)


def risk_message(plan: RiskPlan) -> str:
    return "\n".join([
        "🛡 <b>Your risk plan</b>", LINE,
        f"💼 Balance: <code>{plan.balance:,.2f}</code>",
        f"🎯 Stake per trade ({plan.risk_pct:g}%): <b>{plan.stake:,.2f}</b>",
        f"🛑 Stop for the day after losing <b>{plan.daily_stop:,.2f}</b> or {plan.max_losses_in_row} losses in a row",
        f"📏 Win rate needed at {plan.payout:.0%} payout: <b>{plan.breakeven_win_rate:.1%}</b>",
        "",
        "<b>Why this matters</b>",
        f"• 5 losses in a row at a flat stake costs {plan.losing_streak_cost():,.2f}.",
        f"• With martingale (doubling after each loss) it costs <b>{plan.martingale_cost():,.2f}</b>. Never do it.",
        "• Trade only signals that agree with the bigger trend.",
        "• Skip news minutes and quiet hours. Never chase losses.",
    ])


HELP_MESSAGE = "\n".join([
    "🤖 <b>Quobot</b> · market analysis assistant", LINE,
    "<b>Ask me</b>",
    "• <code>EURUSD</code> → full market read with prediction and reasons",
    "• <code>EURUSD 5m</code> → same, on 5-minute candles",
    "• /scan → quick signal for every asset I watch",
    "• /risk 100 → stake size and daily stop for a balance of 100",
    "• /watchlist → assets I'm watching",
    "",
    "<b>On my own</b>",
    "🔔 I message you when a new CALL or PUT appears on your watchlist.",
    "",
    "<b>How to read a signal</b>",
    "🟢 CALL = price expected up · 🔴 PUT = down · ⚪ WAIT = no edge",
    "📊 Strength = how strongly indicators agree (0-100)",
    "🧭 Verdict = ✅ valid / 🟡 caution / ⛔ skip",
    "📈 Track record = how often this signal was right before",
    "",
    DISCLAIMER_SHORT,
])
