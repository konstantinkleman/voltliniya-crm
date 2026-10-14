"""Уведомления директору в Telegram (тот же бот, что и заявки с сайта)."""
import logging

import httpx

from ..config import settings

log = logging.getLogger("avito.notify")


def _api(method: str, payload: dict) -> dict | None:
    if not (settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID):
        log.info("telegram не настроен: %s %s", method, str(payload.get("text", ""))[:120])
        return None
    try:
        r = httpx.post(f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{method}",
                       json={"chat_id": settings.TELEGRAM_CHAT_ID, **payload}, timeout=10)
        if r.status_code != 200:
            # 400 «message is not modified» при правке тем же текстом — не ошибка
            if "not modified" not in r.text:
                log.warning("telegram %s %s %s", method, r.status_code, r.text[:200])
            return None
        return r.json().get("result") or {}
    except httpx.HTTPError as e:
        log.warning("telegram %s: %s", method, e)
        return None


def tg_send(text: str, silent: bool = False) -> int | None:
    """Отправить сообщение; возвращает message_id (нужен, чтобы потом дописать в него ответ бота)."""
    res = _api("sendMessage", {"text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True,
                               "disable_notification": silent})
    if res is None:
        return None
    return res.get("message_id") or 0


def tg_edit(message_id: int, text: str) -> bool:
    return _api("editMessageText", {"message_id": message_id, "text": text[:4000], "parse_mode": "HTML",
                                    "disable_web_page_preview": True}) is not None


def telegram(text: str, disable_preview: bool = True) -> bool:
    return tg_send(text) is not None


def esc(s: str | None) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
