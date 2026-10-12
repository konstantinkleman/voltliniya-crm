"""Еженедельный разбор переписок Авито: отчёт директору + черновик новой версии скрипта.

Запускается фоновым потоком из main.py (AVITO_REVIEW_WEEKDAY / AVITO_REVIEW_HOUR_MSK) или вручную через POST /api/avito/review.
Черновик не включается сам: директор активирует его ссылкой из Telegram или в настройках CRM.
"""
import hashlib
import hmac
import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..config import settings
from ..db import SessionLocal
from . import agent
from .notify import esc, telegram
from .service import active_script, new_script_version

log = logging.getLogger("avito.review")
MSK = timezone(timedelta(hours=3))


def apply_token(script_id: int) -> str:
    return hmac.new(settings.JWT_SECRET.encode(), f"script-apply-{script_id}".encode(), hashlib.sha256).hexdigest()[:32]


def _transcripts(db: Session, since: datetime) -> tuple[str, int]:
    chats = db.scalars(select(m.AvitoChat).where(m.AvitoChat.last_message_at >= since).order_by(m.AvitoChat.id)).all()
    parts = []
    for c in chats:
        lead = c.lead
        head = f"### Чат {c.id} · {c.item_title or 'объявление'} · квалификация: {c.qualified} · режим: {c.mode}"
        if lead:
            head += f" · этап заявки: {m.LEAD_STAGE_NAMES.get(lead.stage, lead.stage)}"
            if lead.lost_reason:
                head += f" ({lead.lost_reason})"
        lines = [head]
        for msg in c.messages[-60:]:
            who = {"client": "Клиент", "bot": "Бот", "director": "Директор", "system": "Система"}.get(msg.author, msg.author)
            lines.append(f"{who}: {msg.text}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts), len(chats)


def run_review(db: Session, days: int = 7) -> m.AvitoReview | None:
    if not settings.ANTHROPIC_API_KEY:
        log.info("review: нет ANTHROPIC_API_KEY")
        return None
    since = datetime.utcnow() - timedelta(days=days)
    transcripts, n = _transcripts(db, since)
    if n == 0:
        telegram("📊 Разбор чатов Авито за неделю: переписок не было.")
        return None
    script = active_script(db)
    res = agent.review(script.text, transcripts)
    if not res:
        telegram("📊 Разбор чатов Авито: модель не вернула отчёт, повторю на следующей неделе.")
        return None
    draft = None
    if res.get("new_script") and res["new_script"].strip() != script.text.strip():
        draft = new_script_version(db, res["new_script"], note=res.get("changes"), created_by="review", activate=False)
    rev = m.AvitoReview(period_from=(date.today() - timedelta(days=days)), period_to=date.today(),
                        report=res.get("report", ""), draft_script_id=draft.id if draft else None)
    db.add(rev)
    db.commit()
    db.refresh(rev)

    text = f"<b>📊 Разбор чатов Авито за {days} дн. ({n} чатов)</b>\n\n{esc(res.get('report', ''))[:2500]}"
    if draft:
        url = f"{settings.PUBLIC_URL.rstrip('/')}/api/avito/script/{draft.id}/apply/{apply_token(draft.id)}"
        text += f"\n\n<b>Предложена версия скрипта {draft.version}</b>\n{esc(res.get('changes', ''))[:800]}\n\nВключить: {url}"
    else:
        text += "\n\nСкрипт менять не предлагаю."
    telegram(text)
    return rev


def _next_run(now: datetime) -> datetime:
    """Ближайший момент запуска по Москве."""
    target_wd, target_h = settings.AVITO_REVIEW_WEEKDAY, settings.AVITO_REVIEW_HOUR_MSK
    local = now.astimezone(MSK)
    cand = local.replace(hour=target_h, minute=5, second=0, microsecond=0)
    days_ahead = (target_wd - local.weekday()) % 7
    cand += timedelta(days=days_ahead)
    if cand <= local:
        cand += timedelta(days=7)
    return cand


def _loop():
    while True:
        try:
            nxt = _next_run(datetime.now(timezone.utc))
            wait = max(60, (nxt - datetime.now(MSK)).total_seconds())
            log.info("review: следующий запуск %s (через %.0f мин)", nxt.isoformat(), wait / 60)
            time.sleep(wait)
            with SessionLocal() as db:
                run_review(db)
        except Exception as e:  # noqa: BLE001
            log.exception("review loop: %s", e)
            time.sleep(600)


def start_scheduler():
    if not (settings.AVITO_CLIENT_ID and settings.ANTHROPIC_API_KEY):
        return
    t = threading.Thread(target=_loop, name="avito-review", daemon=True)
    t.start()
