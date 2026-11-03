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
        salary_objs = db.scalars(select(m.WorkObject).where(m.WorkObject.salary_foreman_id == u.id)).all()
        in_month = [o for o in salary_objs if deal_month(o, db.scalar(select(m.Lead).where(m.Lead.object_id == o.id))) == (y, mo)]
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


DONE_STAGES = ("act", "warranty")


def closed_month(o: m.WorkObject) -> tuple[int, int] | None:
    """Месяц сдачи: дата «Сдача» объекта, иначе — когда этап стал «Акт подписан» по журналу этапов. None — объект ещё в работе."""
    if o.stage not in DONE_STAGES:
        return None
    d = o.end_date
    if not d:
        for lg in o.stage_log:
            if lg.stage in DONE_STAGES:
                d = lg.created_at.date(); break
    d = d or date.today()
    return d.year, d.month


def _agg(db: Session, objs: list[m.WorkObject], crew_id: int | None = None, cache: dict | None = None) -> dict:
    """Финансовый итог по набору объектов для одного монтажника (бригады): его доля и что осталось компании.
    Если на объекте несколько монтажников, деньги объекта (работы, материалы, прибыль) делятся пропорционально
    их долям — так общий итог по всем не задваивается. crew_id=None — объекты без монтажника, целиком."""
    cache = cache if cache is not None else {}
    rows = []
    for o in objs:
        f = cache.get(o.id) or cache.setdefault(o.id, compute(db, o))
        if crew_id is None:
            share, frac, paid, n_crews = f.crew_plan, Decimal(1), f.crew_paid, 1
        else:
            sh = next((x for x in f.crews if x.crew_id == crew_id), None)
            n_crews = len([x for x in f.crews if x.link_id])
            share = sh.plan if sh else Decimal(0)
            paid = sh.paid if sh else Decimal(0)
            frac = (share / f.crew_plan) if f.crew_plan else (Decimal(1) / n_crews if n_crews else Decimal(1))
        rows.append((o, f, share, paid, frac, n_crews))
    z = Decimal(0)
    works = sum((f.works_base * fr for _, f, _, _, fr, _ in rows), z)
    total = sum((f.contract_total * fr for _, f, _, _, fr, _ in rows), z)
    crew = sum((sh for _, _, sh, _, _, _ in rows), z)
    paid = sum((pd for _, _, _, pd, _, _ in rows), z)
    mats = sum(((f.materials_cost or 0) * fr for _, f, _, _, fr, _ in rows), z)
    fshare = sum(((f.foreman_share or 0) * fr for _, f, _, _, fr, _ in rows), z)
    ccost = sum(((f.client_cost or 0) * fr for _, f, _, _, fr, _ in rows), z)
    profit = sum(((f.profit or 0) * fr for _, f, _, _, fr, _ in rows), z)
    n = len(rows)
    return {
        "objects": n, "objects_share": q(sum((fr for *_, fr, _ in rows), z)),
        "works": q(works), "revenue": q(total),
        "crew": q(crew), "crew_paid": q(paid), "crew_due": q(crew - paid),
        "materials": q(mats), "foreman_share": q(fshare), "client_cost": q(ccost),
        "profit": q(profit), "margin": q(profit / total * 100) if total else None,
        "crew_per_object": q(crew / n) if n else None, "profit_per_object": q(profit / n) if n else None,
        "avg_check": q(total / n) if n else None,
        "items": [{"id": o.id, "client_name": o.client_name, "address": o.address, "stage": o.stage, "foreman_name": o.foreman.name if o.foreman else None,
                   "works": q(f.works_base * fr), "revenue": q(f.contract_total * fr), "crew": q(sh), "crew_paid": q(pd),
                   "materials": q((f.materials_cost or 0) * fr), "profit": q((f.profit or 0) * fr), "margin": f.margin,
                   "shared": nc > 1, "share_pct": q(fr * 100), "start_date": o.start_date, "end_date": o.end_date}
                  for o, f, sh, pd, fr, nc in sorted(rows, key=lambda x: (x[0].end_date or x[0].start_date or date.min), reverse=True)],
    }


