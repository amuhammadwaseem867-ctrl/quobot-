"""Telegram message design (HTML parse mode)."""
from __future__ import annotations

import math
from html import escape

from .market_read import MarketRead
from .risk import RiskPlan
from . import localtime as lt
import pandas as pd

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
    L = m.learned
    if L and L.get("test") and L["test"].get("trades", 0) >= 20 and not L.get("recommended"):
        return "⛔ SKIP", (f"I studied {L['candles']:,} past candles of {s.symbol}: my signals did not beat "
                          f"break-even on data I hadn't seen. Better to skip this asset on {s.interval}.")
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
    sm = m.similar
    if sm is not None and sm.matches >= 50:
        if (m.lean > 0 and sm.high < 0.5) or (m.lean < 0 and sm.low > 0.5):
            problems.append("similar past moments mostly went the other way")
        elif sm.lean == "UNCLEAR":
            problems.append("similar past moments were a coin flip")
    if L and L.get("best") and s.confluence < L["best"]["min_agree"]:
        problems.append(f"my study says wait for {L['best']['min_agree']}/4 agreement on {s.symbol}")
    if problems:
        return "🟡 CAUTION", "Possible setup, but " + ", ".join(problems) + ". Use a small stake or skip."
    return "✅ VALID SETUP", (f"{s.confluence} of 4 groups agree and similar signals were right "
                             f"{m.hit_rate:.0%} of the time. Still not guaranteed; stick to your stake size.")


def lean_dir(m) -> int:
    return m.lean or (1 if m.signal.score > 0 else -1)


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
    ]
    if s.direction != "WAIT" and m.why:
        why, risk = explain(m, 3)
        out.append(f"<b>🔮 Prediction: {'UP ⬆️' if lean_dir(m) > 0 else 'DOWN ⬇️'} because…</b>")
        out += [f"  {n}. {escape(r)}" for n, r in enumerate(why, 1)]
        out += [f"⚠️ {escape(risk)}", ""]
    out += [
        "<b>🤝 Agreement</b> <i>(4 groups of indicators; more agreeing = stronger)</i>",
    ]
    lean = m.lean
    for g, name in GROUP_NAMES.items():
        val = m.groups.get(g, 0)
        mark = "✅" if lean and val == lean else "❌" if lean and val == -lean else "➖"
        out.append(f"{mark} {name}")

    step = pd.Timedelta(minutes=MINUTES.get(s.interval, 1))
    entry = s.time + step               # the signal candle closes -> next candle opens
    exp_at = entry + step * m.expiry
    valid_to = entry + min(step, pd.Timedelta(seconds=30)) if step <= pd.Timedelta(minutes=1) else entry + step / 2
    from .sessions import session_quality
    _, sess = session_quality(s.time, crypto=s.symbol.upper().endswith(("USDT", "USDC")))
    out += ["", f"<b>🕐 Timing</b> <i>({lt.label()})</i>"]
    if s.direction != "WAIT":
        out += [f"• Enter at: <b>{lt.hhmm(entry)}</b> (start of the next candle)",
                f"• Set expiry: <b>{mins} min</b> → trade ends at <b>{lt.hhmm(exp_at)}</b>",
                f"• Too late after: {lt.local(valid_to).strftime('%I:%M:%S %p').lstrip('0')}. If you miss it, skip it."]
    else:
        out.append(f"• Last candle closed at {lt.hhmm(entry)}")
    out.append(f"• Session now: {escape(sess)}")
    L0 = m.learned
    if L0 and L0.get("best_hours"):
        out.append(f"• Best hours for {escape(s.symbol)}: {escape(L0['best_hours'])}")

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

    sm = m.similar
    if sm is not None:
        out += ["", "<b>🧠 Experience</b> <i>(the most similar moments in past data and what happened next)</i>"]
        arrow = "⬆️" if sm.up_rate > 0.5 else "⬇️"
        out.append(f"{arrow} Of the {sm.matches} closest matches in {sm.history:,} past candles, price went "
                   f"<b>UP {sm.up_rate:.0%}</b> / DOWN {1 - sm.up_rate:.0%} over the next {sm.expiry} candle(s)")
        out.append(f"Likely true range: {sm.low:.0%}-{sm.high:.0%} UP"
                   + (" → a real lean" if sm.lean != "UNCLEAR" else " → too close to 50/50 to rely on"))
    L = m.learned
    if L and L.get("best"):
        b, t = L["best"], L.get("test") or {}
        out += ["", "<b>🎓 Learned settings</b> <i>(from /study: tested on older data, checked on newer data)</i>",
                f"Best: strength ≥{b['threshold']:.0f}, {b['min_agree']}/4 agree, expiry {b['expiry']} candle(s)"]
        if t.get("trades"):
            out.append(f"On unseen data: {t['win_rate']:.0%} over {t['trades']} trades")
        out.append(escape(L["verdict"]))

    other = [w for w in s.warnings]
    if other:
        out += ["", "<b>⚠️ Watch out</b>"] + [f"• {escape(w)}" for w in other]

    out += ["", DISCLAIMER_SHORT]
    return "\n".join(out)


