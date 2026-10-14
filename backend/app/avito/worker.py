"""Очередь отложенных действий бота Авито и сторож «клиент ждёт ответа».

Задачи (таблица avito_tasks):
- think    — «прочитать» чат (отметка о прочтении), сгенерировать ответ, проверить его на запреты → создать send;
- send     — отправить очередную часть ответа (второе короткое сообщение — отдельной задачей с паузой);
- followup — напоминание клиенту, замолчавшему после нашего вопроса (stage 1 и 2);
- close    — после второго напоминания и N дней тишины: заявка «Проиграна: не ответил».
Фоновый поток опрашивает очередь каждые 10 с; тесты вызывают run_due(db, now) напрямую.
"""
import json
import logging
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from .. import models as m
from ..config import settings
from ..db import SessionLocal
from . import agent, guard, notify, service, timing
from .client import client
from .notify import esc

log = logging.getLogger("avito.worker")
MAX_ATTEMPTS = 3
RETRY_SECONDS = [60, 180]
TICK_SECONDS = 10
WATCHDOG_EVERY = 60


def _payload(task: m.AvitoTask) -> dict:
    try:
        return json.loads(task.payload or "{}")
    except ValueError:
        return {}


def _in_hours(t: datetime) -> bool:
    return timing.in_window(t, settings.AVITO_HOURS_START, settings.AVITO_HOURS_END)


def _who(chat: m.AvitoChat) -> str:
    lead = chat.lead
    name = lead.name if lead else (chat.client_name or "Клиент")
    return f"{name} — {chat.item_title or 'объявление'}"


def _alert(chat: m.AvitoChat, title: str, details: list[str]) -> None:
    lines = [f"<b>⚠️ {esc(title)}</b>", esc(_who(chat))] + [esc(x) for x in details if x]
    if chat.lead_id:
        lines.append(f"Заявка № {chat.lead_id}: {service.lead_url(chat.lead_id)}")
    notify.tg_send("\n".join(lines))


# ---------- генерация ответа ----------

def _generate(db: Session, chat: m.AvitoChat, now: datetime, purpose: str) -> tuple[agent.AgentResult | None, list[str]]:
    script = service.active_script(db)
    ctx = {"item_title": chat.item_title, "client_name": chat.client_name, "known": service.known_fields(chat),
           "now_msk": timing.to_msk(now), "handoff_done": bool(chat.handoff_reason)}
    res = agent.run(script.text, service.history(chat), ctx, purpose)
    bad = guard.violations(res.reply)
    if bad:
        log.warning("guard: чат %s, нарушения %s: %r — пишу заново", chat.id, bad, res.reply)
        res = agent.run(script.text, service.history(chat), ctx, purpose, feedback=", ".join(bad))
        bad = guard.violations(res.reply)
    if bad:
        return None, bad
    return res, []


def _apply_result(db: Session, chat: m.AvitoChat, res: agent.AgentResult) -> bool:
    """Заносит итог хода бота в заявку. Возвращает True, если это новая передача руководителю."""
    lead = chat.lead
    changed = service.apply_fields(db, chat, res.fields)
    if changed and lead:
        db.add(m.LeadActivity(lead_id=lead.id, kind="note", text="Бот обновил заявку: " + ", ".join(changed)))
    if res.qualified != "unknown":
        chat.qualified = res.qualified
    if lead and lead.stage == "new" and chat.qualified == "yes":
        lead.stage = "contacted"
        db.add(m.LeadActivity(lead_id=lead.id, kind="stage", text="Связались — бот квалифицировал заявку в чате Авито"))
    new_handoff = False
    if res.handoff:
        reason = (res.handoff_reason or "передано руководителю")[:300]
        new_handoff = reason != chat.handoff_reason
        chat.handoff_reason = reason
        if new_handoff and lead:
            db.add(m.LeadActivity(lead_id=lead.id, kind="note",
                                  text=f"Бот передал вам: {reason}." + (f" Итог: {res.summary}" if res.summary else "")))
    return new_handoff


# ---------- обработчики задач ----------

def _think(db: Session, task: m.AvitoTask, now: datetime) -> None:
    chat = task.chat
    if not service.bot_can_reply(chat, now) or not service.client_waiting(chat):
        task.status = "cancelled"
        return
    if not _in_hours(now):  # обработчик стоял (перезапуск сервера ночью) — ответим утром
        task.status, task.due_at = "pending", service._fit_hours(now)
        return
    client.mark_read(chat.chat_id)
    res, bad = _generate(db, chat, now, "reply")
    if res is None:
        chat.alerted_at = chat.last_client_at
        _alert(chat, "Бот не отправил ответ — нарушение правил", [
            f"Нарушения: {', '.join(bad)}. Ответьте клиенту сами.", f"Клиент: «{(service.last_dialog_message(chat).text or '')[:300]}»"])
        return
    handoff = _apply_result(db, chat, res)
    if not res.parts:  # например, клиент написал «спасибо» — отвечать нечего, сторож не должен поднимать тревогу
        chat.alerted_at = chat.last_client_at
        service.notify_bot_reply(db, chat, "(бот решил не отвечать)", {"summary": res.summary})
        return
    p = _payload(task)
    service.add_task(db, chat, "send", now + timing.typing_delay(res.parts[0], bool(p.get("first"))), {
        "purpose": "reply", "parts": res.parts, "all": res.reply, "gen_at": now.isoformat(),
        "info": {"summary": res.summary, "handoff": handoff, "handoff_reason": res.handoff_reason,
                 "expects_answer": res.expects_answer},
    })


