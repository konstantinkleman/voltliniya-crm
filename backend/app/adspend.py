"""Автоматическая загрузка рекламных расходов в «Расходы» CRM.

Каналы с официальным доступом — CRM забирает сама раз в 3 часа (текущий месяц целиком):
- Яндекс Директ: API Reports (CUSTOM_REPORT: Date × AdNetworkType × Cost), поиск и РСЯ — отдельными строками.
  Нужен OAuth-токен с доступом к API Директа: YANDEX_DIRECT_TOKEN (+ YANDEX_DIRECT_LOGIN для агентского аккаунта).
- Авито: POST /stats/v2/accounts/{user_id}/spendings (расходы профиля по дням).
  Нужны AVITO_CLIENT_ID / AVITO_CLIENT_SECRET (те же, что для бота Авито).

Каналы без API (Профи, SMS-рассылки операторов) присылают сборщики через POST /api/intake/expense.

В «Расходах» — одна строка на канал в месяц (у Директа — поиск и РСЯ отдельно), сумма обновляется при каждой загрузке:
external_ref «direct:2026-11:search», «avito:2026-11». Повторная загрузка обновляет сумму, а не создаёт дубль.
"""
import logging
import threading
import time
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .config import settings
from .db import SessionLocal

log = logging.getLogger("adspend")

SYNC_DAYS = 7               # если месяц начался меньше недели назад — дозагружаем и прошлый (расходы уточняются задним числом)
SYNC_EVERY_SECONDS = 3 * 3600
DIRECT_URL = "https://api.direct.yandex.com/json/v5/reports"
AVITO_BASE = "https://api.avito.ru"

# состояние последнего запуска — для страницы настроек
status: dict = {"last_run": None, "channels": {}}
_lock = threading.Lock()


def _dec(v) -> Decimal | None:
    try:
        d = Decimal(str(v).replace(",", ".").replace(" ", ""))
        return d if d >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def upsert_expense(db: Session, *, ref: str, day: date, amount: Decimal, category: str, note: str) -> str:
    """Создать или обновить автоматический расход. Возвращает created | updated | same | skipped."""
    cat = m.EXPENSE_CATEGORIES.get(category)
    if not cat:
        raise ValueError(f"Неизвестная категория расхода: {category}")
    amount = Decimal(amount).quantize(Decimal("0.01"))
    e = db.scalar(select(m.Expense).where(m.Expense.external_ref == ref))
    if e:
        if e.amount == amount and e.date == day:
            return "same"
        e.amount, e.date, e.note = amount, day, note
        return "updated"
    if amount == 0:
        return "skipped"           # нулевые дни не засоряют список
    db.add(m.Expense(date=day, amount=amount, category=category, channel=cat[2], note=note, external_ref=ref))
    return "created"


# ---------- Яндекс Директ ----------
def direct_configured() -> bool:
    return bool(settings.YANDEX_DIRECT_TOKEN)