def scan_message(rows, interval: str, errors: dict | None = None, title: str = "Market scan") -> str:
    from .assets import KIND_NAMES, kind
    now = pd.Timestamp.now(tz="UTC")
    active = [s for s in rows if s.direction != "WAIT"]
    out = [f"📡 <b>{escape(title)}</b> · {interval} · {lt.hhmm(now)} ({lt.label()})", LINE,
           f"🟢🔴 <b>{len(active)}</b> signal(s) out of {len(rows)} assets"]
    if active:
        out += ["", "<b>🔔 Signals now</b>"]
        for s in active:
            icon, word = ("🟢", "CALL ⬆️") if s.direction.startswith("CALL") else ("🔴", "PUT ⬇️")
            out.append(f"{icon} <b>{escape(s.symbol)}</b> {word} {strength_bar(s.score, 5)} {abs(s.score):.0f} · {s.confluence}/4")
    waiting = [s for s in rows if s.direction == "WAIT"]
    by_kind: dict[str, list] = {}
    for s in waiting:
        by_kind.setdefault(kind(s.symbol), []).append(s)
    for k, items in by_kind.items():
        closed = [x.symbol for x in items if x.warnings and x.warnings[0].startswith("Market closed")]
        live = [x for x in items if x.symbol not in closed]
        out += ["", f"<b>⚪ {KIND_NAMES.get(k, k)}: waiting</b>"]
        if live:
            out.append(" · ".join(f"{escape(x.symbol)} {'⬆' if x.score > 0 else '⬇'}{abs(x.score):.0f}" for x in live))
        if closed:
            out.append("💤 Closed: " + ", ".join(escape(c) for c in closed))
    if errors:
        out += ["", "⚠️ No data: " + ", ".join(escape(e) for e in errors)]
    out += ["", "<i>Strength 0-100 · x/4 = groups agreeing · ⬆/⬇ = slight lean. "
                "Send an asset name (e.g. EURUSD or gold) for the full explanation.</i>"]
    return "\n".join(out)


def assets_message() -> str:
    from .assets import GROUPS
    names = {"majors": "💶 Forex majors", "crosses": "💱 Forex crosses", "exotics": "🌏 Exotic forex",
             "commodities": "🛢 Commodities", "indices": "📈 Indices", "stocks": "🏢 US stocks", "crypto": "🪙 Crypto"}
    out = ["📋 <b>Assets I can analyse</b>", LINE]
    for k, label in names.items():
        out += ["", f"<b>{label}</b> (<code>/scan {k}</code>)", ", ".join(GROUPS[k])]
    out += ["", "You can also type names: <code>gold</code>, <code>oil</code>, <code>apple</code>, "
                "<code>bitcoin</code>, <code>dax</code>.",
            "<code>/scan all</code> checks everything (takes about a minute).",
            "<i>OTC assets can't be analysed: their prices come from Quotex itself.</i>"]
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
    "• <code>EURUSD</code>, <code>gold</code>, <code>apple</code>, <code>BTC</code> → full market read with prediction and reasons",
    "• <code>EURUSD 5m</code> → same, on 5-minute candles",
    "• /scan → quick signal for every asset I watch",
    "• /picks → the safest trades right now (also sent automatically every 5 min)",
    "• /results → today's wins and losses of my picks",
    "• /study EURUSD → replay up to 10,000 past candles, learn the best settings, check them on unseen data",
    "• /risk 100 → stake size and daily stop for a balance of 100",
    "• /scan forex (or crypto, stocks, indices, commodities, all) → scan a group",
    "• /assets → every asset I know",
    "• /watchlist → assets I'm watching",
    "• /sessions → market session times in your time zone",
    "",
    "<b>On my own</b>",
    "🎯 Every 5 minutes I send the safest trades: asset, CALL/PUT, candle, expiry and entry time.",
    "✅ After each trade ends I tell you if it won or lost, with today's score.",
    "",
    "<b>How to read a signal</b>",
    "🟢 CALL = price expected up · 🔴 PUT = down · ⚪ WAIT = no edge",
    "📊 Strength = how strongly indicators agree (0-100)",
    "🧭 Verdict = ✅ valid / 🟡 caution / ⛔ skip",
    "📈 Track record = how often this signal was right before",
    "🧠 Experience = what happened after the most similar past moments",
    "🎓 Learned = best settings from /study, checked on data it never saw",
    "",
    DISCLAIMER_SHORT,
])


