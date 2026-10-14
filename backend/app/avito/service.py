"""Логика переписки Авито: входящее → заявка в CRM и уведомление сразу → ответ бота с паузой через очередь.

Бот ведёт себя как живой менеджер (раздел 3.3 ТЗ):
- отвечает с AVITO_HOURS_START до AVITO_HOURS_END по Москве; ночные сообщения — утром со случайным разбросом;
- пауза перед ответом: первый ответ в чате 2–6 мин, дальше 40 с – 3 мин, длиннее при длинном ответе;
- клиент дописал, пока бот «думал», — отвечаем одним сообщением на всё;
- клиент замолчал после нашего вопроса — два напоминания, затем заявка «Проиграна: не ответил»;
- директор написал в чат сам — бот молчит AVITO_MANUAL_HOLD_HOURS часов;
- уведомление в Telegram — сразу на каждое входящее; ответ бота дописывается в то же сообщение.
Отложенные действия живут в таблице avito_tasks, их выполняет worker.py.
"""
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..config import settings
from . import notify, timing
from .client import AvitoError, client
from .default_script import DEFAULT_SCRIPT
from .notify import esc

log = logging.getLogger("avito.service")

OBJECT_TYPE_NOTE = {"новостройка": "новостройка", "вторичка": "вторичка", "дом": "частный дом", "коммерция": "коммерческое помещение"}
DEFAULT_NAME = "Клиент с Авито"


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

def lead_url(lead_id: int) -> str:
    return f"{settings.PUBLIC_URL.rstrip('/')}/#/leads/{lead_id}"


def _ensure_chat(db: Session, chat_id: str, item_id: int | None, account_user_id: int | None) -> tuple[m.AvitoChat, bool]:
    chat = db.scalar(select(m.AvitoChat).where(m.AvitoChat.chat_id == chat_id))
    if chat:
        return chat, False
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
        followup_stage=0,
    )
    db.add(chat)
    db.flush()
    name = chat.client_name or DEFAULT_NAME
    note = "Авито"
    if chat.item_title:
        note += f" · объявление «{chat.item_title}»"
    lead = m.Lead(name=name, source="avito", note=note, lead_cost=Decimal(0))
    db.add(lead)
    db.flush()
    db.add(m.LeadActivity(lead_id=lead.id, kind="stage", text="Заявка создана из чата Авито"))
    chat.lead_id = lead.id
    db.flush()
    return chat, True


def apply_fields(db: Session, chat: m.AvitoChat, fields: dict) -> list[str]:
    """Переносит извлечённые ботом поля в заявку. Возвращает список того, что обновилось."""
    lead = chat.lead
    if not lead or not fields:
        return []
    changed = []
    if fields.get("name") and lead.name in (DEFAULT_NAME, chat.client_name):
        lead.name = str(fields["name"])[:200]
        changed.append(f"имя: {lead.name}")
    if fields.get("phone") and not lead.phone:
        lead.phone = str(fields["phone"])[:50]
        changed.append(f"телефон: {lead.phone}")
    if fields.get("area_m2") and not lead.area_m2:
        try:
            lead.area_m2 = Decimal(str(fields["area_m2"]))
            changed.append(f"площадь: {lead.area_m2} м²")
        except Exception:  # noqa: BLE001
            pass
    if fields.get("district") and not lead.address:
        lead.address = str(fields["district"])[:300]
        changed.append(f"адрес: {lead.address}")
    if fields.get("has_project") in m.PROJECT_KINDS and lead.project_kind == "none" and fields["has_project"] != "none":
        lead.project_kind = fields["has_project"]
        changed.append(f"проект: {m.PROJECT_KINDS[lead.project_kind]}")
    extra = []
    if fields.get("has_project") == "none" and "без проекта" not in (lead.note or ""):
        extra.append("без проекта")
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
    return changed