def _send(db: Session, task: m.AvitoTask, now: datetime) -> None:
    chat = task.chat
    p = _payload(task)
    purpose = p.get("purpose", "reply")
    if not service.bot_can_reply(chat, now):
        task.status = "cancelled"
        return
    since = datetime.fromisoformat(p.get("gen_at") or p.get("after"))
    if chat.last_client_at and chat.last_client_at > since:
        # Клиент написал после того, как ответ был готов: этот ответ устарел.
        task.status = "cancelled"
        if purpose == "reply" and not service.pending_tasks(db, chat, ("think",)):
            service.schedule_reply(db, chat, now)
        return
    part = p["parts"][0]
    # Сохраняем до отправки: эхо вебхука узнает своё сообщение и не примет его за ответ директора.
    msg = m.AvitoMessage(chat_pk=chat.id, message_id=None, direction="out", author="bot", msg_type="text", text=part)
    db.add(msg)
    db.commit()
    try:
        sent = client.send_text(chat.chat_id, part)
    except Exception:
        db.delete(msg)
        db.commit()
        raise
    if sent.get("id") and not msg.message_id:
        msg.message_id = str(sent["id"])
    chat.last_our_at = now
    chat.last_message_at = now
    if chat.lead:
        db.add(m.LeadActivity(lead_id=chat.lead.id, kind="message", text=f"Бот (Авито): {part}"))
    rest = p["parts"][1:]
    if rest:
        service.add_task(db, chat, "send", now + timing.second_part_delay(rest[0]), {**p, "parts": rest})
        return
    info = p.get("info") or {}
    if purpose == "reply":
        service.notify_bot_reply(db, chat, p.get("all") or part, info)
        if info.get("expects_answer") and service.followup_allowed(chat):
            service.schedule_followup(db, chat, 1, now)
        return
    # напоминание
    stage = int(p.get("stage", 1))
    chat.followup_stage = stage
    notify.tg_send(f"🔁 Напоминание {stage} клиенту отправлено · {esc(_who(chat))}\n«{esc((p.get('all') or part)[:400])}»"
                   + (f"\nЗаявка № {chat.lead_id}: {service.lead_url(chat.lead_id)}" if chat.lead_id else ""), silent=True)
    if stage == 1:
        service.schedule_followup(db, chat, 2, now)
    else:
        service.add_task(db, chat, "close", now + timedelta(days=settings.AVITO_CLOSE_AFTER_DAYS), {"after": now.isoformat()})


def _followup(db: Session, task: m.AvitoTask, now: datetime) -> None:
    chat = task.chat
    p = _payload(task)
    after = datetime.fromisoformat(p["after"])
    if (chat.last_client_at and chat.last_client_at > after) or not service.followup_allowed(chat) \
            or not service.bot_can_reply(chat, now) or not settings.AVITO_FOLLOWUP_ENABLED:
        task.status = "cancelled"
        return
    if not timing.in_window(now, settings.AVITO_FOLLOWUP_HOURS_START, settings.AVITO_FOLLOWUP_HOURS_END):
        task.status = "pending"
        task.due_at = timing.fit_window(now, settings.AVITO_FOLLOWUP_HOURS_START, settings.AVITO_FOLLOWUP_HOURS_END, 90)
        return
    stage = int(p.get("stage", 1))
    res, bad = _generate(db, chat, now, f"followup{stage}")
    if res is None or not res.parts:
        if bad:
            log.warning("followup: чат %s, нарушения %s — напоминание не отправлено", chat.id, bad)
        return
    service.add_task(db, chat, "send", now + timing.typing_delay(res.reply, False), {
        "purpose": "followup", "stage": stage, "parts": res.parts, "all": res.reply, "after": p["after"],
        "gen_at": now.isoformat()})


def _close(db: Session, task: m.AvitoTask, now: datetime) -> None:
    chat = task.chat
    after = datetime.fromisoformat(_payload(task)["after"])
    lead = chat.lead
    if (chat.last_client_at and chat.last_client_at > after) or not lead or lead.stage not in ("new", "contacted") \
            or chat.mode != "bot":
        task.status = "cancelled"
        return
    lead.stage = "lost"
    lead.lost_reason = "не ответил"
    db.add(m.LeadActivity(lead_id=lead.id, kind="stage", text="Проиграна: не ответил — молчит после двух напоминаний в Авито"))
    notify.tg_send(f"📭 Заявка № {lead.id} закрыта: клиент не ответил после двух напоминаний · {esc(_who(chat))}", silent=True)