def _loc(utc_label: str) -> str:
    a, b = utc_label.split()[0].split("-")
    return lt.utc_hour_range_to_local(int(a), int(b))


def best_hours_text(r) -> str:
    good = [(h, v) for h, v in r.by_hour.items() if v[1] >= 10]
    if not good:
        return ""
    good.sort(key=lambda x: -x[1][0])
    return ", ".join(f"{_loc(h)} ({v[0]:.0%})" for h, v in good[:2]) + f" {lt.label()}"


def sessions_message() -> str:
    rows = "\n".join(f"• {n}: <b>{t}</b>" for n, t in lt.session_times_local())
    return "\n".join([f"🌍 <b>Market sessions</b> · {lt.label()}", LINE, rows, "",
                      f"✅ Best: London + New York overlap, <b>{lt.utc_hour_range_to_local(12, 16)}</b> (most volume, cleanest moves)",
                      "🟡 OK: London or New York alone", "⚠️ Weaker: Asian session and late night",
                      "⛔ Forex closed Saturday and Sunday (Quotex shows OTC only)",
                      "", "<i>Times are approximate and shift by an hour when Europe/US change clocks.</i>"])


def study_message(r) -> str:
    be = 1 / (1 + r.payout)
    out = [f"🎓 <b>Study: {escape(r.symbol)} · {r.interval}</b>", LINE,
           f"📚 Replayed <b>{r.candles_replayed:,}</b> past candles as if live",
           f"🧪 Tested <b>{r.combos_tested}</b> setting combinations (strength, agreement, expiry)"]
    if not r.best:
        return "\n".join(out + ["", escape(r.verdict)])
    b, tr, te = r.best, r.train, r.test
    icon = ("➖" if te["trades"] < 20 else "✅" if r.recommended and r.test_low > 0.5
            else "🟡" if r.recommended else "⛔")
    out += ["", "<b>🏆 Best settings (learned on older 70%)</b>",
            f"Strength ≥{b['threshold']:.0f} · {b['min_agree']}/4 agree · expiry {b['expiry']} candle(s)",
            f"Older data: {tr['win_rate']:.0%} over {tr['trades']} trades",
            "", "<b>🔍 Check on newer 30% it never saw</b>",
            f"{icon} <b>{te['win_rate']:.0%}</b> over {te['trades']} trades (need {be:.0%})" if te["trades"] else "No trades",
            f"Likely true range: {r.test_low:.0%}-{r.test_high:.0%}",
            "", f"<b>🧭 Verdict</b>", escape(r.verdict)]
    if r.by_direction:
        out += ["", "<b>📊 Details</b>"]
        out += [f"• {k}: {v[0]:.0%} of {v[1]}" for k, v in r.by_direction.items()]
        out += [f"• {k}: {v[0]:.0%} of {v[1]}" for k, v in r.by_regime.items()]
        good = [(h, v) for h, v in r.by_hour.items() if v[1] >= 10]
        if good:
            best_h = max(good, key=lambda x: x[1][0])
            worst_h = min(good, key=lambda x: x[1][0])
            out.append(f"• Best hours ({lt.label()}): {_loc(best_h[0])} ({best_h[1][0]:.0%}) · "
                       f"worst: {_loc(worst_h[0])} ({worst_h[1][0]:.0%})")
    out += ["", "<i>Past results don't guarantee future ones. The 'unseen data' line is the honest one.</i>"]
    return "\n".join(out)


