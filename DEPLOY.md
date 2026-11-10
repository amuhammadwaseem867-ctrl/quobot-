# Quobot ko 24/7 cloud server par chalana

PC band ho tab bhi bot chalta rahe, is ke liye usay ek **cloud server (VPS)** par chalayein.
Server Pakistan se bahar hota hai, is liye wahan **VPN ki zaroorat nahi**. Telegram seedha chalta hai.

## 1. Server lein (ek option chunein)

| Option | Qeemat | Note |
|---|---|---|
| **Oracle Cloud "Always Free"** | Muft | Card se verification hoti hai (charge nahi hota). Signup kabhi kabhi mushkil hota hai. |
| **Hetzner CX22** | ~€4 / mahina | Sasta aur reliable. |
| **DigitalOcean / Vultr** | ~$5-6 / mahina | Asaan dashboard. |

Server banate waqt ye chunein:
- **Ubuntu 24.04** (ya 22.04)
- Sab se chhota plan (1 CPU, 1 GB RAM kaafi hai)
- Login ke liye **password** ya SSH key

Server ban jaye to uska **IP address** (jaise `65.21.10.20`) note kar lein.

> Render, Railway jaise "free hosting" background bots ko kuch der baad sula dete hain. Is bot ke liye VPS behtar hai.

## 2. Server se connect karein

Apne PC par **PowerShell** kholein aur likhein (IP apna lagayein):

```
ssh root@65.21.10.20
```

Oracle par user `ubuntu` hota hai: `ssh ubuntu@IP`. Pehli baar "yes" likhein, phir password dein.

## 3. Ek command se bot install karein

Server par ye command chalayein:

```
curl -fsSL https://raw.githubusercontent.com/amuhammadwaseem867-ctrl/quobot-/main/deploy/setup-server.sh | sudo bash
```

Ye aap se do cheezein poochega:
- `TELEGRAM_BOT_TOKEN`: BotFather wala token
- `TELEGRAM_CHAT_ID`: aapka chat id (jo `.env` mein hai)

Ye sirf server par save hote hain. Bas! Telegram mein "🤖 Quobot is online" aa jayega.

## 4. Zaroori: PC wala bot band karein

Ek hi token par **do bot ek saath nahi chal sakte**. Server wala chalne ke baad PC par
start-bot.bat ki window band kar dein.

## Rozana kaam

Server par (ssh se connect ho kar):

| Kaam | Command |
|---|---|
| Bot kya kar raha hai dekhein | `sudo journalctl -u quobot -f` (band karne ke liye Ctrl+C) |
| Restart | `sudo systemctl restart quobot` |
| Band | `sudo systemctl stop quobot` |
| Naya update | upar wali **curl** command dobara chalayein |
| Assets / strict mode badlein | `sudo nano /etc/systemd/system/quobot.service`, `ExecStart` line badlein, phir `sudo systemctl daemon-reload && sudo systemctl restart quobot` |

Server restart ho jaye to bot khud dobara start ho jata hai.

## Docker (agar aap Docker use karte hain)

```
git clone https://github.com/amuhammadwaseem867-ctrl/quobot-
cd quobot-
docker build -t quobot .
docker run -d --name quobot --restart always -v quobot-data:/data \
  -e TELEGRAM_BOT_TOKEN=xxx -e TELEGRAM_CHAT_ID=yyy quobot
docker logs -f quobot
```
