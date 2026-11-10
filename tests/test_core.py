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
