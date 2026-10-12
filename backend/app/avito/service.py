"""Логика обработки входящих сообщений Авито: заявка в CRM → ответ бота → уведомление в Telegram."""
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..config import settings
from . import agent
from .client import AvitoError, client
from .default_script import DEFAULT_SCRIPT
from .notify import esc, telegram

log = logging.getLogger("avito.service")

OBJECT_TYPE_NOTE = {"новостройка": "новостройка", "вторичка": "вторичка", "дом": "частный дом", "коммерция": "коммерческое помещение"}


# ---------- скрипт ----------

def active_script(db: Session) -> m.SalesScript:
    s = db.scalar(select(m.SalesScript).where(m.SalesScript.is_active == True))  # noqa: E712
    if not s:
        s = m.SalesScript(version=1, text=DEFAULT_SCRIPT, note="Стартовая версия", is_active=True, created_by="director")
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def new_script_version(db: Session, text: str, note: str | None, created_by: str, activate: bool) -> m.SalesScript:
    last = db.scalar(select(m.SalesScript).order_by(m.SalesScript.version.desc()))
    s = m.SalesScript(version=(last.version + 1 if last else 1), text=text, note=note, created_by=created_by, is_active=False)
    db.add(s)
    db.flush()
    if activate:
        activate_script(db, s)
    db.commit()
    db.refresh(s)
    return s


def activate_script(db: Session, s: m.SalesScript) -> None:
    for other in db.scalars(select(m.SalesScript).where(m.SalesScript.is_active == True)):  # noqa: E712
        other.is_active = False
    s.is_active = True
    db.flush()


# ---------- чат и заявка ----------

def _lead_url(lead_id: int) -> str:
    return f"{settings.PUBLIC_URL.rstrip('/')}/#/leads/{lead_id}"


def _ensure_chat(db: Session, chat_id: str, item_id: int | None, account_user_id: int | None) -> m.AvitoChat:
    chat = db.scalar(select(m.AvitoChat).where(m.AvitoChat.chat_id == chat_id))
    if chat:
        return chat
    info: dict = {}
    try:
        info = client.chat_info(chat_id)
    except AvitoError as e:
        log.warning("chat_info %s: %s", chat_id, e)
    ctx = (info.get("context") or {}).get("value") or {}
    client_user = None
    for u in info.get("users") or []:
        if account_user_id is None or int(u.get("id", 0)) != int(account_user_id):
            client_user = u
            break
    chat = m.AvitoChat(
        chat_id=chat_id,
        client_user_id=int(client_user["id"]) if client_user and client_user.get("id") else None,
        client_name=(client_user or {}).get("name"),
        item_id=item_id or ctx.get("id"),
        item_title=ctx.get("title"),
        item_url=ctx.get("url"),
        mode="bot" if settings.AVITO_BOT_ENABLED else "manual",
    )
    db.add(chat)
    db.flush()
    # заявка в CRM
    name = chat.client_name or "Клиент с Авито"
    note = "Авито"
    if chat.item_title:
        note += f" · объявление «{chat.item_title}»"
    lead = m.Lead(name=name, source="avito", note=note, lead_cost=Decimal(0))
    db.add(lead)
    db.flush()
    db.add(m.LeadActivity(lead_id=lead.id, kind="stage", text="Заявка создана из чата Авито"))
    chat.lead_id = lead.id
    db.flush()
    return chat


