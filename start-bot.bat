@echo off
REM Double-click to start Quobot. Turn your VPN on first.
REM Every 5 minutes it sends the safest trades from all assets, then each result.
cd /d "%~dp0"
:loop
python -m today_trader bot majors XAUUSD BTCUSDT ETHUSDT -i 1m --picks-from all --picks-every 5 --top 3 --min-winrate 0.55 --fx-every 15
echo Bot stopped. Restarting in 30 seconds... (close this window to quit)
timeout /t 30 >nul
goto loop
