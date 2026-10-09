from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..auth import director
from ..db import get_db
from ..finance import compute, deal_month, q
from ..schemas import ChannelStat, ForemanStat

router = APIRouter(prefix="/api/stats", tags=["stats"])


def _bounds(month: str | None):
    if month:
        y, mo = map(int, month.split("-"))
    else:
        t = date.today()
        y, mo = t.year, t.month
    return (y, mo), date(y, mo, 1), date(y + mo // 12, mo % 12 + 1, 1)


@router.get("/channels", response_model=list[ChannelStat])
def channels(month: str | None = None, _: m.User = Depends(director), db: Session = Depends(get_db)):
    (y, mo), start, end = _bounds(month)
    leads = db.scalars(select(m.Lead).where(m.Lead.created_at >= datetime(start.year, start.month, 1),
                                            m.Lead.created_at < datetime(end.year, end.month, 1))).all()
    exps = db.scalars(select(m.Expense).where(m.Expense.date >= start, m.Expense.date < end)).all()
    objs = [o for o in db.scalars(select(m.WorkObject)).all()
            if deal_month(o, db.scalar(select(m.Lead).where(m.Lead.object_id == o.id))) == (y, mo)]
    general = sum((e.amount for e in exps if m.EXPENSE_CATEGORIES.get(e.category, (0, "", 0))[1] == "marketing"), Decimal(0))
    deals_all = len(objs) or 0
    out = []
    order = ["new", "contacted", "measure", "offer_sent", "won", "lost"]
    for src, name in m.SOURCES.items():
        ls = [l for l in leads if l.source == src]
        os_ = [o for o in objs if o.source == src]
        if not ls and not os_:
            continue
        spent = sum((e.amount for e in exps if (e.channel == src)), Decimal(0))
        # лиды без внесённого расхода по каналу считаем по их стоимости
        if spent == 0:
            spent = sum((l.lead_cost for l in ls), Decimal(0))
        if deals_all:
            spent += general * len(os_) / deals_all
        reached = lambda st: sum(1 for l in ls if order.index(l.stage) >= order.index(st) and l.stage != "lost")  # noqa: E731
        fins = [compute(db, o) for o in os_]
        revenue = sum((f.contract_total for f in fins), Decimal(0))
        profit = sum((f.profit or 0 for f in fins), Decimal(0))
        out.append(ChannelStat(
            source=src, name=name, spent=q(spent), leads=len(ls),
            contacted=reached("contacted"), measured=reached("measure"), offered=reached("offer_sent"),
            won=len(os_), lost=sum(1 for l in ls if l.stage == "lost"),
            cost_per_lead=q(spent / len(ls)) if ls else None,
            cost_per_client=q(spent / len(os_)) if os_ else None,
            revenue=q(revenue), profit=q(profit), avg_check=q(revenue / len(os_)) if os_ else None,
        ))
    return out


@router.get("/foremen", response_model=list[ForemanStat])
def foremen(month: str | None = None, _: m.User = Depends(director), db: Session = Depends(get_db)):
    (y, mo), start, end = _bounds(month)
    users = db.scalars(select(m.User).where(m.User.is_foreman == True)).all()  # noqa: E712
    out = []
    for u in users:
        objs = db.scalars(select(m.WorkObject).where(m.WorkObject.foreman_id == u.id)).all()
        in_month = [o for o in objs if deal_month(o, db.scalar(select(m.Lead).where(m.Lead.object_id == o.id))) == (y, mo)]
        fins = [compute(db, o, full=False) for o in objs]
        accrued = sum((f.crew_plan for f in fins), Decimal(0))
        paid = sum((f.crew_paid for f in fins), Decimal(0))
        salary_paid = sum((e.amount for e in db.scalars(select(m.Expense).where(
            m.Expense.category == "salary", m.Expense.foreman_id == u.id, m.Expense.date >= start, m.Expense.date < end)).all()), Decimal(0))
        out.append(ForemanStat(
            id=u.id, name=u.name, salary=u.salary, objects_total=len(objs), objects_in_month=len(in_month),
            salary_per_object=q(u.salary / len(in_month)) if (u.salary and in_month) else None,
            crew_accrued=q(accrued), crew_paid=q(paid), crew_due=q(accrued - paid), salary_paid=q(salary_paid),
        ))
    return out


@router.get("/summary")
def summary(month: str | None = None, _: m.User = Depends(director), db: Session = Depends(get_db)):
    (y, mo), start, end = _bounds(month)
    received = sum((p.amount for p in db.scalars(select(m.Payment).where(m.Payment.date >= start, m.Payment.date < end)).all()), Decimal(0))
    payouts = sum((p.amount for p in db.scalars(select(m.CrewPayout).where(m.CrewPayout.date >= start, m.CrewPayout.date < end)).all()), Decimal(0))
    materials = sum((l.cost_sum for l in db.scalars(select(m.MaterialLine).where(m.MaterialLine.date >= start, m.MaterialLine.date < end)).all()), Decimal(0))
    exps = db.scalars(select(m.Expense).where(m.Expense.date >= start, m.Expense.date < end)).all()
    by_type = {"channel": Decimal(0), "marketing": Decimal(0), "staff": Decimal(0), "operating": Decimal(0)}
    for e in exps:
        t = m.EXPENSE_CATEGORIES.get(e.category, (None, "operating", None))[1]
        by_type[t] += e.amount
    objs = db.scalars(select(m.WorkObject)).all()
    active = [o for o in objs if o.stage not in ("act", "warranty")]
    receivable = sum((compute(db, o, full=False).receivable for o in active), Decimal(0))
    fins_all = [compute(db, o) for o in objs]
    crew_due = sum((f.crew_due for f in fins_all), Decimal(0))
    result = received - materials - payouts - by_type["staff"] - by_type["channel"] - by_type["marketing"] - by_type["operating"]
    return {
        "month": f"{y}-{mo:02d}",
        "received": q(received), "materials": q(materials), "crew_payouts": q(payouts),
        "staff": q(by_type["staff"]), "marketing": q(by_type["channel"] + by_type["marketing"]), "operating": q(by_type["operating"]),
        "result": q(result),
        "receivable": q(receivable), "crew_due": q(crew_due),
        "objects_active": len(active), "objects_total": len(objs),
        "avg_margin": q(sum((f.margin or 0 for f in fins_all), Decimal(0)) / len(fins_all)) if fins_all else None,
    }