def known_fields(chat: m.AvitoChat) -> dict:
    lead = chat.lead
    if not lead:
        return {}
    return {
        "имя": lead.name if lead.name not in (DEFAULT_NAME, chat.client_name) else None,
        "телефон": lead.phone,
        "площадь_м2": float(lead.area_m2) if lead.area_m2 else None,
        "адрес": lead.address,
        "проект": m.PROJECT_KINDS.get(lead.project_kind) if lead.project_kind != "none" else None,
        "заметка": lead.note,
    }


def history(chat: m.AvitoChat, limit: int = 40) -> list[dict]:
    msgs = [x for x in chat.messages if x.author != "system"][-limit:]
    return [{"direction": x.direction, "author": x.author, "text": x.text} for x in msgs]


def last_dialog_message(chat: m.AvitoChat) -> m.AvitoMessage | None:
    for x in reversed(chat.messages):
        if x.author != "system":
            return x
    return None


def client_waiting(chat: m.AvitoChat) -> bool:
    """Последнее сообщение в чате — от клиента, мы ещё не ответили."""
    last = last_dialog_message(chat)
    return bool(last and last.direction == "in")


def bot_can_reply(chat: m.AvitoChat, now: datetime) -> bool:
    """Бот включён и чат не в ручном режиме. Истёкший ручной режим возвращает чат боту."""
    if not (settings.AVITO_BOT_ENABLED and settings.ANTHROPIC_API_KEY):
        return False
    if chat.mode == "manual":
        if chat.manual_until and chat.manual_until <= now:
            chat.mode = "bot"
            chat.manual_until = None
        else:
            return False
    return True


# ---------- очередь ----------

def pending_tasks(db: Session, chat: m.AvitoChat, kinds: tuple[str, ...] | None = None) -> list[m.AvitoTask]:
    q = select(m.AvitoTask).where(m.AvitoTask.chat_pk == chat.id, m.AvitoTask.status == "pending")
    if kinds:
        q = q.where(m.AvitoTask.kind.in_(kinds))
    return list(db.scalars(q.order_by(m.AvitoTask.due_at)).all())


def cancel_tasks(db: Session, chat: m.AvitoChat, kinds: tuple[str, ...] | None = None) -> int:
    n = 0
    for t in pending_tasks(db, chat, kinds):
        t.status = "cancelled"
        t.done_at = timing.utcnow()
        n += 1
    return n


def add_task(db: Session, chat: m.AvitoChat, kind: str, due_at: datetime, payload: dict | None = None) -> m.AvitoTask:
    t = m.AvitoTask(chat_pk=chat.id, kind=kind, due_at=due_at, status="pending",
                    payload=json.dumps(payload, ensure_ascii=False) if payload else None, attempts=0)
    db.add(t)
    db.flush()
    return t


def _fit_hours(t: datetime) -> datetime:
    return timing.fit_window(t, settings.AVITO_HOURS_START, settings.AVITO_HOURS_END, settings.AVITO_MORNING_SPREAD_MIN)


def schedule_reply(db: Session, chat: m.AvitoChat, now: datetime) -> datetime:
    """Запланировать ответ на входящее. Возвращает время, когда бот «начнёт печатать»."""
    # Ответ уже был готов, но клиент дописал — выбрасываем его и перечитываем переписку целиком.
    stale = cancel_tasks(db, chat, ("send",))
    think = pending_tasks(db, chat, ("think",))
    if think:
        t = think[0]
        # Клиент дописывает прямо перед ответом — подождать ещё немного, ответить на всё сразу.
        if t.due_at - now < timedelta(seconds=45):
            t.due_at = _fit_hours(now + timing.debounce_delay())
        return t.due_at
    first = not any(x.direction == "out" for x in chat.messages)
    delay = timing.regenerate_delay() if stale else timing.think_delay(first)
    due = _fit_hours(now + delay)
    add_task(db, chat, "think", due, {"first": first})
    return due


def schedule_followup(db: Session, chat: m.AvitoChat, stage: int, now: datetime) -> None:
    if not settings.AVITO_FOLLOWUP_ENABLED:
        return
    due = timing.fit_window(now + timing.followup_delay(stage), settings.AVITO_FOLLOWUP_HOURS_START,
                            settings.AVITO_FOLLOWUP_HOURS_END, 90)
    add_task(db, chat, "followup", due, {"stage": stage, "after": now.isoformat()})