# indicator label -> plain-language reason (UP version, DOWN version)
PLAIN = {
    "EMA 9 above EMA 21": "short-term trend is up (fast average above slow average)",
    "EMA 9 below EMA 21": "short-term trend is down (fast average below slow average)",
    "price above EMA 50": "price is above its 50-candle average, so buyers control the bigger move",
    "price below EMA 50": "price is below its 50-candle average, so sellers control the bigger move",
    "buyers stronger (+DI > -DI)": "buying pressure is stronger than selling pressure",
    "sellers stronger (-DI > +DI)": "selling pressure is stronger than buying pressure",
    "Supertrend up": "Supertrend has flipped to an uptrend",
    "Supertrend down": "Supertrend has flipped to a downtrend",
    "Heikin Ashi candle green": "smoothed candles are green",
    "Heikin Ashi candle red": "smoothed candles are red",
    "MACD positive": "momentum is positive",
    "MACD negative": "momentum is negative",
    "MACD rising": "momentum is getting stronger upward",
    "MACD falling": "momentum is getting stronger downward",
    "RSI oversold": "RSI says it fell too far too fast, a bounce is likely",
    "RSI overbought": "RSI says it rose too far too fast, a pullback is likely",
    "below lower Bollinger band (stretched down)": "price is stretched below its normal range and tends to snap back up",
    "above upper Bollinger band (stretched up)": "price is stretched above its normal range and tends to snap back down",
    "Stochastic turning up from oversold": "Stochastic is turning up from the bottom",
    "Stochastic turning down from overbought": "Stochastic is turning down from the top",
    "CCI below -100": "CCI shows an oversold extreme",
    "CCI above +100": "CCI shows an overbought extreme",
    "Williams %R oversold": "Williams %R is oversold",
    "Williams %R overbought": "Williams %R is overbought",
    "bullish candle pattern": "the last candles formed a bullish pattern",
    "bearish candle pattern": "the last candles formed a bearish pattern",
    "bounce off support / break above resistance": "price bounced off support or broke above resistance",
    "rejection at resistance / break below support": "price was rejected at resistance or broke below support",
    "bullish RSI divergence": "price made a lower low but RSI didn't: sellers are running out",
    "bearish RSI divergence": "price made a higher high but RSI didn't: buyers are running out",
}
# price action first, then trend, then momentum, then oscillators
PRIORITY = ["candle pattern", "support", "resistance", "divergence", "Supertrend", "EMA 50", "EMA 9", "DI", "MACD"]


def _rank(label: str) -> int:
    for i, key in enumerate(PRIORITY):
        if key in label:
            return i
    return len(PRIORITY)


def explain(m, max_reasons: int = 4) -> list[str]:
    """Plain-language reasons for the prediction, most important first,
    plus the main risk."""
    s = m.signal
    up = m.lean > 0
    lines = []
    reasons = sorted(m.why, key=_rank)
    story = {x.split(":")[0]: x for x in m.story}
    candle = story.get("Last candle")
    for r in reasons[:max_reasons]:
        text = PLAIN.get(r, r)
        if "candle pattern" in r and candle:
            text = f"the last candle shows a {candle.split(':', 1)[1].strip().rstrip('.')}"
        lines.append(text[0].upper() + text[1:] + ".")
    big = story.get("Bigger picture")
    if big and (("up" in big and up) or ("down" in big and not up)):
        lines.append("The bigger timeframe agrees, so this goes with the main trend.")
    lv = story.get("Levels")
    if lv:
        lines.append(lv.replace("Levels: ", "Levels: ").rstrip(".") + ".")
    risk = [PLAIN.get(a, a) for a in sorted(m.against, key=_rank)[:2]]
    return lines, ("Risk: " + "; ".join(risk) + ".") if risk else "Risk: nothing major against it right now."