def fetch_direct(date_from: date, date_to: date) -> list[tuple[date, str, Decimal]]:
    """[(день, 'search'|'rsya', сумма с НДС)] из отчёта Директа."""
    headers = {
        "Authorization": f"Bearer {settings.YANDEX_DIRECT_TOKEN}",
        "Accept-Language": "ru",
        "processingMode": "auto",
        "returnMoneyInMicros": "false",
        "skipReportHeader": "true",
        "skipReportSummary": "true",
    }
    if settings.YANDEX_DIRECT_LOGIN:
        headers["Client-Login"] = settings.YANDEX_DIRECT_LOGIN
    body = {"params": {
        "SelectionCriteria": {"DateFrom": date_from.isoformat(), "DateTo": date_to.isoformat()},
        "FieldNames": ["Date", "AdNetworkType", "Cost"],
        # имя отчёта должно быть уникальным для набора параметров — добавляем время
        "ReportName": f"crm-cost-{date_from}-{date_to}-{int(time.time())}",
        "ReportType": "CUSTOM_REPORT",
        "DateRangeType": "CUSTOM_DATE",
        "Format": "TSV",
        "IncludeVAT": "YES",          # ВольтЛиния не платит НДС — реальный расход с НДС
        "IncludeDiscount": "NO",
    }}
    for _ in range(12):            # отчёт может строиться офлайн: 201/202 → ждём retryIn
        r = httpx.post(DIRECT_URL, json=body, headers=headers, timeout=60)
        if r.status_code == 200:
            break
        if r.status_code in (201, 202):
            time.sleep(min(int(r.headers.get("retryIn", "5") or 5), 30))
            continue
        raise RuntimeError(f"Директ ответил {r.status_code}: {r.text[:300]}")
    else:
        raise RuntimeError("Директ не успел построить отчёт — попробуем в следующий раз")
    out = []
    lines = [l for l in r.text.splitlines() if l.strip()]
    for line in lines[1:]:          # первая строка — названия колонок
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        try:
            day = date.fromisoformat(parts[0])
        except ValueError:
            continue
        net = "rsya" if parts[1].upper() == "AD_NETWORK" else "search"
        cost = _dec(parts[2])
        if cost is not None:
            out.append((day, net, cost))
    return out


MONTHS_RU = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]


def _by_month(rows, key=lambda r: ()) -> dict:
    """Суммы по дням → суммы по месяцам: {(год-месяц, *ключ): (сумма, последний день)}.
    В «Расходах» одна строка на канал в месяц — обновляется при каждой загрузке."""
    agg: dict = {}
    for day, *rest in rows:
        amt = rest[-1]
        k = (f"{day:%Y-%m}", *key(rest))
        s, last = agg.get(k, (Decimal(0), day))
        agg[k] = (s + amt, max(last, day))
    return agg


def _month_note(label: str, last: date) -> str:
    return f"{label} · {MONTHS_RU[last.month - 1]}, по {last:%d.%m} · автозагрузка"


def sync_direct(db: Session, date_from: date, date_to: date) -> dict:
    rows = fetch_direct(date_from, date_to)
    res = {"created": 0, "updated": 0}
    for (mon, net), (cost, last) in sorted(_by_month(rows, key=lambda r: (r[0],)).items()):
        cat = "rsya" if net == "rsya" else "direct"
        what = upsert_expense(db, ref=f"direct:{mon}:{net}", day=last, amount=cost, category=cat,
                              note=_month_note("Директ · " + ("РСЯ" if net == "rsya" else "поиск"), last))
        if what in res:
            res[what] += 1
    return res


# ---------- Авито ----------
def avito_configured() -> bool:
    return bool(settings.AVITO_CLIENT_ID and settings.AVITO_CLIENT_SECRET)


def _avito_token() -> str:
    r = httpx.post(f"{AVITO_BASE}/token", data={"grant_type": "client_credentials", "client_id": settings.AVITO_CLIENT_ID,
                                                "client_secret": settings.AVITO_CLIENT_SECRET}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"Авито не выдал токен: {r.status_code} {r.text[:200]}")
    return r.json()["access_token"]


def parse_avito_spendings(data) -> list[tuple[date, Decimal]]:
    """Ответ Авито → [(день, сумма)]. Формат ответа документирован скупо, поэтому разбираем гибко:
    ищем любые объекты с датой и суммой; если внутри есть разбивка по типам — берём «all», иначе складываем."""
    out: dict[date, Decimal] = {}

    def as_day(v):
        if not isinstance(v, str):
            return None
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None

    def amount_of(o):
        for k in ("value", "amount", "total", "sum", "spending", "spendings"):
            if k in o and not isinstance(o[k], (dict, list)):
                return _dec(o[k])
        return None

    def walk(o):
        if isinstance(o, list):
            for x in o:
                walk(x)
            return
        if not isinstance(o, dict):
            return
        day = next((as_day(o[k]) for k in ("date", "dateFrom", "day", "period") if k in o and as_day(o[k])), None)
        if day:
            amt = amount_of(o)
            if amt is None:
                # {"date": ..., "spendings": [{"slug": "all", "value": ...}, ...]}
                inner = next((o[k] for k in ("spendings", "values", "items", "types") if isinstance(o.get(k), list)), None)
                if inner:
                    vals = [(str(x.get("slug") or x.get("type") or x.get("name") or ""), amount_of(x)) for x in inner if isinstance(x, dict)]
                    alls = [v for s, v in vals if s == "all" and v is not None]
                    amt = alls[0] if alls else sum((v for _, v in vals if v is not None), Decimal(0))
            if amt is not None:
                out[day] = out.get(day, Decimal(0)) + amt
                return
        for v in o.values():
            walk(v)

    walk(data)
    return sorted(out.items())


