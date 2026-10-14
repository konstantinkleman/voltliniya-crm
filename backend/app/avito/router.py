"""HTTP: вебхук Авито, управление подпиской, скрипт бота, разбор переписок."""
import hmac
import logging
from datetime import datetime, timedelta

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
from . import service, timing
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
    hours: str = ""
    queue: int = 0
    failed_7d: int = 0


@router.get("/status", response_model=StatusOut)
def status(_: m.User = Depends(director), db: Session = Depends(get_db)):
    out = StatusOut(configured=client.configured, bot_enabled=settings.AVITO_BOT_ENABLED,
                    telegram=bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID),
                    anthropic=bool(settings.ANTHROPIC_API_KEY), webhook_url=webhook_url(),
                    chats=db.scalar(select(func.count(m.AvitoChat.id))) or 0)
    s = db.scalar(select(m.SalesScript).where(m.SalesScript.is_active == True))  # noqa: E712
    out.active_script_version = s.version if s else None
    out.hours = f"{settings.AVITO_HOURS_START}:00–{settings.AVITO_HOURS_END}:00 МСК"
    out.queue = db.scalar(select(func.count(m.AvitoTask.id)).where(m.AvitoTask.status == "pending")) or 0
    week_ago = timing.utcnow() - timedelta(days=7)
    out.failed_7d = db.scalar(select(func.count(m.AvitoTask.id)).where(m.AvitoTask.status == "failed",
                                                                     m.AvitoTask.created_at >= week_ago)) or 0
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
    manual_until: datetime | None = None
    qualified: str
    handoff_reason: str | None
    last_message_at: datetime | None
    messages: int
    followup_stage: int = 0
    next_action: str | None = None       # что бот сделает дальше
    next_action_at: datetime | None = None


def _chat_out(db: Session, c: m.AvitoChat) -> ChatOut:
    nxt = service.pending_tasks(db, c)
    t = nxt[0] if nxt else None
    return ChatOut(id=c.id, chat_id=c.chat_id, lead_id=c.lead_id, client_name=c.client_name, item_title=c.item_title,
                   mode=c.mode, manual_until=c.manual_until, qualified=c.qualified, handoff_reason=c.handoff_reason,
                   last_message_at=c.last_message_at, messages=len(c.messages), followup_stage=c.followup_stage or 0,
                   next_action=m.AVITO_TASK_KINDS.get(t.kind) if t else None, next_action_at=t.due_at if t else None)


@router.get("/chats", response_model=list[ChatOut])
def chats(_: m.User = Depends(director), db: Session = Depends(get_db)):
    rows = db.scalars(select(m.AvitoChat).order_by(m.AvitoChat.last_message_at.desc().nullslast()).limit(100)).all()
    return [_chat_out(db, c) for c in rows]


class MessageOut(BaseModel):
    direction: str
    author: str
    text: str
    created_at: datetime | None


class LeadChatOut(BaseModel):
    chat: ChatOut
    messages: list[MessageOut]


@router.get("/leads/{lead_id}/chat", response_model=LeadChatOut | None)
def lead_chat(lead_id: int, _: m.User = Depends(director), db: Session = Depends(get_db)):
    """Чат Авито в карточке заявки: переписка и кнопка «Ответить»."""
    c = db.scalar(select(m.AvitoChat).where(m.AvitoChat.lead_id == lead_id))
    if not c:
        return None
    msgs = [MessageOut(direction=x.direction, author=x.author, text=x.text, created_at=x.created_at)
            for x in c.messages if x.author != "system"][-50:]
    return LeadChatOut(chat=_chat_out(db, c), messages=msgs)


class ChatMode(BaseModel):
    mode: str  # bot / manual


@router.post("/chats/{cid}/mode")
def set_mode(cid: int, data: ChatMode, _: m.User = Depends(director), db: Session = Depends(get_db)):
    chat = db.get(m.AvitoChat, cid)
    if not chat:
        raise HTTPException(404)
    if data.mode not in ("bot", "manual"):
        raise HTTPException(400, "mode: bot или manual")
    now = timing.utcnow()
    planned = None
    if data.mode == "manual":
        chat.mode, chat.manual_until = "manual", None  # вручную — бессрочно, пока не вернёте боту
        service.cancel_tasks(db, chat)
    else:
        planned = service.return_to_bot(db, chat, now)
    db.commit()
    return {"ok": True, "reply_planned_at": planned}


class SendIn(BaseModel):
    text: str


@router.post("/chats/{cid}/send")
def send(cid: int, data: SendIn, user: m.User = Depends(director), db: Session = Depends(get_db)):
    """Ответить клиенту из CRM от своего имени; бот в этом чате замолкает на AVITO_MANUAL_HOLD_HOURS."""
    chat = db.get(m.AvitoChat, cid)
    if not chat:
        raise HTTPException(404)
    text = data.text.strip()
    if not text:
        raise HTTPException(400, "Пустое сообщение")
    msg = m.AvitoMessage(chat_pk=chat.id, message_id=None, direction="out", author="director", msg_type="text", text=text)
    db.add(msg)
    db.commit()  # до отправки — чтобы эхо вебхука узнало сообщение
    try:
        sent = client.send_text(chat.chat_id, text)
    except AvitoError as e:
        db.delete(msg)
        db.commit()
        raise HTTPException(502, str(e))
    if sent.get("id") and not msg.message_id:
        msg.message_id = str(sent["id"])
    now = timing.utcnow()
    service.take_over(db, chat, now)
    chat.last_message_at = now
    if chat.lead:
        db.add(m.LeadActivity(lead_id=chat.lead.id, kind="message", text=f"Вы (Авито): {text}", user_id=user.id))
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