def picks_message(picks, stats: dict, interval: str, next_check: pd.Timestamp | None = None) -> str:
    now = pd.Timestamp.now(tz="UTC")
    out = [f"🎯 <b>Safe picks</b> · {lt.hhmm(now)} ({lt.label()})", LINE]
    if not picks:
        out.append(f"😴 <b>No safe trades right now.</b>")
        out.append(f"Checked {stats.get('scanned', 0)} assets: {stats.get('signals', 0)} had a signal, "
                   f"{stats.get('rejected', 0)} failed a safety check.")
        out.append("Not trading is the safe choice when nothing passes. 🧘")
    for i, (p, m) in enumerate(picks, 1):
        icon, word = ("🟢", "CALL ⬆️ UP") if p.direction == "CALL" else ("🔴", "PUT ⬇️ DOWN")
        entry, end = pd.Timestamp(p.entry_time), pd.Timestamp(p.end_time)
        mins = MINUTES.get(p.interval, 1) * p.expiry
        hit = f"{m.hit_rate:.0%} of {m.samples}" if m.samples >= 20 else "not enough cases yet"
        out += ["",
                f"<b>{i}. {icon} {escape(p.symbol)} — {word}</b>",
                f"🛡 Safety: {strength_bar(p.safety)} <b>{p.safety:.0f}</b>/100",
                (f"🎯 Win chance: <b>{p.win_chance:.0%}</b> (likely {p.win_low:.0%}-{p.win_high:.0%}, "
                 f"from {escape(p.win_basis)})" if not math.isnan(p.win_chance)
                 else "🎯 Win chance: not enough history yet"),
                f"🕯 Candle: <b>{p.interval}</b> · ⏱ Expiry: <b>{mins} min</b>",
                f"🕐 Enter at <b>{lt.hhmm(entry)}</b> · ends <b>{lt.hhmm(end)}</b>",
                f"💰 Price now <code>{_p(p.entry_price)}</code>"
                + ("" if math.isnan(p.stop) else
                   f" · wrong if {'below' if p.direction == 'CALL' else 'above'} <code>{_p(p.stop)}</code>"),
                f"🤝 {p.confluence}/4 groups agree · 📈 track record {hit}"]
        why, risk = explain(m)
        out.append(f"🧠 <b>Why {'UP' if p.direction == 'CALL' else 'DOWN'}:</b>")
        out += [f"  {n}. {escape(r)}" for n, r in enumerate(why, 1)]
        out.append(f"⚠️ {escape(risk)}")
    if next_check is not None:
        out += ["", f"⏭ Next check at {lt.hhmm(next_check)}. I'll send the result of each pick after it ends."]
    out += ["", "<i>Send the asset name (e.g. EURUSD) for the full explanation.</i>", DISCLAIMER_SHORT]
    return "\n".join(out)


def result_message(p, tally: dict) -> str:
    if p.result == "UNKNOWN":
        return (f"❔ <b>Result: {escape(p.symbol)} {p.direction}</b>\n"
                "The price feed didn't publish the closing candle in time, so I can't tell. Check it on Quotex.")
    icon = {"WIN": "✅", "LOSS": "❌", "DRAW": "➖"}.get(p.result, "❔")
    arrow = "⬆️" if p.direction == "CALL" else "⬇️"
    done = tally["wins"] + tally["losses"]
    rate = f"{tally['wins'] / done:.0%}" if done else "-"
    return "\n".join([
        f"{icon} <b>Result: {escape(p.symbol)} {p.direction} {arrow} — {p.result}</b>",
        f"Entry <code>{_p(p.entry_price)}</code> → close <code>{_p(p.exit_price)}</code> "
        f"({MINUTES.get(p.interval, 1) * p.expiry} min, ended {lt.hhmm(pd.Timestamp(p.end_time))})",
        f"📊 Today: <b>{tally['wins']}W / {tally['losses']}L</b>" + (f" / {tally['draws']}D" if tally["draws"] else "")
        + f" · win rate {rate}",
        "<i>Results use public price feeds; Quotex's own price can differ slightly.</i>",
    ])


def results_message(tally: dict) -> str:
    done = tally["wins"] + tally["losses"]
    out = [f"📊 <b>Today's picks</b> ({lt.label()})", LINE,
           f"✅ {tally['wins']} wins · ❌ {tally['losses']} losses" + (f" · ➖ {tally['draws']} draws" if tally["draws"] else ""),
           f"Win rate: <b>{tally['wins'] / done:.0%}</b> (need 54% to break even)" if done else "No finished picks yet today."]
    rows = [r for r in tally["rows"] if isinstance(r.get("result"), str) and r["result"]]
    if rows:
        out += ["", "<b>Last picks</b>"]
        for r in rows[-10:]:
            icon = {"WIN": "✅", "LOSS": "❌", "DRAW": "➖"}.get(r["result"], "❔")
            out.append(f"{icon} {lt.hhmm(pd.Timestamp(r['entry_time']))} {escape(str(r['symbol']))} {r['direction']}")
    if done >= 10 and tally["wins"] / done < 0.54:
        out += ["", "⚠️ Below break-even today. Consider stopping for the day."]
    return "\n".join(out)