def followup_allowed(chat: m.AvitoChat) -> bool:
    """Напоминаем только тем, с кем бот ведёт квалификацию сам: не мелочь, не передано руководителю, заявка открыта."""
    lead = chat.lead
    return (chat.mode == "bot" and chat.qualified != "no" and not chat.handoff_reason
            and (lead is None or lead.stage in ("new", "contacted")))


# ---------- уведомления ----------

def _head(chat: m.AvitoChat, is_new: bool, handoff: bool = False) -> str:
    head = "🆕 Новый чат Авито" if is_new else "💬 Авито"
    if chat.qualified == "yes":
        head = "🔥 Наш объект · " + head
    if handoff:
        head += " · нужен ваш ответ"
    if chat.mode == "manual":
        head += " · вы ведёте чат сами"
    return head


def _render(n: dict) -> str:
    lines = [f"<b>{esc(n['head'])}</b>", f"{esc(n['who'])}", f"«{esc(n['text'][:600])}»"]
    lines += [x for x in n.get("status", []) if x]
    if n.get("lead_id"):
        lines.append(f"Заявка № {n['lead_id']}: {lead_url(n['lead_id'])}")
    return "\n".join(lines)


def _msk(t: datetime) -> str:
    loc = timing.to_msk(t)
    today = timing.to_msk(timing.utcnow()).date()
    return f"{loc:%H:%M}" if loc.date() == today else f"{loc:%d.%m %H:%M}"


def notify_incoming(db: Session, chat: m.AvitoChat, text: str, is_new: bool, planned_at: datetime | None) -> None:
    if planned_at:
        status = [f"⏳ Бот ответит около {_msk(planned_at)}"]
    elif chat.mode == "manual":
        status = ["Бот молчит — ответьте сами в Авито или в CRM"]
    else:
        status = ["Бот выключен — ответьте сами"]
    n = {"head": _head(chat, is_new), "who": f"{chat.client_name or 'Клиент'} — {chat.item_title or 'объявление'}",
         "text": text, "status": status, "lead_id": chat.lead_id, "is_new": is_new}
    mid = notify.tg_send(_render(n))
    chat.notify_msg_id = mid or None
    chat.notify_json = json.dumps(n, ensure_ascii=False)


def notify_bot_reply(db: Session, chat: m.AvitoChat, reply: str, info: dict) -> None:
    """Дописать ответ бота и итог в уведомление о последнем входящем; при передаче — отдельное сообщение со звуком."""
    try:
        n = json.loads(chat.notify_json or "{}")
    except ValueError:
        n = {}
    if not n:
        return
    n["head"] = _head(chat, n.get("is_new", False), handoff=bool(info.get("handoff")))
    status = [f"Бот: «{esc(reply[:700])}»"]
    if info.get("summary"):
        status.append(f"Итог: {esc(info['summary'][:300])}")
    n["status"] = status
    chat.notify_json = json.dumps(n, ensure_ascii=False)
    if chat.notify_msg_id:
        notify.tg_edit(chat.notify_msg_id, _render(n))
    else:
        notify.tg_send(_render(n))
    if info.get("handoff"):
        lead = chat.lead
        lines = [f"<b>🙋 Нужен ваш ответ · Авито</b>", esc(f"{lead.name if lead else chat.client_name or 'Клиент'} — {chat.item_title or 'объявление'}")]
        if info.get("handoff_reason"):
            lines.append(f"Причина: {esc(info['handoff_reason'][:200])}")
        if info.get("summary"):
            lines.append(f"Итог: {esc(info['summary'][:300])}")
        if lead and lead.phone:
            lines.append(f"Телефон: {esc(lead.phone)}")
        if lead and lead.note:
            lines.append(esc(lead.note[:300]))
        if chat.lead_id:
            lines.append(f"Заявка № {chat.lead_id}: {lead_url(chat.lead_id)}")
        notify.tg_send("\n".join(lines))


