"""HTTP: вебхук Авито, управление подпиской, скрипт бота, разбор переписок."""
import hmac
import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from ..auth import director
from ..config import settings
from ..db import SessionLocal, get_db
from . import review as review_mod
from . import service
from .client import AvitoError, client, parse_webhook, webhook_url

log = logging.getLogger("avito.router")
router = APIRouter(prefix="/api/avito", tags=["avito"])


# ---------- вебхук (без авторизации, защищён секретом в адресе) ----------

def _process(ev: dict):
    with SessionLocal() as db:
        try:
            service.handle_incoming(db, ev)
        except Exception as e:  # noqa: BLE001
            log.exception("handle_incoming: %s", e)


@router.post("/webhook/{secret}")
async def webhook(secret: str, request: Request, bg: BackgroundTasks):
    if not settings.AVITO_WEBHOOK_SECRET or not hmac.compare_digest(secret, settings.AVITO_WEBHOOK_SECRET):
        raise HTTPException(404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    ev = parse_webhook(body) if isinstance(body, dict) else None
    if ev:
        bg.add_task(_process, ev)  # Авито ждёт 200 не дольше 2 с — вся работа в фоне
    return {"ok": True}


# ---------- статус и подписка ----------

class StatusOut(BaseModel):
    configured: bool
    bot_enabled: bool
    telegram: bool
    anthropic: bool
    webhook_url: str
    subscribed: bool | None = None
    account_id: int | None = None
    error: str | None = None
    chats: int = 0
    active_script_version: int | None = None


@router.get("/status", response_model=StatusOut)
def status(_: m.User = Depends(director), db: Session = Depends(get_db)):
    out = StatusOut(configured=client.configured, bot_enabled=settings.AVITO_BOT_ENABLED,
                    telegram=bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID),
                    anthropic=bool(settings.ANTHROPIC_API_KEY), webhook_url=webhook_url(),
                    chats=db.scalar(select(func.count(m.AvitoChat.id))) or 0)
    s = db.scalar(select(m.SalesScript).where(m.SalesScript.is_active == True))  # noqa: E712
    out.active_script_version = s.version if s else None
    if client.configured:
        try:
            out.account_id = client.user_id()
            subs = client.subscriptions()
            out.subscribed = any((x.get("url") == webhook_url()) for x in subs)
        except AvitoError as e:
            out.error = str(e)
    return out


@router.post("/subscribe")
def subscribe(_: m.User = Depends(director)):
    if not settings.AVITO_WEBHOOK_SECRET:
        raise HTTPException(400, "Задайте AVITO_WEBHOOK_SECRET в .env")
    try:
        client.subscribe(webhook_url())
    except AvitoError as e:
        raise HTTPException(502, str(e))
    return {"ok": True, "url": webhook_url()}


@router.post("/unsubscribe")
def unsubscribe(_: m.User = Depends(director)):
    try:
        client.unsubscribe(webhook_url())
    except AvitoError as e:
        raise HTTPException(502, str(e))
    return {"ok": True}


