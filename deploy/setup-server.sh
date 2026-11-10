#!/usr/bin/env bash
# Quobot one-command setup for an Ubuntu/Debian server.
# Usage (on the server):
#   curl -fsSL https://raw.githubusercontent.com/amuhammadwaseem867-ctrl/quobot-/main/deploy/setup-server.sh | sudo bash
# Run it again any time to update the bot to the newest code.
set -euo pipefail

REPO="https://github.com/amuhammadwaseem867-ctrl/quobot-"
DIR="/opt/quobot"
SERVICE="quobot"
RUN_USER="quobot"

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run with sudo:  sudo bash setup-server.sh"; exit 1
fi

echo "==> Installing Python and git"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-venv python3-pip git tzdata >/dev/null

id -u "$RUN_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$RUN_USER"

echo "==> Getting the bot code"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only
else
  git clone --depth 1 "$REPO" "$DIR"
fi

echo "==> Installing Python packages"
python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install -q --upgrade pip
"$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"

if [ ! -f "$DIR/.env" ]; then
  echo
  echo "==> Telegram details (typed once, saved only on this server in $DIR/.env)"
  read -r -p "TELEGRAM_BOT_TOKEN: " TOKEN </dev/tty
  read -r -p "TELEGRAM_CHAT_ID: " CHAT </dev/tty
  printf 'TELEGRAM_BOT_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\nTIMEZONE=Asia/Karachi\n' "$TOKEN" "$CHAT" > "$DIR/.env"
fi
chmod 600 "$DIR/.env"
chown -R "$RUN_USER":"$RUN_USER" "$DIR"

echo "==> Installing the background service"
cp "$DIR/deploy/quobot.service" /etc/systemd/system/$SERVICE.service
systemctl daemon-reload
systemctl enable --now $SERVICE
systemctl restart $SERVICE

sleep 3
systemctl --no-pager --lines=5 status $SERVICE || true
echo
echo "Done. Quobot is running 24/7 and starts again by itself after a reboot."
echo "  Logs:      sudo journalctl -u $SERVICE -f"
echo "  Restart:   sudo systemctl restart $SERVICE"
echo "  Stop:      sudo systemctl stop $SERVICE"
echo "  Update:    run this script again"
