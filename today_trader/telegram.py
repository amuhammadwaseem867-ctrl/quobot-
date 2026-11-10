"""Telegram alerts. Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from the
environment or from a .env file in the folder you run the bot from."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

API = "https://api.telegram.org/bot{token}/{method}"

UNREACHABLE_HINT = (
    "Your internet connection can't reach api.telegram.org. Some networks block it.\n"
    "Turn on a VPN and try again, or set HTTPS_PROXY to a working proxy.\n"
    "Tip: you can get your chat id without the API by messaging @userinfobot in Telegram."
)


def load_env(path: str | Path = ".env") -> None:
    """Minimal .env loader: KEY=value lines; real environment variables win."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def credentials() -> tuple[str | None, str | None]:
    return os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")


def _call(method: str, token: str, http_timeout: float = 30, **data) -> dict:
    try:
        r = requests.post(API.format(token=token, method=method), data=data, timeout=http_timeout)
    except requests.RequestException as e:
        # don't print the exception text: it can contain the URL, which holds the token
        raise RuntimeError(f"could not reach Telegram ({type(e).__name__})") from None
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not body.get("ok"):
        raise RuntimeError(f"Telegram said: {body.get('description', f'HTTP {r.status_code}')}")
    return body["result"]


def send(text: str) -> bool:
    token, chat = credentials()
    if not (token and chat):
        return False
    try:
        _call("sendMessage", token, chat_id=chat, text=text)
        return True
    except RuntimeError as e:
        print(f"Telegram send failed: {e}", file=sys.stderr)
        if "could not reach" in str(e):
            print(UNREACHABLE_HINT, file=sys.stderr)
        return False


def find_chat_ids(token: str) -> list[tuple[str, str]]:
    """Chats that have messaged the bot recently: [(chat_id, name)]."""
    seen = {}
    for upd in _call("getUpdates", token):
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if "id" in chat:
            name = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
            seen[str(chat["id"])] = name or chat.get("username", "")
    return list(seen.items())


def get_updates(token: str, offset: int | None, wait: int) -> list[dict]:
    """Long-poll for new messages, waiting up to `wait` seconds."""
    data = {"timeout": max(0, int(wait))}
    if offset is not None:
        data["offset"] = offset
    return _call("getUpdates", token, http_timeout=wait + 15, **data)


def send_to(chat_id: str, text: str) -> None:
    token, _ = credentials()
    for i in range(0, len(text), 4000):  # Telegram limit is 4096 chars
        _call("sendMessage", token, chat_id=chat_id, text=text[i:i + 4000])
