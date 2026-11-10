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


def send(text: str, html: bool = False) -> bool:
    token, chat = credentials()
    if not (token and chat):
        return False
    try:
        extra = {"parse_mode": "HTML", "disable_web_page_preview": "true"} if html else {}
        try:
            _call("sendMessage", token, chat_id=chat, text=text, **extra)
        except RuntimeError as e:
            if not html or "parse" not in str(e).lower():
                raise
            _call("sendMessage", token, chat_id=chat, text=_strip_tags(text))  # formatting failed: send plain
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


def _strip_tags(text: str) -> str:
    import html as _html
    import re
    return _html.unescape(re.sub(r"</?(b|i|code)>", "", text))


def send_to(chat_id: str, text: str, html: bool = False) -> None:
    token, _ = credentials()
    extra = {"parse_mode": "HTML", "disable_web_page_preview": "true"} if html else {}
    # split on blank lines so HTML tags are never cut in half (limit is 4096 chars)
    chunks, cur = [], ""
    for block in text.split("\n\n"):
        if cur and len(cur) + len(block) + 2 > 4000:
            chunks.append(cur)
            cur = block
        else:
            cur = f"{cur}\n\n{block}" if cur else block
    chunks.append(cur)
    for c in chunks:
        try:
            _call("sendMessage", token, chat_id=chat_id, text=c, **extra)
        except RuntimeError as e:
            if not html or "parse" not in str(e).lower():
                raise
            _call("sendMessage", token, chat_id=chat_id, text=_strip_tags(c))