def _apply_fields(db: Session, chat: m.AvitoChat, fields: dict) -> list[str]:
    """Переносит извлечённые ботом поля в заявку. Возвращает список того, что обновилось."""
    lead = chat.lead
    if not lead or not fields:
        return []
    changed = []
    if fields.get("name") and (lead.name == "Клиент с Авито" or lead.name == chat.client_name):
        lead.name = fields["name"]
        changed.append(f"имя: {lead.name}")
    if fields.get("phone") and not lead.phone:
        lead.phone = str(fields["phone"])[:50]
        changed.append(f"телефон: {lead.phone}")
    if fields.get("area_m2") and not lead.area_m2:
        try:
            lead.area_m2 = Decimal(str(fields["area_m2"]))
            changed.append(f"площадь: {lead.area_m2} м²")
        except Exception:
            pass
    if fields.get("district") and not lead.address:
        lead.address = str(fields["district"])[:300]
        changed.append(f"адрес: {lead.address}")
    if fields.get("has_project") in m.PROJECT_KINDS and lead.project_kind == "none" and fields["has_project"] != "none":
        lead.project_kind = fields["has_project"]
        changed.append(f"проект: {m.PROJECT_KINDS[lead.project_kind]}")
    extra = []
    if fields.get("object_type"):
        extra.append(OBJECT_TYPE_NOTE.get(fields["object_type"], fields["object_type"]))
    if fields.get("start_when"):
        extra.append(f"старт: {fields['start_when']}")
    if fields.get("call_time"):
        extra.append(f"звонить: {fields['call_time']}")
    for e in extra:
        if e not in (lead.note or ""):
            lead.note = ((lead.note or "") + " · " + e).strip(" ·")
            changed.append(e)
    if changed and lead.stage == "new":
        lead.stage = "contacted"
    return changed


def _known(chat: m.AvitoChat) -> dict:
    lead = chat.lead
    if not lead:
        return {}
    return {
        "имя": lead.name if lead.name not in ("Клиент с Авито", chat.client_name) else None,
        "телефон": lead.phone,
        "площадь_м2": float(lead.area_m2) if lead.area_m2 else None,
        "адрес": lead.address,
        "проект": m.PROJECT_KINDS.get(lead.project_kind) if lead.project_kind != "none" else None,
        "заметка": lead.note,
    }


def _history(chat: m.AvitoChat, limit: int = 40) -> list[dict]:
    msgs = chat.messages[-limit:]
    return [{"direction": x.direction, "author": x.author, "text": x.text} for x in msgs if x.author != "system"]


# ---------- главный обработчик ----------