HANDLERS = {"think": _think, "send": _send, "followup": _followup, "close": _close}


# ---------- цикл ----------

def run_due(db: Session, now: datetime | None = None) -> int:
    """Выполнить все задачи, срок которых наступил. Возвращает число обработанных."""
    now = now or timing.utcnow()
    ids = db.scalars(select(m.AvitoTask.id).where(m.AvitoTask.status == "pending", m.AvitoTask.due_at <= now)
                     .order_by(m.AvitoTask.due_at).limit(50)).all()
    done = 0
    for tid in ids:
        claimed = db.execute(update(m.AvitoTask).where(m.AvitoTask.id == tid, m.AvitoTask.status == "pending")
                             .values(status="running"))
        db.commit()
        if claimed.rowcount != 1:
            continue
        task = db.get(m.AvitoTask, tid)
        db.refresh(task.chat)
        try:
            HANDLERS[task.kind](db, task, now)
            if task.status == "running":
                task.status = "done"
            if task.status in ("done", "cancelled"):
                task.done_at = now
            db.commit()
        except Exception as e:  # noqa: BLE001 — ошибка одной задачи не должна останавливать очередь
            log.exception("task %s (%s): %s", tid, task.kind, e)
            db.rollback()
            task = db.get(m.AvitoTask, tid)
            task.attempts = (task.attempts or 0) + 1
            task.error = str(e)[:1000]
            if task.attempts >= MAX_ATTEMPTS:
                task.status = "failed"
                task.done_at = now
                chat = task.chat
                if task.kind in ("think", "send"):
                    chat.alerted_at = chat.last_client_at
                    _alert(chat, "Бот не смог ответить клиенту", [f"Ошибка: {str(e)[:300]}", "Ответьте сами в Авито или в CRM."])
            else:
                task.status = "pending"
                task.due_at = now + timedelta(seconds=RETRY_SECONDS[task.attempts - 1])
            db.commit()
        done += 1
    return done


def watchdog(db: Session, now: datetime | None = None) -> int:
    """Алерт директору, если клиент ждёт ответа дольше положенного (сбой бота или чат ведёте вы и забыли)."""
    now = now or timing.utcnow()
    chats = db.scalars(select(m.AvitoChat).where(
        m.AvitoChat.last_client_at != None,  # noqa: E711
        or_(m.AvitoChat.last_our_at == None, m.AvitoChat.last_our_at < m.AvitoChat.last_client_at),  # noqa: E711
        or_(m.AvitoChat.alerted_at == None, m.AvitoChat.alerted_at != m.AvitoChat.last_client_at),  # noqa: E711
    )).all()
    sent = 0
    for chat in chats:
        start = timing.latest_start(chat.last_client_at, settings.AVITO_HOURS_START, settings.AVITO_HOURS_END,
                                    settings.AVITO_MORNING_SPREAD_MIN)
        bot = service.bot_can_reply(chat, now)
        deadline = start + timedelta(minutes=settings.AVITO_ALERT_BOT_MIN if bot else settings.AVITO_ALERT_MANUAL_MIN)
        if bot:
            for t in service.pending_tasks(db, chat, ("think", "send")):
                deadline = max(deadline, t.due_at + timedelta(minutes=5))
        if now < deadline:
            continue
        waited = int((now - chat.last_client_at).total_seconds() // 60)
        last = service.last_dialog_message(chat)
        why = "Бот не ответил — проверьте ключи API и логи (docker compose logs api)." if bot else \
            "Чат ведёте вы — бот в нём молчит."
        _alert(chat, f"Клиент ждёт ответа {waited} мин", [f"«{(last.text if last else '')[:300]}»", why])
        chat.alerted_at = chat.last_client_at
        sent += 1
    db.commit()
    return sent


def _loop():
    last_watch = 0.0
    while True:
        try:
            with SessionLocal() as db:
                run_due(db)
                if time.time() - last_watch >= WATCHDOG_EVERY:
                    watchdog(db)
                    last_watch = time.time()
        except Exception as e:  # noqa: BLE001
            log.exception("worker: %s", e)
        time.sleep(TICK_SECONDS)


def start() -> None:
    if not (settings.AVITO_WORKER_ENABLED and client.configured):
        return
    with SessionLocal() as db:  # задачи, прерванные перезапуском, — снова в очередь
        db.execute(update(m.AvitoTask).where(m.AvitoTask.status == "running").values(status="pending"))
        db.commit()
    threading.Thread(target=_loop, name="avito-worker", daemon=True).start()