# ---------- входящие ----------

def handle_incoming(db: Session, ev: dict) -> None:
    """ev — результат client.parse_webhook. Вызывается в фоне, после ответа 200 Авито."""
    if ev["message_id"] and db.scalar(select(m.AvitoMessage).where(m.AvitoMessage.message_id == ev["message_id"])):
        return  # дубль вебхука или эхо нашего сообщения, отправленного через API
    account_id = ev.get("account_user_id")
    try:
        if account_id is None:
            account_id = client.user_id()
    except AvitoError as e:
        log.warning("user_id: %s", e)
    chat, is_new = _ensure_chat(db, ev["chat_id"], ev.get("item_id"), account_id)
    outgoing = account_id is not None and ev.get("author_id") is not None and int(ev["author_id"]) == int(account_id)
    now = timing.utcnow()

    if ev.get("type") == "system" or ev.get("flow_id"):
        db.add(m.AvitoMessage(chat_pk=chat.id, message_id=ev["message_id"] or None, direction="in", author="system",
                              msg_type=ev["type"], text=ev["text"]))
        db.commit()
        return

    if outgoing:
        # Наше сообщение. Бот и кнопка «Ответить» в CRM сохраняют своё сообщение до отправки — найдём его.
        ours = db.scalar(select(m.AvitoMessage).where(m.AvitoMessage.chat_pk == chat.id, m.AvitoMessage.direction == "out",
                                                     m.AvitoMessage.text == ev["text"], m.AvitoMessage.message_id == None))  # noqa: E711
        if ours:
            ours.message_id = ev["message_id"] or None
        else:
            # Директор написал из приложения Авито — бот замолкает, напоминания отменяются.
            db.add(m.AvitoMessage(chat_pk=chat.id, message_id=ev["message_id"] or None, direction="out", author="director",
                                  msg_type=ev["type"], text=ev["text"]))
            take_over(db, chat, now)
            if chat.lead:
                db.add(m.LeadActivity(lead_id=chat.lead.id, kind="message", text=f"Вы (Авито): {ev['text']}"))
        chat.last_message_at = now
        db.commit()
        return

    # входящее от клиента
    db.add(m.AvitoMessage(chat_pk=chat.id, message_id=ev["message_id"] or None, direction="in", author="client",
                          msg_type=ev["type"], text=ev["text"]))
    chat.last_message_at = now
    chat.last_client_at = now
    chat.followup_stage = 0
    cancel_tasks(db, chat, ("followup", "close"))
    if chat.lead:
        db.add(m.LeadActivity(lead_id=chat.lead.id, kind="message", text=f"Клиент (Авито): {ev['text']}"))
    db.flush()
    db.refresh(chat)

    planned = schedule_reply(db, chat, now) if bot_can_reply(chat, now) else None
    db.commit()
    notify_incoming(db, chat, ev["text"], is_new, planned)
    db.commit()


def take_over(db: Session, chat: m.AvitoChat, now: datetime) -> None:
    """Директор ответил сам: бот молчит AVITO_MANUAL_HOLD_HOURS часов и не вмешивается."""
    indefinite = chat.mode == "manual" and chat.manual_until is None  # «вести самому» из CRM — бессрочно, не сокращаем
    chat.mode = "manual"
    chat.manual_until = None if indefinite else now + timedelta(hours=settings.AVITO_MANUAL_HOLD_HOURS)
    chat.last_our_at = now
    chat.followup_stage = 0
    cancel_tasks(db, chat)


def return_to_bot(db: Session, chat: m.AvitoChat, now: datetime) -> datetime | None:
    """Директор вернул чат боту. Если клиент ждёт ответа — бот ответит с обычной паузой."""
    chat.mode = "bot"
    chat.manual_until = None
    if client_waiting(chat) and bot_can_reply(chat, now):
        return schedule_reply(db, chat, now)
    return None
