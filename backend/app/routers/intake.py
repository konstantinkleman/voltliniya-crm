"""Автоматический приём заявок из внешних каналов.

Кто шлёт:
- обработчик формы сайта (вместе с уведомлением в Telegram) — с UTM-метками, по ним определяется источник;
- сбор заявок с Профи и других площадок — с явным source и external_ref (id чата или заказа).

Защита: секрет в заголовке X-Intake-Token (INTAKE_TOKEN в .env). Без него приём выключен.

Дубли:
- тот же source + external_ref → та же заявка, ничего нового не создаётся;
- тот же телефон у открытой заявки за последние 90 дней → в заявку пишется «повторное обращение».
"""
import hmac
import re
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..config import settings
from ..db import get_db

router = APIRouter(prefix="/api/intake", tags=["intake"])

REPEAT_WINDOW_DAYS = 90

# utm_source → источник CRM (сравнение без регистра, по вхождению)
UTM_SOURCES = [
    (("yandex", "direct", "ya_direct", "yd"), "site_direct"),
    (("sms",), "sms"),
    (("avito",), "avito"),
    (("maps", "yandex_maps", "ymaps"), "yandex_maps"),
    (("profi",), "profi"),
]
SEARCH_REFERRERS = ("yandex.", "ya.ru", "google.", "go.mail.ru", "bing.com", "duckduckgo.")


class IntakeLead(BaseModel):
    name: str | None = None
    phone: str | None = None
    message: str | None = None          # текст заявки / последнее сообщение чата
    address: str | None = None
    area_m2: Decimal | None = None
    source: str | None = None           # явный источник (profi, avito…); для сайта не нужен
    external_ref: str | None = None     # id чата/заказа во внешней системе
    lead_cost: Decimal | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None
    yclid: str | None = None            # метка клика Директа
    page: str | None = None             # страница сайта, где отправлена форма
    referrer: str | None = None


class IntakeResult(BaseModel):
    lead_id: int
    created: bool
    duplicate: str | None = None        # "external_ref" | "phone"
    source: str


def check_token(x_intake_token: str | None = Header(default=None)) -> None:
    if not settings.INTAKE_TOKEN:
        raise HTTPException(503, "Приём заявок выключен: не задан INTAKE_TOKEN")
    if not x_intake_token or not hmac.compare_digest(x_intake_token, settings.INTAKE_TOKEN):
        raise HTTPException(401, "Неверный токен")


def norm_phone(p: str | None) -> str | None:
    """Последние 10 цифр: +7 911 469-16-70 и 89114691670 — один номер."""
    if not p:
        return None
    d = re.sub(r"\D", "", p)
    return d[-10:] if len(d) >= 10 else (d or None)


def resolve_source(data: IntakeLead) -> str:
    if data.source:
        if data.source not in m.SOURCES:
            raise HTTPException(400, f"Неизвестный источник: {data.source}")
        return data.source
    us = (data.utm_source or "").lower()
    if us:
        for keys, src in UTM_SOURCES:
            if any(k in us for k in keys):
                return src
        return "site_other"
    if data.yclid:
        return "site_direct"
    host = urlparse(data.referrer or "").netloc.lower()
    if host and any(r in host for r in SEARCH_REFERRERS):
        return "site_seo"
    return "site_other"


def utm_text(data: IntakeLead) -> str | None:
    parts = [f"{k}={v}" for k, v in (
        ("utm_source", data.utm_source), ("utm_medium", data.utm_medium), ("utm_campaign", data.utm_campaign),
        ("utm_content", data.utm_content), ("utm_term", data.utm_term), ("yclid", data.yclid),
        ("page", data.page), ("referrer", data.referrer)) if v]
    return "; ".join(parts)[:500] or None


def _activity(db: Session, lead: m.Lead, text: str, kind: str = "message"):
    db.add(m.LeadActivity(lead_id=lead.id, kind=kind, text=text[:4000], user_id=None))


@router.post("/lead", response_model=IntakeResult, dependencies=[Depends(check_token)])
def intake_lead(data: IntakeLead, db: Session = Depends(get_db)):
    if not (data.phone or data.external_ref or data.message):
        raise HTTPException(400, "Нужен телефон, id внешней заявки или текст")
    source = resolve_source(data)
    channel = m.SOURCES[source]

    # 1. та же внешняя заявка уже есть
    if data.external_ref:
        lead = db.scalar(select(m.Lead).where(m.Lead.source == source, m.Lead.external_ref == data.external_ref))
        if lead:
            changed = False
            if data.phone and not lead.phone:
                lead.phone = data.phone; changed = True
            if data.area_m2 and not lead.area_m2:
                lead.area_m2 = data.area_m2; changed = True
            if changed:
                _activity(db, lead, "Дополнены контакты из канала " + channel, "note")
                db.commit()
            return IntakeResult(lead_id=lead.id, created=False, duplicate="external_ref", source=source)

    # 2. повторное обращение по тому же телефону, пока заявка открыта
    phone = norm_phone(data.phone)
    if phone:
        since = datetime.now() - timedelta(days=REPEAT_WINDOW_DAYS)
        open_leads = db.scalars(select(m.Lead).where(
            m.Lead.stage.not_in(["won", "lost"]), m.Lead.phone.is_not(None), m.Lead.created_at >= since)).all()
        same = next((l for l in open_leads if norm_phone(l.phone) == phone), None)
        if same:
            txt = f"Повторное обращение ({channel})"
            if data.message:
                txt += f": {data.message}"
            _activity(db, same, txt)
            db.commit()
            return IntakeResult(lead_id=same.id, created=False, duplicate="phone", source=source)

    # 3. новая заявка
    name = (data.name or "").strip() or (data.phone or "Без имени")
    lead = m.Lead(
        name=name[:200], phone=data.phone, address=data.address, area_m2=data.area_m2,
        source=source, lead_cost=data.lead_cost or Decimal(0),
        note=data.message, external_ref=data.external_ref, utm=utm_text(data),
    )
    db.add(lead)
    db.flush()
    _activity(db, lead, f"Заявка создана автоматически · {channel}", "stage")
    db.commit()
    return IntakeResult(lead_id=lead.id, created=True, source=source)
