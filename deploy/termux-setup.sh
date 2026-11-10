#!/data/data/com.termux/files/usr/bin/bash
# Quobot on an Android phone with Termux (totally free, runs 24/7 while the phone is on).
# Install Termux from F-Droid (not the old Play Store version), open it and run:
#   curl -fsSL https://raw.githubusercontent.com/amuhammadwaseem867-ctrl/quobot-/main/deploy/termux-setup.sh | bash
set -e
DIR="$HOME/quobot-"

echo "==> Installing Python and git (takes a few minutes the first time)"
pkg update -y
pkg install -y python git tur-repo || pkg install -y python git
# numpy/pandas: use Termux's prebuilt packages when available, else build with pip
pkg install -y python-numpy python-pandas 2>/dev/null || pip install numpy pandas
pip install requests tzdata

if [ -d "$DIR/.git" ]; then git -C "$DIR" pull --ff-only; else git clone --depth 1 https://github.com/amuhammadwaseem867-ctrl/quobot- "$DIR"; fi

if [ ! -f "$DIR/.env" ]; then
  read -r -p "TELEGRAM_BOT_TOKEN: " TOKEN </dev/tty
  read -r -p "TELEGRAM_CHAT_ID: " CHAT </dev/tty
  printf 'TELEGRAM_BOT_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\nTIMEZONE=Asia/Karachi\n' "$TOKEN" "$CHAT" > "$DIR/.env"
fi

cat > "$HOME/start-quobot.sh" <<'RUN'
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock 2>/dev/null || true   # keep running with the screen off
cd "$HOME/quobot-"
while true; do
  python -m today_trader bot majors XAUUSD BTCUSDT ETHUSDT -i 1m --picks-from all --picks-every 5 --top 3 --min-winrate 0.55 --fx-every 15
  echo "Bot stopped, restarting in 30 seconds..."; sleep 30
done
RUN
chmod +x "$HOME/start-quobot.sh"
echo
echo "Done. Start the bot with:   ~/start-quobot.sh"
echo "Keep the phone charging, Wi-Fi on, and the VPN app on (Telegram is blocked on some Pakistani networks)."
