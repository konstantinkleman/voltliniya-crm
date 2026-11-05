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
from datetime import date as date_, datetime, timedelta
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
# РСЯ (рекламная сеть Яндекса) отличается от поиска не utm_source, а типом площадки: подстановка Директа
# {source_type} = context (РСЯ) / search (поиск). Плюс страхуемся по utm_medium/utm_campaign, если метки ставили вручную.
RSYA_MARKS = ("context", "rsya", "rsy", "рся", "network", "display", "cpm")


def is_rsya(data) -> bool:
    st = (getattr(data, "source_type", None) or "").lower()
    if st:
        return st == "context"
    hay = " ".join((getattr(data, k, None) or "") for k in ("utm_medium", "utm_campaign", "utm_content")).lower()
    return any(m in hay for m in RSYA_MARKS)


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
    source_type: str | None = None      # подстановка Директа {source_type}: search — поиск, context — РСЯ
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
                return "site_rsya" if src == "site_direct" and is_rsya(data) else src
        return "site_other"
    if data.yclid:
        return "site_rsya" if is_rsya(data) else "site_direct"
    host = urlparse(data.referrer or "").netloc.lower()
    if host and any(r in host for r in SEARCH_REFERRERS):
        return "site_seo"
    return "site_other"


def utm_text(data: IntakeLead) -> str | None:
    parts = [f"{k}={v}" for k, v in (
        ("utm_source", data.utm_source), ("utm_medium", data.utm_medium), ("utm_campaign", data.utm_campaign),
        ("utm_content", data.utm_content), ("utm_term", data.utm_term), ("source_type", data.source_type), ("yclid", data.yclid),
        ("page", data.page), ("referrer", data.referrer)) if v]
    return "; ".join(parts)[:500] or None


def _activity(db: Session, lead: m.Lead, text: str, kind: str = "message"):
    db.add(m.LeadActivity(lead_id=lead.id, kind=kind, text=text[:4000], user_id=None))


@router.post("/lead", response_model=IntakeResult, dependencies=[Depends(check_token)])
def intake_lead(data: IntakeLead, db: Session = Depends(get_db)):
    return _intake(data, db)


class SiteLead(BaseModel):
    """Форма сайта. Без токена: форма и так публична, поэтому принимаем только её поля —
    источник определяется по меткам, стоимость лида и внешний id задать нельзя."""
    name: str | None = None
    phone: str
    message: str | None = None
    area_m2: Decimal | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None
    source_type: str | None = None
    yclid: str | None = None
    page: str | None = None
    referrer: str | None = None
    website: str | None = None          # ловушка для ботов: настоящая форма шлёт пустым


SITE_HOURLY_LIMIT = 30   # новых заявок с сайта в час — выше этого похоже на спам-атаку


@router.post("/site", response_model=IntakeResult)
def intake_site(data: SiteLead, db: Session = Depends(get_db)):
    if data.website:
        raise HTTPException(400, "Отклонено")
    digits = re.sub(r"\D", "", data.phone or "")
    if not 10 <= len(digits) <= 11:
        raise HTTPException(400, "Неверный телефон")
    since = datetime.now() - timedelta(hours=1)
    recent = db.scalars(select(m.Lead).where(m.Lead.created_at >= since, m.Lead.source.like("site%"))).all()
    if len(recent) >= SITE_HOURLY_LIMIT:
        raise HTTPException(429, "Слишком много заявок, попробуйте позже")
    lead = IntakeLead(**{k: (v[:4000] if k == "message" else v[:500]) if isinstance(v, str) else v
                         for k, v in data.model_dump(exclude={"website"}).items()})
    res = _intake(lead, db)
    return res


def _intake(data: IntakeLead, db: Session) -> IntakeResult:
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


# ---------- расходы из каналов без API (Профи, SMS-рассылки) ----------
class IntakeExpense(BaseModel):
    date: date_
    amount: Decimal
    category: str                 # profi | sms | avito | direct | rsya | ...
    external_ref: str             # уникальный ключ у источника: «profi:<id отклика>», «sms:<id рассылки>»
    note: str | None = None


@router.post("/expense", dependencies=[Depends(check_token)])
def intake_expense(data: IntakeExpense, db: Session = Depends(get_db)):
    """Создать или обновить расход. Повторная отправка с тем же external_ref обновляет сумму, а не дублирует."""
    from .. import adspend
    cat = m.EXPENSE_CATEGORIES.get(data.category)
    if not cat or cat[1] != "channel":
        raise HTTPException(400, "Категория должна быть рекламным каналом")
    if data.amount < 0:
        raise HTTPException(400, "Сумма не может быть отрицательной")
    ref = data.external_ref.strip()[:120]
    if not ref:
        raise HTTPException(400, "Нужен external_ref")
    what = adspend.upsert_expense(db, ref=ref, day=data.date, amount=data.amount, category=data.category,
                                  note=(data.note or f"{cat[0]} · автозагрузка")[:500])
    db.commit()
    return {"ok": True, "result": what}
