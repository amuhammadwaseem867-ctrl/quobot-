@echo off
REM Double-click to start Quobot. Turn your VPN on first.
cd /d "%~dp0"
:loop
python -m today_trader bot EURUSD GBPUSD USDJPY AUDUSD EURJPY XAUUSD BTCUSDT ETHUSDT -i 1m
echo Bot stopped. Restarting in 30 seconds... (close this window to quit)
timeout /t 30 >nul
goto loop
