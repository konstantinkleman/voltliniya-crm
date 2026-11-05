from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..auth import director
from ..db import get_db
from ..schemas import ExpenseIn, ExpenseOut

router = APIRouter(prefix="/api/expenses", tags=["expenses"])


def _out(e: m.Expense) -> ExpenseOut:
    o = ExpenseOut.model_validate(e)
    o.foreman_name = e.foreman.name if e.foreman else None
    o.crew_name = e.crew.name if e.crew else None
    return o


@router.get("", response_model=list[ExpenseOut])
def list_expenses(month: str | None = None, category: str | None = None, crew_id: int | None = None,
                  _: m.User = Depends(director), db: Session = Depends(get_db)):
    qs = select(m.Expense).order_by(m.Expense.date.desc(), m.Expense.id.desc())
    if month:
        y, mo = map(int, month.split("-"))
        start = date(y, mo, 1)
        end = date(y + mo // 12, mo % 12 + 1, 1)
        qs = qs.where(m.Expense.date >= start, m.Expense.date < end)
    if category:
        qs = qs.where(m.Expense.category == category)
    if crew_id:
        qs = qs.where(m.Expense.crew_id == crew_id)
    return [_out(e) for e in db.scalars(qs).all()]


@router.post("", response_model=ExpenseOut)
def create_expense(data: ExpenseIn, user: m.User = Depends(director), db: Session = Depends(get_db)):
    cat = m.EXPENSE_CATEGORIES.get(data.category)
    if not cat:
        raise HTTPException(400, "Неизвестная категория")
    if data.category == "salary" and not data.foreman_id:
        raise HTTPException(400, "Для зарплаты укажите прораба")
    if data.crew_id and not db.get(m.Crew, data.crew_id):
        raise HTTPException(400, "Бригада не найдена")
    e = m.Expense(**data.model_dump(), channel=cat[2], user_id=user.id)
    if e.category == "salary" and not e.period:
        e.period = e.date.strftime("%Y-%m")
    db.add(e)
    db.commit()
    db.refresh(e)
    return _out(e)


@router.get("/autoload")
def autoload_status(_: m.User = Depends(director)):
    """Состояние автозагрузки рекламных расходов: какие каналы подключены, когда и чем закончилась загрузка."""
    from .. import adspend
    ch = {}
    for key, (name, configured, _fn) in adspend.CHANNELS.items():
        ch[key] = {"name": name, "configured": configured(), **adspend.status["channels"].get(key, {})}
    return {"last_run": adspend.status["last_run"], "running": adspend._lock.locked(), "channels": ch,
            "every_hours": adspend.SYNC_EVERY_SECONDS // 3600, "days": adspend.SYNC_DAYS}


@router.post("/autoload")
def autoload_run(days: int = 7, _: m.User = Depends(director)):
    """Загрузить расходы сейчас (в фоне — Директ может строить отчёт до нескольких минут)."""
    import threading
    from .. import adspend
    days = max(1, min(days, 180))
    if not adspend._lock.locked():
        threading.Thread(target=adspend.sync_all, args=(days,), daemon=True).start()
    return {"ok": True}


class ExpenseUpsert(BaseModel):
    date: date
    amount: Decimal
    category: str
    external_ref: str
    note: str | None = None


@router.post("/upsert")
def upsert_expense(data: ExpenseUpsert, _: m.User = Depends(director), db: Session = Depends(get_db)):
    """Создать или обновить расход по ключу источника — для сборщиков, которые работают из браузера директора
    (Профи: месячная сумма откликов за вычетом возвратов). Повтор с тем же external_ref обновляет сумму."""
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


@router.delete("/{eid}")
def delete_expense(eid: int, _: m.User = Depends(director), db: Session = Depends(get_db)):
    e = db.get(m.Expense, eid)
    if e:
        db.delete(e)
        db.commit()
    return {"ok": True}
