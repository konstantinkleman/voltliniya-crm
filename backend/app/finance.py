"""Расчёт денег объекта. Все правила в одном месте."""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import EXPENSE_CATEGORIES, Expense, Lead, User, WorkObject
from .schemas import Finance

Q = Decimal("0.01")


def q(x) -> Decimal:
    return Decimal(x or 0).quantize(Q)


def deal_month(o: WorkObject, lead: Lead | None) -> tuple[int, int]:
    d: date | None = None
    if lead and lead.won_at:
        d = lead.won_at
    d = d or o.start_date or (o.created_at.date() if o.created_at else date.today())
    return d.year, d.month


def _month_bounds(y: int, m: int) -> tuple[date, date]:
    start = date(y, m, 1)
    end = date(y + (m // 12), (m % 12) + 1, 1)
    return start, end


def _objects_in_month(db: Session, y: int, m: int) -> list[WorkObject]:
    start, end = _month_bounds(y, m)
    objs = db.scalars(select(WorkObject)).all()
    out = []
    for o in objs:
        lead = db.scalar(select(Lead).where(Lead.object_id == o.id))
        yy, mm = deal_month(o, lead)
        if (yy, mm) == (y, m):
            out.append(o)
    return out


def client_cost(db: Session, o: WorkObject, lead: Lead | None) -> Decimal:
    """Стоимость клиента по каналу за месяц сделки: расходы канала / сделок канала + общий маркетинг / всех сделок."""
    if not o.source:
        return Decimal(0)
    y, m = deal_month(o, lead)
    start, end = _month_bounds(y, m)
    exps = db.scalars(select(Expense).where(Expense.date >= start, Expense.date < end)).all()
    channel_spent = Decimal(0)
    general_spent = Decimal(0)
    for e in exps:
        cat = EXPENSE_CATEGORIES.get(e.category)
        if not cat:
            continue
        _, kind, channel = cat
        if kind == "channel" and (e.channel or channel) == o.source:
            channel_spent += e.amount
        elif kind == "marketing":
            general_spent += e.amount
    deals = _objects_in_month(db, y, m)
    deals_channel = [d for d in deals if d.source == o.source]
    cost = Decimal(0)
    if deals_channel:
        cost += channel_spent / len(deals_channel)
    if deals:
        cost += general_spent / len(deals)
    # если расходов по каналу ещё не внесено, берём хотя бы стоимость самого лида
    if channel_spent == 0 and lead and lead.lead_cost:
        cost += lead.lead_cost
    return q(cost)


def foreman_share(db: Session, o: WorkObject, lead: Lead | None) -> tuple[Decimal | None, int | None]:
    """Доля зарплаты прораба: его месячная зарплата / число его объектов в месяце сделки."""
    fid = o.salary_foreman_id or o.foreman_id
    if not fid:
        return None, None
    foreman = db.get(User, fid)
    if not foreman or not foreman.salary:
        return None, None
    y, m = deal_month(o, lead)
    mine = [d for d in _objects_in_month(db, y, m) if (d.salary_foreman_id or d.foreman_id) == fid]
    n = max(len(mine), 1)
    return q(foreman.salary / n), n


def compute(db: Session, o: WorkObject, full: bool = True) -> Finance:
    lead = db.scalar(select(Lead).where(Lead.object_id == o.id))
    share = Decimal(str(settings.CREW_SHARE))
    extra = sum((e.amount for e in o.extra_works), Decimal(0))
    works_base = q(o.works_sum + extra)
    total = q(works_base + o.materials_client_sum)
    received = q(sum((p.amount for p in o.payments), Decimal(0)))
    crew_plan = q(works_base * share)
    crew_paid = q(sum((p.amount for p in o.payouts), Decimal(0)))
    f = Finance(
        works_sum=q(o.works_sum), extra_works_sum=q(extra), works_base=works_base,
        materials_client_sum=q(o.materials_client_sum), contract_total=total,
        received=received, receivable=q(total - received),
        crew_share=share, crew_plan=crew_plan, crew_paid=crew_paid, crew_due=q(crew_plan - crew_paid),
        crew_share_actual=(q(crew_paid / works_base) if works_base and crew_paid else None),
    )
    if not full:
        return f
    mat_cost = q(sum((m.cost_sum for m in o.materials), Decimal(0)))
    fs, n = foreman_share(db, o, lead)
    cc = client_cost(db, o, lead)
    profit = q(total - mat_cost - crew_plan - (fs or 0) - cc)
    f.materials_cost = mat_cost
    f.materials_markup = q(o.materials_client_sum - mat_cost)
    f.foreman_share = fs
    f.foreman_objects_in_month = n
    f.client_cost = cc
    f.profit = profit
    f.margin = (q(profit / total * 100) if total else None)
    return f