def fetch_avito(date_from: date, date_to: date):
    tok = _avito_token()
    h = {"Authorization": f"Bearer {tok}"}
    me = httpx.get(f"{AVITO_BASE}/core/v1/accounts/self", headers=h, timeout=20)
    if me.status_code != 200:
        raise RuntimeError(f"Авито: профиль {me.status_code} {me.text[:200]}")
    uid = me.json()["id"]
    r = httpx.post(f"{AVITO_BASE}/stats/v2/accounts/{uid}/spendings", headers=h, timeout=30,
                   json={"dateFrom": date_from.isoformat(), "dateTo": date_to.isoformat(), "grouping": "day", "spendingTypes": ["all"]})
    if r.status_code != 200:
        raise RuntimeError(f"Авито: расходы {r.status_code} {r.text[:300]}")
    return r.json()


def sync_avito(db: Session, date_from: date, date_to: date) -> dict:
    raw = fetch_avito(date_from, date_to)
    rows = parse_avito_spendings(raw)
    if not rows and raw:
        status["channels"].setdefault("avito", {})["raw_sample"] = str(raw)[:500]
    res = {"created": 0, "updated": 0}
    for (mon,), (amt, last) in sorted(_by_month(rows).items()):
        what = upsert_expense(db, ref=f"avito:{mon}", day=last, amount=amt, category="avito", note=_month_note("Авито", last))
        if what in res:
            res[what] += 1
    return res


# ---------- запуск ----------
CHANNELS = {
    "direct": ("Яндекс Директ", direct_configured, sync_direct),
    "avito": ("Авито", avito_configured, sync_avito),
}


def sync_all(days: int = SYNC_DAYS) -> dict:
    """Загрузить расходы всех настроенных каналов за последние days дней. Ошибка одного канала не мешает другим."""
    if not _lock.acquire(blocking=False):
        return status
    try:
        today = date.today()
        # месяц пересчитывается целиком (одна строка на канал в месяц), а первые дни месяца — ещё и прошлый
        date_from, date_to = (today - timedelta(days=days)).replace(day=1), today
        for key, (name, configured, fn) in CHANNELS.items():
            st = {"name": name, "configured": configured(), "at": datetime.now().isoformat(timespec="seconds")}
            if st["configured"]:
                with SessionLocal() as db:
                    try:
                        st.update(fn(db, date_from, date_to), ok=True)
                        db.commit()
                    except Exception as e:  # noqa: BLE001 — один канал не должен ронять остальные
                        db.rollback()
                        st.update(ok=False, error=str(e)[:400])
                        log.warning("adspend %s: %s", key, e)
            status["channels"][key] = {**status["channels"].get(key, {}), **st}
        status["last_run"] = datetime.now().isoformat(timespec="seconds")
        return status
    finally:
        _lock.release()


def start_background() -> None:
    """Фоновая загрузка: сразу после старта (через минуту) и затем раз в SYNC_EVERY_SECONDS."""
    if not (direct_configured() or avito_configured()):
        return

    def loop():
        time.sleep(60)
        while True:
            try:
                sync_all()
            except Exception as e:  # noqa: BLE001
                log.warning("adspend loop: %s", e)
            time.sleep(SYNC_EVERY_SECONDS)

    threading.Thread(target=loop, name="adspend", daemon=True).start()