@router.post("/test-telegram")
def test_telegram(_: m.User = Depends(director)):
    from .notify import telegram
    ok = telegram("✅ ВольтЛиния CRM: уведомления об Авито подключены.")
    if not ok:
        raise HTTPException(400, "Telegram не настроен или не отвечает (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
    return {"ok": True}


# ---------- чаты ----------

class ChatOut(BaseModel):
    id: int
    chat_id: str
    lead_id: int | None
    client_name: str | None
    item_title: str | None
    mode: str
    qualified: str
    handoff_reason: str | None
    last_message_at: datetime | None
    messages: int


@router.get("/chats", response_model=list[ChatOut])
def chats(_: m.User = Depends(director), db: Session = Depends(get_db)):
    rows = db.scalars(select(m.AvitoChat).order_by(m.AvitoChat.last_message_at.desc().nullslast())).all()
    return [ChatOut(id=c.id, chat_id=c.chat_id, lead_id=c.lead_id, client_name=c.client_name, item_title=c.item_title,
                    mode=c.mode, qualified=c.qualified, handoff_reason=c.handoff_reason,
                    last_message_at=c.last_message_at, messages=len(c.messages)) for c in rows]


class ChatMode(BaseModel):
    mode: str  # bot / manual


@router.post("/chats/{cid}/mode")
def set_mode(cid: int, data: ChatMode, _: m.User = Depends(director), db: Session = Depends(get_db)):
    chat = db.get(m.AvitoChat, cid)
    if not chat:
        raise HTTPException(404)
    if data.mode not in ("bot", "manual"):
        raise HTTPException(400, "mode: bot или manual")
    chat.mode = data.mode
    chat.manual_until = None
    db.commit()
    return {"ok": True}


class SendIn(BaseModel):
    text: str


@router.post("/chats/{cid}/send")
def send(cid: int, data: SendIn, user: m.User = Depends(director), db: Session = Depends(get_db)):
    """Ответить клиенту из CRM от своего имени; бот в этом чате замолкает на AVITO_MANUAL_HOLD_HOURS."""
    chat = db.get(m.AvitoChat, cid)
    if not chat:
        raise HTTPException(404)
    try:
        sent = client.send_text(chat.chat_id, data.text)
    except AvitoError as e:
        raise HTTPException(502, str(e))
    from datetime import timedelta
    db.add(m.AvitoMessage(chat_pk=chat.id, message_id=str(sent.get("id")) if sent.get("id") else None,
                          direction="out", author="director", msg_type="text", text=data.text))
    chat.mode = "manual"
    chat.manual_until = datetime.utcnow() + timedelta(hours=settings.AVITO_MANUAL_HOLD_HOURS)
    chat.last_message_at = datetime.utcnow()
    if chat.lead:
        db.add(m.LeadActivity(lead_id=chat.lead.id, kind="message", text=f"Вы (Авито): {data.text}", user_id=user.id))
    db.commit()
    return {"ok": True}


# ---------- скрипт ----------

class ScriptOut(BaseModel):
    id: int
    version: int
    text: str
    note: str | None
    is_active: bool
    created_by: str
    created_at: datetime


class ScriptIn(BaseModel):
    text: str
    note: str | None = None
    activate: bool = True


@router.get("/script", response_model=list[ScriptOut])
def scripts(_: m.User = Depends(director), db: Session = Depends(get_db)):
    service.active_script(db)
    return db.scalars(select(m.SalesScript).order_by(m.SalesScript.version.desc())).all()


@router.post("/script", response_model=ScriptOut)
def create_script(data: ScriptIn, _: m.User = Depends(director), db: Session = Depends(get_db)):
    if len(data.text.strip()) < 200:
        raise HTTPException(400, "Скрипт слишком короткий")
    return service.new_script_version(db, data.text, data.note, "director", data.activate)


@router.post("/script/{sid}/activate", response_model=ScriptOut)
def activate(sid: int, _: m.User = Depends(director), db: Session = Depends(get_db)):
    s = db.get(m.SalesScript, sid)
    if not s:
        raise HTTPException(404)
    service.activate_script(db, s)
    db.commit()
    db.refresh(s)
    return s


@router.get("/script/{sid}/apply/{token}", response_class=HTMLResponse)
def apply_from_link(sid: int, token: str, db: Session = Depends(get_db)):
    """Ссылка из Telegram: включает черновик, подготовленный еженедельным разбором."""
    s = db.get(m.SalesScript, sid)
    if not s or not hmac.compare_digest(token, review_mod.apply_token(sid)):
        raise HTTPException(404)
    if not s.is_active:
        service.activate_script(db, s)
        db.commit()
    return HTMLResponse(f"<html><body style='font-family:sans-serif;padding:40px'><h2>Скрипт версии {s.version} включён</h2>"
                        f"<p>Бот-продажник ВольтЛинии теперь отвечает по новой версии. Это окно можно закрыть.</p></body></html>")


# ---------- разбор ----------

class ReviewOut(BaseModel):
    id: int
    period_from: datetime | None = None
    period_to: datetime | None = None
    report: str
    draft_script_id: int | None
    created_at: datetime


@router.get("/reviews")
def reviews(_: m.User = Depends(director), db: Session = Depends(get_db)):
    rows = db.scalars(select(m.AvitoReview).order_by(m.AvitoReview.id.desc()).limit(20)).all()
    return [{"id": r.id, "period_from": str(r.period_from), "period_to": str(r.period_to), "report": r.report,
             "draft_script_id": r.draft_script_id, "created_at": r.created_at} for r in rows]


@router.post("/review")
def run_review_now(days: int = 7, _: m.User = Depends(director), db: Session = Depends(get_db)):
    r = review_mod.run_review(db, days=days)
    return {"ok": True, "review_id": r.id if r else None}