@router.get("/crews")
def crews_stats(month: str | None = None, date_from: str | None = None, date_to: str | None = None,
                _: m.User = Depends(director), db: Session = Depends(get_db)):
    """Сколько заработала каждая бригада (её доля) и сколько осталось компании с её объектов.
    Сданные объекты относятся к месяцу сдачи (акт подписан): month=YYYY-MM или date_from/date_to=YYYY-MM (включительно).
    Объекты в работе показываются отдельно — у них месяца ещё нет, период на них не влияет. total — за всё время."""
    (y, mo), start, end = _bounds(month)
    lo = tuple(map(int, date_from.split("-"))) if date_from else (y, mo)
    hi = tuple(map(int, date_to.split("-"))) if date_to else (lo if date_from else (y, mo))
    if lo > hi:
        lo, hi = hi, lo
    crews = db.scalars(select(m.Crew).order_by(m.Crew.id)).all()
    objs = db.scalars(select(m.WorkObject)).all()
    cm = {o.id: closed_month(o) for o in objs}
    # расходы компании на бригаду (форма, инструмент…) — по дате расхода; из выплат бригаде не вычитаются, это расходы компании
    exps = db.scalars(select(m.Expense).where(m.Expense.crew_id.is_not(None)).order_by(m.Expense.date.desc())).all()
    def exp_block(cid, period: bool):
        items = [e for e in exps if e.crew_id == cid and (not period or lo <= (e.date.year, e.date.month) <= hi)]
        return {"sum": q(sum((e.amount for e in items), Decimal(0))),
                "items": [{"id": e.id, "date": e.date, "category": e.category, "category_name": m.EXPENSE_CATEGORIES.get(e.category, (e.category,))[0],
                           "amount": e.amount, "note": e.note} for e in items]}
    out = []
    cache = {}
    members = {o.id: {l.crew_id for l in o.crew_links} for o in objs}
    groups = [(c.id, c.name, c.foreman.name if c.foreman else None, c.is_active) for c in crews]
    if any(not members[o.id] for o in objs):
        groups.append((None, "Без бригады", None, True))
    for cid, name, foreman, active in groups:
        mine = [o for o in objs if (cid in members[o.id] if cid is not None else not members[o.id])]
        if not mine and not active:
            continue
        done_period = [o for o in mine if cm[o.id] and lo <= cm[o.id] <= hi]
        done_all = [o for o in mine if cm[o.id]]
        active_objs = [o for o in mine if not cm[o.id]]
        out.append({"id": cid, "name": name, "foreman_name": foreman, "is_active": active,
                    "done": _agg(db, done_period, cid, cache),      # сдано за период
                    "done_total": _agg(db, done_all, cid, cache),   # сдано за всё время
                    "active": _agg(db, active_objs, cid, cache),    # в работе сейчас
                    "expenses": exp_block(cid, True),   # расходы на бригаду за период
                    "expenses_total": exp_block(cid, False)})
    return out


@router.get("/summary")
def summary(month: str | None = None, _: m.User = Depends(director), db: Session = Depends(get_db)):
    (y, mo), start, end = _bounds(month)
    received = sum((p.amount for p in db.scalars(select(m.Payment).where(m.Payment.date >= start, m.Payment.date < end)).all()), Decimal(0))
    payouts = sum((p.amount for p in db.scalars(select(m.CrewPayout).where(m.CrewPayout.date >= start, m.CrewPayout.date < end)).all()), Decimal(0))
    materials = sum((l.cost_sum for l in db.scalars(select(m.MaterialLine).where(m.MaterialLine.date >= start, m.MaterialLine.date < end)).all()), Decimal(0))
    exps = db.scalars(select(m.Expense).where(m.Expense.date >= start, m.Expense.date < end)).all()
    by_type = {"channel": Decimal(0), "marketing": Decimal(0), "staff": Decimal(0), "operating": Decimal(0), "materials": Decimal(0)}
    for e in exps:
        t = m.EXPENSE_CATEGORIES.get(e.category, (None, "operating", None))[1]
        by_type[t] += e.amount
    objs = db.scalars(select(m.WorkObject)).all()
    active = [o for o in objs if o.stage not in ("act", "warranty")]
    receivable = sum((compute(db, o, full=False).receivable for o in active), Decimal(0))
    fins_all = [compute(db, o) for o in objs]
    crew_due = sum((f.crew_due for f in fins_all), Decimal(0))
    # по деньгам: закупка материалов — реальный расход месяца; списание на объекты — перенос себестоимости, в итог не входит.
    # материалы, записанные на объект вручную (куплены мимо склада), считаем расходом — у них нет закупки.
    manual_materials = sum((l.cost_sum for l in db.scalars(select(m.MaterialLine).where(
        m.MaterialLine.date >= start, m.MaterialLine.date < end, m.MaterialLine.movement_id.is_(None))).all()), Decimal(0))
    result = received - by_type["materials"] - manual_materials - payouts - by_type["staff"] - by_type["channel"] - by_type["marketing"] - by_type["operating"]
    return {
        "month": f"{y}-{mo:02d}",
        "received": q(received), "materials": q(materials), "crew_payouts": q(payouts),
        "staff": q(by_type["staff"]), "marketing": q(by_type["channel"] + by_type["marketing"]), "operating": q(by_type["operating"]),
        "materials_purchased": q(by_type["materials"] + manual_materials),
        "result": q(result),
        "receivable": q(receivable), "crew_due": q(crew_due),
        "objects_active": len(active), "objects_total": len(objs),
        "avg_margin": q(sum((f.margin or 0 for f in fins_all), Decimal(0)) / len(fins_all)) if fins_all else None,
    }
