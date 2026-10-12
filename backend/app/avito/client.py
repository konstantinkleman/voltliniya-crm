"""Клиент Avito Messenger API (OAuth2 client_credentials).

Документация: https://developers.avito.ru/api-catalog/messenger/documentation
В категории «Услуги» Messenger API доступен на подписках «Расширенный» и «Максимальный».
"""
import logging
import threading
import time

import httpx

from ..config import settings

log = logging.getLogger("avito")
BASE = "https://api.avito.ru"


class AvitoError(RuntimeError):
    pass


class AvitoClient:
    def __init__(self):
        self._token: str | None = None
        self._token_exp: float = 0
        self._user_id: int | None = None
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(settings.AVITO_CLIENT_ID and settings.AVITO_CLIENT_SECRET)

    # ---- auth ----
    def token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._token_exp - 60:
                return self._token
            if not self.configured:
                raise AvitoError("Не заданы AVITO_CLIENT_ID / AVITO_CLIENT_SECRET")
            r = httpx.post(f"{BASE}/token", data={
                "grant_type": "client_credentials",
                "client_id": settings.AVITO_CLIENT_ID,
                "client_secret": settings.AVITO_CLIENT_SECRET,
            }, timeout=15)
            if r.status_code != 200:
                raise AvitoError(f"Авито не выдал токен: {r.status_code} {r.text[:200]}")
            data = r.json()
            self._token = data["access_token"]
            self._token_exp = time.time() + int(data.get("expires_in", 86400))
            return self._token

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self.token()}"}

    def _req(self, method: str, path: str, **kw):
        r = httpx.request(method, f"{BASE}{path}", headers=self._h(), timeout=20, **kw)
        if r.status_code == 401:  # токен протух раньше срока — обновим один раз
            self._token = None
            r = httpx.request(method, f"{BASE}{path}", headers=self._h(), timeout=20, **kw)
        if r.status_code >= 400:
            raise AvitoError(f"{method} {path} → {r.status_code} {r.text[:300]}")
        return r.json() if r.content else {}

    # ---- аккаунт ----
    def user_id(self) -> int:
        if self._user_id is None:
            me = self._req("GET", "/core/v1/accounts/self")
            self._user_id = int(me["id"])
        return self._user_id

    # ---- чаты ----
    def chat_info(self, chat_id: str) -> dict:
        return self._req("GET", f"/messenger/v2/accounts/{self.user_id()}/chats/{chat_id}")

    def chats(self, unread_only: bool = False, limit: int = 100, offset: int = 0) -> list[dict]:
        data = self._req("GET", f"/messenger/v2/accounts/{self.user_id()}/chats",
                         params={"unread_only": str(unread_only).lower(), "limit": limit, "offset": offset, "chat_types": "u2i,u2u"})
        return data.get("chats", [])

    def messages(self, chat_id: str, limit: int = 100) -> list[dict]:
        data = self._req("GET", f"/messenger/v3/accounts/{self.user_id()}/chats/{chat_id}/messages/", params={"limit": limit})
        return data if isinstance(data, list) else data.get("messages", [])

    def send_text(self, chat_id: str, text: str) -> dict:
        return self._req("POST", f"/messenger/v1/accounts/{self.user_id()}/chats/{chat_id}/messages",
                         json={"message": {"text": text}, "type": "text"})

    def mark_read(self, chat_id: str) -> None:
        try:
            self._req("POST", f"/messenger/v1/accounts/{self.user_id()}/chats/{chat_id}/read")
        except AvitoError as e:  # не критично
            log.warning("mark_read: %s", e)

    # ---- вебхуки ----
    def subscribe(self, url: str) -> dict:
        return self._req("POST", "/messenger/v3/webhook", json={"url": url})

    def unsubscribe(self, url: str) -> dict:
        return self._req("POST", "/messenger/v1/webhook/unsubscribe", json={"url": url})

    def subscriptions(self) -> list[dict]:
        return self._req("POST", "/messenger/v1/subscriptions").get("subscriptions", [])


client = AvitoClient()


def webhook_url() -> str:
    return f"{settings.PUBLIC_URL.rstrip('/')}/api/avito/webhook/{settings.AVITO_WEBHOOK_SECRET}"


def parse_webhook(body: dict) -> dict | None:
    """Приводит тело вебхука v3 к плоскому виду. Возвращает None, если это не сообщение."""
    payload = body.get("payload") or {}
    if payload.get("type") not in (None, "message"):
        return None
    v = payload.get("value") or body.get("value") or {}
    if not v.get("chat_id"):
        return None
    content = v.get("content") or {}
    text = content.get("text") or ""
    mtype = v.get("type") or ("text" if text else "other")
    if mtype == "image":
        text = "[изображение]"
    elif mtype == "voice":
        text = "[голосовое сообщение]"
    elif mtype == "link":
        text = content.get("link", {}).get("text") or content.get("link", {}).get("url") or "[ссылка]"
    elif mtype == "item":
        text = "[объявление]"
    elif mtype == "location":
        text = "[геопозиция]"
    elif mtype == "system":
        text = content.get("text") or "[системное сообщение]"
    elif not text:
        text = f"[{mtype}]"
    return {
        "message_id": str(v.get("id") or ""),
        "chat_id": str(v["chat_id"]),
        "account_user_id": v.get("user_id"),
        "author_id": v.get("author_id"),
        "item_id": v.get("item_id"),
        "type": mtype,
        "text": text,
        "created": v.get("created"),
        "flow_id": v.get("flow_id"),
    }