def handle_incoming(db: Session, ev: dict) -> None:
    """ev — результат client.parse_webhook. Вызывается в фоне, после ответа 200 Авито."""
    if ev["message_id"] and db.scalar(select(m.AvitoMessage).where(m.AvitoMessage.message_id == ev["message_id"])):
        return  # дубль вебхука или эхо нашего же сообщения, отправленного через API
    account_id = ev.get("account_user_id")
    try:
        if account_id is None:
            account_id = client.user_id()
    except AvitoError as e:
        log.warning("user_id: %s", e)
    chat = _ensure_chat(db, ev["chat_id"], ev.get("item_id"), account_id)
    is_new_chat = len(chat.messages) == 0
    outgoing = account_id is not None and ev.get("author_id") is not None and int(ev["author_id"]) == int(account_id)
    now = datetime.utcnow()

    if ev.get("type") == "system" or ev.get("flow_id"):
        db.add(m.AvitoMessage(chat_pk=chat.id, message_id=ev["message_id"] or None, direction="in", author="system",
                              msg_type=ev["type"], text=ev["text"]))
        db.commit()
        return

    if outgoing:
        # Наше сообщение. Если его отправил не бот (бот пишет через API и сам сохраняет) — это директор из приложения.
        sent_by_bot = db.scalar(select(m.AvitoMessage).where(m.AvitoMessage.chat_pk == chat.id, m.AvitoMessage.direction == "out",
                                                           m.AvitoMessage.text == ev["text"], m.AvitoMessage.message_id == None))  # noqa: E711
        if sent_by_bot:
            sent_by_bot.message_id = ev["message_id"] or None
        else:
            db.add(m.AvitoMessage(chat_pk=chat.id, message_id=ev["message_id"] or None, direction="out", author="director",
                                  msg_type=ev["type"], text=ev["text"]))
            chat.mode = "manual"
            chat.manual_until = now + timedelta(hours=settings.AVITO_MANUAL_HOLD_HOURS)
            if chat.lead:
                db.add(m.LeadActivity(lead_id=chat.lead.id, kind="message", text=f"Вы (Авито): {ev['text']}"))
        chat.last_message_at = now
        db.commit()
        return

    # входящее от клиента
    db.add(m.AvitoMessage(chat_pk=chat.id, message_id=ev["message_id"] or None, direction="in", author="client",
                          msg_type=ev["type"], text=ev["text"]))
    chat.last_message_at = now
    if chat.lead:
        db.add(m.LeadActivity(lead_id=chat.lead.id, kind="message", text=f"Клиент (Авито): {ev['text']}"))
    db.commit()
    db.refresh(chat)
    client.mark_read(chat.chat_id)

    bot_allowed = settings.AVITO_BOT_ENABLED and (chat.mode == "bot" or (chat.manual_until and chat.manual_until < now))
    if chat.mode == "manual" and chat.manual_until and chat.manual_until < now and settings.AVITO_BOT_ENABLED:
        chat.mode = "bot"
        chat.manual_until = None

    reply_text, result = "", None
    if bot_allowed and settings.ANTHROPIC_API_KEY:
        try:
            script = active_script(db)
            result = agent.run(script.text, _history(chat), {"item_title": chat.item_title, "client_name": chat.client_name, "known": _known(chat)})
        except Exception as e:  # noqa: BLE001 — бот не должен ронять вебхук
            log.exception("agent: %s", e)
            result = None
        if result:
            changed = _apply_fields(db, chat, result.fields)
            if changed and chat.lead:
                db.add(m.LeadActivity(lead_id=chat.lead.id, kind="note", text="Бот обновил заявку: " + ", ".join(changed)))
            if result.qualified != "unknown":
                chat.qualified = result.qualified
            if result.handoff:
                chat.handoff_reason = result.handoff_reason[:300] if result.handoff_reason else "передано руководителю"
                if chat.lead and chat.qualified == "yes" and chat.lead.stage in ("new", "contacted"):
                    chat.lead.stage = "contacted"
            if result.qualified == "no" and chat.lead and chat.lead.stage == "new":
                pass  # отказ не закрываем автоматически — директор решает сам
            reply_text = result.reply
            if reply_text:
                try:
                    sent = client.send_text(chat.chat_id, reply_text)
                    db.add(m.AvitoMessage(chat_pk=chat.id, message_id=str(sent.get("id")) if sent.get("id") else None,
                                          direction="out", author="bot", msg_type="text", text=reply_text))
                    if chat.lead:
                        db.add(m.LeadActivity(lead_id=chat.lead.id, kind="message", text=f"Бот (Авито): {reply_text}"))
                except AvitoError as e:
                    log.warning("send_text: %s", e)
                    reply_text = ""
            db.commit()

    # уведомление в Telegram — на каждое входящее
    lead_id = chat.lead.id if chat.lead else None
    head = "🆕 Новый чат Авито" if is_new_chat else "💬 Авито"
    if result and result.qualified == "yes":
        head = "🔥 " + head
    if result and result.handoff:
        head += " · нужен ваш ответ"
    if chat.mode == "manual":
        head += " · вы ведёте чат сами"
    lines = [f"<b>{head}</b>",
             f"{esc(chat.client_name or 'Клиент')} — {esc(chat.item_title or 'объявление')}",
             f"«{esc(ev['text'][:500])}»"]
    if reply_text:
        lines.append(f"Бот: «{esc(reply_text[:400])}»")
    if result and result.summary:
        lines.append(f"Итог: {esc(result.summary[:300])}")
    if result and result.handoff and result.handoff_reason:
        lines.append(f"Причина передачи: {esc(result.handoff_reason[:200])}")
    if lead_id:
        lines.append(f"Заявка № {lead_id}: {_lead_url(lead_id)}")
    telegram("\n".join(lines))
