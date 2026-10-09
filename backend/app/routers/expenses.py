from datetime import date

from fastapi import APIRouter, Depends, HTTPException
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
    return o


@router.get("", response_model=list[ExpenseOut])
def list_expenses(month: str | None = None, category: str | None = None,
                  _: m.User = Depends(director), db: Session = Depends(get_db)):
    qs = select(m.Expense).order_by(m.Expense.date.desc(), m.Expense.id.desc())
    if month:
        y, mo = map(int, month.split("-"))
        start = date(y, mo, 1)
        end = date(y + mo // 12, mo % 12 + 1, 1)
        qs = qs.where(m.Expense.date >= start, m.Expense.date < end)
    if category:
        qs = qs.where(m.Expense.category == category)
    return [_out(e) for e in db.scalars(qs).all()]


@router.post("", response_model=ExpenseOut)
def create_expense(data: ExpenseIn, user: m.User = Depends(director), db: Session = Depends(get_db)):
    cat = m.EXPENSE_CATEGORIES.get(data.category)
    if not cat:
        raise HTTPException(400, "Неизвестная категория")
    if data.category == "salary" and not data.foreman_id:
        raise HTTPException(400, "Для зарплаты укажите прораба")
    e = m.Expense(**data.model_dump(), channel=cat[2], user_id=user.id)
    if e.category == "salary" and not e.period:
        e.period = e.date.strftime("%Y-%m")
    db.add(e)
    db.commit()
    db.refresh(e)
    return _out(e)


@router.delete("/{eid}")
def delete_expense(eid: int, _: m.User = Depends(director), db: Session = Depends(get_db)):
    e = db.get(m.Expense, eid)
    if e:
        db.delete(e)
        db.commit()
    return {"ok": True}
