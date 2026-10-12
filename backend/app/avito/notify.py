"""Уведомления директору в Telegram."""
import logging

import httpx

from ..config import settings

log = logging.getLogger("avito.notify")


def telegram(text: str, disable_preview: bool = True) -> bool:
    if not (settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID):
        log.info("telegram не настроен, сообщение: %s", text[:120])
        return False
    try:
        r = httpx.post(f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
                       json={"chat_id": settings.TELEGRAM_CHAT_ID, "text": text[:4000], "parse_mode": "HTML",
                             "disable_web_page_preview": disable_preview}, timeout=10)
        if r.status_code != 200:
            log.warning("telegram %s %s", r.status_code, r.text[:200])
        return r.status_code == 200
    except httpx.HTTPError as e:
        log.warning("telegram: %s", e)
        return False


def esc(s: str | None) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
