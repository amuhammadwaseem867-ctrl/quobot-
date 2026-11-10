import numpy as np
import pandas as pd

from today_trader import data, indicators
from today_trader.backtest import backtest
from today_trader.signals import analyze, direction_for


def test_rsi_bounds_and_extremes():
    up = pd.Series(np.linspace(1, 2, 100))
    assert indicators.rsi(up).iloc[-1] > 95
    down = pd.Series(np.linspace(2, 1, 100))
    assert indicators.rsi(down).iloc[-1] < 5


def test_strong_uptrend_gives_call():
    n = 200
    close = np.linspace(1.0, 1.2, n) + np.sin(np.arange(n)) * 0.001
    df = pd.DataFrame({"open": close - 0.0005, "high": close + 0.001, "low": close - 0.001,
                       "close": close, "volume": 1.0},
                      index=pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC"))
    s = analyze(df, "TEST", "5m")
    assert s.score > 0


def test_direction_thresholds():
    assert direction_for(50).startswith("CALL")
    assert direction_for(-50).startswith("PUT")
    assert direction_for(10) == "WAIT"


def test_score_range_and_backtest_on_demo():
    df = data.demo_candles(n=600, seed=1)
    s = analyze(df, "DEMO", "5m")
    assert -100 <= s.score <= 100
    r = backtest(df, "DEMO")
    assert 0 <= r.wins <= r.signals


def test_yahoo_ticker_mapping():
    assert data.yahoo_ticker("EURUSD") == "EURUSD=X"
    assert data.yahoo_ticker("XAUUSD") == "GC=F"
    assert data.is_crypto("BTCUSDT")


def test_load_env(tmp_path, monkeypatch):
    from today_trader import telegram
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    f = tmp_path / ".env"
    f.write_text('# comment\nexport TELEGRAM_CHAT_ID="12345"\n')
    telegram.load_env(f)
    assert telegram.credentials()[1] == "12345"


def test_no_lookahead_bias():
    """Scores for past candles must not change when newer candles arrive."""
    from today_trader.signals import score_frame
    df = data.demo_candles(n=500, seed=3)
    full = score_frame(df)
    for cut in (250, 333, 420):
        part = score_frame(df.iloc[:cut])
        assert np.allclose(full["score"].iloc[cut - 30:cut].values, part["score"].iloc[-30:].values)


def test_random_walk_is_near_coin_flip():
    """On pure noise the bot must not 'find' an edge (would mean a bug)."""
    rng = np.random.default_rng(0)
    n = 3000
    close = 1.1 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    o = np.r_[close[0], close[:-1]]
    sp = np.abs(rng.normal(0, 0.0006, n)) * close
    df = pd.DataFrame({"open": o, "high": np.maximum(o, close) + sp, "low": np.minimum(o, close) - sp,
                       "close": close, "volume": 1.0},
                      index=pd.date_range("2026-11-02 08:00", periods=n, freq="1min", tz="UTC"))
    r = backtest(df, "RW", use_filters=False)
    assert 0.44 < r.win_rate < 0.56


def test_bullish_engulfing_detected():
    from today_trader import candles
    df = pd.DataFrame({"open": [1.10, 1.09, 1.085], "high": [1.101, 1.091, 1.10],
                       "low": [1.089, 1.084, 1.084], "close": [1.09, 1.086, 1.095]})
    assert candles.engulfing(df).iloc[-1] == 1


def test_weekend_forex_is_blocked():
    from today_trader.sessions import session_quality
    assert session_quality(pd.Timestamp("2026-11-14 12:00", tz="UTC"))[0] == 0
    assert session_quality(pd.Timestamp("2026-11-14 12:00", tz="UTC"), crypto=True)[0] == 1


def test_risk_plan():
    from today_trader.risk import RiskPlan
    p = RiskPlan(200, risk_pct=1)
    assert p.stake == 2 and p.martingale_cost(5) == 62


def test_market_read_runs_and_explains():
    from today_trader.market_read import format_read, read_market
    df = data.demo_candles(n=800, seed=11)
    m = read_market(df, "EURUSD", "5m")
    text = format_read(m)
    assert "Prediction:" in text and "What the market is doing" in text
    assert m.prediction.split()[0] in ("UP", "DOWN", "NO")


def test_bot_replies():
    from html.parser import HTMLParser

    from today_trader.bot import QuobotChat
    from today_trader.tg_format import HELP_MESSAGE

    class TagCheck(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []

        def handle_starttag(self, tag, attrs):
            assert tag in ("b", "i", "code"), tag
            self.stack.append(tag)

        def handle_endtag(self, tag):
            assert self.stack.pop() == tag

    bot = QuobotChat(["EURUSD", "BTCUSDT"], "5m", demo=True)
    replies = [bot.reply(x) for x in ("/help", "eurusd", "EURUSD 1m", "/scan", "/risk 100", "/risk abc", "/watchlist")]
    assert replies[0] == HELP_MESSAGE
    assert "Verdict" in replies[1] and "What the market is doing" in replies[1]
    assert "EURUSD" in replies[3]
    assert "Stake per trade" in replies[4]
    assert "like this" in replies[5]
    for r in replies:
        p = TagCheck()
        p.feed(r)
        assert not p.stack and len(r) < 4096


def test_study_finds_no_edge_in_noise_and_saves(tmp_path):
    from today_trader.study import load_study, save_study, similar_setups, study
    rng = np.random.default_rng(1)
    n = 6000
    close = 1.1 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    o = np.r_[close[0], close[:-1]]
    sp = np.abs(rng.normal(0, 0.0006, n)) * close
    df = pd.DataFrame({"open": o, "high": np.maximum(o, close) + sp, "low": np.minimum(o, close) - sp,
                       "close": close, "volume": 1.0},
                      index=pd.date_range("2026-10-05", periods=n, freq="1min", tz="UTC"))
    r = study(df, "RW", "1m")
    assert r.test is None or r.test["trades"] < 20 or r.test_low < 0.5  # no fake edge on unseen noise
    sim = similar_setups(df)
    assert sim.matches > 0 and sim.low < 0.5 < sim.high
    f = tmp_path / "s.json"
    save_study(r, f)
    assert load_study("RW", "1m", f) is not None


def test_local_time_is_pakistan_by_default(monkeypatch):
    from today_trader import localtime
    monkeypatch.delenv("TIMEZONE", raising=False)
    assert localtime.hhmm(pd.Timestamp("2026-11-10 16:00", tz="UTC")) == "9:00 PM"


def test_assets_catalog():
    from today_trader import assets
    assert assets.normalize("gold") == "XAUUSD"
    assert assets.normalize("EUR/USD OTC") == "EURUSD"
    assert assets.normalize("bitcoin") == "BTCUSDT"
    allx = assets.expand(["all"])
    assert len(allx) == len(set(allx)) > 80
    assert assets.expand(["forex", "gold", "EURUSD"])[-1] == "XAUUSD"
    assert data.yahoo_ticker("GER40") == "^GDAXI" and data.is_crypto("TONUSDT")


def test_picks_flow(tmp_path, monkeypatch):
    from today_trader import picks
    from today_trader.tg_format import picks_message, result_message, results_message
    monkeypatch.chdir(tmp_path)
    found, stats = picks.find_picks(["EURUSD", "GBPUSD", "XAUUSD"], "5m", 3, demo=True)
    assert stats["scanned"] == 3
    assert "Safe picks" in picks_message(found, stats, "5m")
    p = picks.Pick("EURUSD", "CALL", "5m", 1, "2026-11-10T15:05:00+00:00", "2026-11-10T15:10:00+00:00",
                   1.0, float("nan"), 50, 50, 3, "x")
    p.result, p.exit_price = "WIN", 1.1
    picks.log_pick(p, tmp_path / "log.csv")
    assert "WIN" in result_message(p, {"wins": 1, "losses": 0, "draws": 0})
    assert "Today" in results_message(picks.today_results(tmp_path / "log.csv"))


def test_forex_plan_math():
    from today_trader import forex
    assert forex.broker_symbol("EURUSD", "micro") == "EURUSDmicro"
    assert forex.broker_symbol("XAUUSD", "standard") == "GOLD"
    assert forex.pip_size("USDJPY") == 0.01
    for sym in forex.FX_DEFAULT:
        p = forex.plan_trade(sym, "15m", balance=50, risk_pct=1, account="micro", demo=True, history=1500)
        assert p.action in ("BUY", "SELL", "WAIT")
        if p.action == "WAIT":
            continue
        side = 1 if p.action == "BUY" else -1
        assert side * (p.target - p.entry) > 0 and side * (p.entry - p.stop) > 0
        assert abs(abs(p.target - p.entry) - 2 * abs(p.entry - p.stop)) < 1e-9
        assert p.lots >= 0.01 and abs(round(p.lots * 100) - p.lots * 100) < 1e-6
        assert abs(p.reward_usd - 2 * p.risk_usd) < 1e-9


def test_forex_no_edge_on_random_walk():
    import numpy as np
    import pandas as pd
    from today_trader.forex import tp_before_sl
    rng = np.random.default_rng(1)
    n = 6000
    c = 1.1 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    o = np.r_[c[0], c[:-1]]
    sp = np.abs(rng.normal(0, 0.0006, n)) * c
    df = pd.DataFrame({"open": o, "high": np.maximum(o, c) + sp, "low": np.minimum(o, c) - sp, "close": c,
                       "volume": 1.0}, index=pd.date_range("2026-01-05", periods=n, freq="15min", tz="UTC"))
    rate, n_trades = tp_before_sl(df, 40, 2, 1.5, 0.00017)
    assert n_trades > 30 and rate < 0.45   # 1:2 on noise should win about a third
