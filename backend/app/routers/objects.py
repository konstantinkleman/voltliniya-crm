from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..auth import current_user, director
from ..db import get_db
from ..finance import compute
from ..schemas import (
    ExtraWorkIn, MaterialIn, ObjectCreate, ObjectDetail, ObjectOut, ObjectStage, ObjectUpdate, PaymentIn, PayoutIn,
)

router = APIRouter(prefix="/api/objects", tags=["objects"])


def object_out(db: Session, o: m.WorkObject, full: bool, detail: bool = False) -> ObjectOut:
    cls = ObjectDetail if detail else ObjectOut
    out = cls.model_validate(o)
    out.foreman_name = o.foreman.name if o.foreman else None
    out.crew_name = ", ".join(l.crew.name for l in o.crew_links if l.crew) or (o.crew.name if o.crew else None)
    out.finance = compute(db, o, full=full)
    if detail:
        names = {l.crew_id: l.crew.name for l in o.crew_links if l.crew}
        for p in out.payouts:
            p.crew_name = names.get(p.crew_id) or (db.get(m.Crew, p.crew_id).name if p.crew_id and db.get(m.Crew, p.crew_id) else None)
    if detail and out.materials:
        # категория позиции для материалов, списанных со склада — чтобы группировать таблицу
        from .stock import _cat_path
        cats = {c.id: c for c in db.scalars(select(m.Category)).all()}
        mv_ids = [x.movement_id for x in out.materials if x.movement_id]
        prod_by_mv = {}
        if mv_ids:
            for mv in db.scalars(select(m.StockMovement).where(m.StockMovement.id.in_(mv_ids))).all():
                prod_by_mv[mv.id] = mv.product
        for x in out.materials:
            p = prod_by_mv.get(x.movement_id)
            x.category_path = (_cat_path(db, cats, p.category_id) or None) if p else None
    return out


def _get(db: Session, oid: int, user: m.User) -> m.WorkObject:
    o = db.get(m.WorkObject, oid)
    if not o:
        raise HTTPException(404, "Объект не найден")
    if not user.is_director and o.foreman_id != user.id:
        raise HTTPException(403, "Это не ваш объект")
    return o


def _crew_for(db: Session, foreman_id: int | None, crew_id: int | None = None) -> int | None:
    """Бригада объекта. Явно выбранная должна принадлежать прорабу; если не выбрана —
    единственная бригада прораба подставляется сама, при нескольких бригадах выбор остаётся за директором."""
    if not foreman_id:
        return None
    if crew_id:
        crew = db.get(m.Crew, crew_id)
        if not crew or crew.foreman_id != foreman_id:
            raise HTTPException(400, "Эта бригада закреплена за другим прорабом")
        return crew.id
    crews = db.scalars(select(m.Crew).where(m.Crew.foreman_id == foreman_id, m.Crew.is_active == True)).all()  # noqa: E712
    return crews[0].id if len(crews) == 1 else None


def sync_primary_crew(db: Session, o: m.WorkObject, crew_id: int | None) -> None:
    """Основная бригада объекта (выбор при назначении прораба). Если на объекте один монтажник — заменяем его;
    если несколько — добавляем выбранного, остальных не трогаем."""
    o.crew_id = crew_id
    if not crew_id:
        if len(o.crew_links) <= 1 and not any(p.crew_id for p in o.payouts):
            o.crew_links.clear()
        return
    if any(l.crew_id == crew_id for l in o.crew_links):
        return
    if len(o.crew_links) <= 1 and not any(p.crew_id and p.crew_id != crew_id for p in o.payouts):
        o.crew_links.clear()
    o.crew_links.append(m.ObjectCrew(crew_id=crew_id))


@router.get("", response_model=list[ObjectOut])
def list_objects(stage: str | None = None, active: bool | None = None,
                 user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    qs = select(m.WorkObject).order_by(m.WorkObject.id.desc())
    if not user.is_director:
        qs = qs.where(m.WorkObject.foreman_id == user.id)
    if stage:
        qs = qs.where(m.WorkObject.stage == stage)
    if active is True:
        qs = qs.where(m.WorkObject.stage.not_in(["act", "warranty"]))
    elif active is False:
        qs = qs.where(m.WorkObject.stage.in_(["act", "warranty"]))
    return [object_out(db, o, full=user.is_director) for o in db.scalars(qs).all()]


@router.post("", response_model=ObjectDetail)
def create_object(data: ObjectCreate, user: m.User = Depends(director), db: Session = Depends(get_db)):
    o = m.WorkObject(**data.model_dump(exclude={"crew_id"}), salary_foreman_id=data.foreman_id)
    db.add(o)
    db.flush()
    sync_primary_crew(db, o, _crew_for(db, data.foreman_id, data.crew_id))
    db.add(m.ObjectStageLog(object_id=o.id, stage="contract", user_id=user.id))
    db.commit()
    db.refresh(o)
    return object_out(db, o, full=True, detail=True)


@router.get("/{oid}", response_model=ObjectDetail)
def get_object(oid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    o = _get(db, oid, user)
    return object_out(db, o, full=user.is_director, detail=True)


@router.patch("/{oid}", response_model=ObjectDetail)
def update_object(oid: int, data: ObjectUpdate, user: m.User = Depends(director), db: Session = Depends(get_db)):
    o = _get(db, oid, user)
    patch = data.model_dump(exclude_unset=True)
    crew_id = patch.pop("crew_id", None)
    if "foreman_id" in patch:
        sync_primary_crew(db, o, _crew_for(db, patch["foreman_id"], crew_id))
        if o.salary_foreman_id is None or o.stage == "contract":
            o.salary_foreman_id = patch["foreman_id"]
    elif "crew_id" in data.model_fields_set:
        sync_primary_crew(db, o, _crew_for(db, o.foreman_id, crew_id))
    for k, v in patch.items():
        setattr(o, k, v)
    db.commit()
    db.refresh(o)
    return object_out(db, o, full=True, detail=True)


@router.post("/{oid}/stage", response_model=ObjectDetail)
def set_stage(oid: int, data: ObjectStage, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    o = _get(db, oid, user)
    if data.stage not in m.OBJECT_STAGES:
        raise HTTPException(400, "Неизвестный этап")
    o.stage = data.stage
    # дата сдачи: ставится при подписании акта (если не задана вручную) — по ней объект относится к месяцу в статистике бригад
    if data.stage in ("act", "warranty") and not o.end_date:
        o.end_date = date.today()
    db.add(m.ObjectStageLog(object_id=o.id, stage=data.stage, user_id=user.id))
    db.commit()
    db.refresh(o)
    return object_out(db, o, full=user.is_director, detail=True)


class CrewSumIn(BaseModel):
    amount: Decimal | None = None  # null — вернуть расчёт по правилу


@router.post("/{oid}/crew-sum", response_model=ObjectDetail)
def set_crew_sum(oid: int, data: CrewSumIn, user: m.User = Depends(director), db: Session = Depends(get_db)):
    """Сумма бригаде по договорённости. null — снова считать 55 % от работ."""
    o = _get(db, oid, user)
    o.crew_sum_override = data.amount
    db.commit()
    db.refresh(o)
    return object_out(db, o, full=True, detail=True)


# ---------- платежи клиента ----------
@router.post("/{oid}/payments", response_model=ObjectDetail)
def add_payment(oid: int, data: PaymentIn, user: m.User = Depends(director), db: Session = Depends(get_db)):
    o = _get(db, oid, user)
    db.add(m.Payment(object_id=o.id, **data.model_dump()))
    db.commit()
    db.refresh(o)
    return object_out(db, o, full=True, detail=True)


@router.delete("/{oid}/payments/{pid}", response_model=ObjectDetail)
def del_payment(oid: int, pid: int, user: m.User = Depends(director), db: Session = Depends(get_db)):
    o = _get(db, oid, user)
    p = db.get(m.Payment, pid)
    if p and p.object_id == o.id:
        db.delete(p)
        db.commit()
    db.refresh(o)
    return object_out(db, o, full=True, detail=True)


# ---------- выплаты бригаде ----------
@router.post("/{oid}/payouts", response_model=ObjectDetail)
def add_payout(oid: int, data: PayoutIn, user: m.User = Depends(director), db: Session = Depends(get_db)):
    o = _get(db, oid, user)
    ids = [l.crew_id for l in o.crew_links]
    crew_id = data.crew_id
    if crew_id is None:
        if len(ids) > 1:
            raise HTTPException(400, "На объекте несколько монтажников — укажите, кому выплата")
        crew_id = ids[0] if ids else o.crew_id
    elif crew_id not in ids:
        raise HTTPException(400, "Этот монтажник не назначен на объект")
    db.add(m.CrewPayout(object_id=o.id, foreman_id=o.foreman_id, **data.model_dump(exclude={"crew_id"}), crew_id=crew_id))
    db.commit()
    db.refresh(o)
    return object_out(db, o, full=True, detail=True)


@router.delete("/{oid}/payouts/{pid}", response_model=ObjectDetail)
def del_payout(oid: int, pid: int, user: m.User = Depends(director), db: Session = Depends(get_db)):
    o = _get(db, oid, user)
    p = db.get(m.CrewPayout, pid)
    if p and p.object_id == o.id:
        db.delete(p)
        db.commit()
    db.refresh(o)
    return object_out(db, o, full=True, detail=True)


# ---------- монтажники на объекте ----------
class ObjectCrewIn(BaseModel):
    crew_id: int
    amount: Decimal | None = None
    note: str | None = None


class ObjectCrewPatch(BaseModel):
    amount: Decimal | None = None


@router.post("/{oid}/crews", response_model=ObjectDetail)
def add_object_crew(oid: int, data: ObjectCrewIn, user: m.User = Depends(director), db: Session = Depends(get_db)):
    o = _get(db, oid, user)
    c = db.get(m.Crew, data.crew_id)
    if not c or not c.is_active:
        raise HTTPException(400, "Монтажник не найден")
    if any(l.crew_id == c.id for l in o.crew_links):
        raise HTTPException(400, f"«{c.name}» уже на объекте")
    o.crew_links.append(m.ObjectCrew(crew_id=c.id, amount=data.amount, note=data.note))
    if not o.crew_id:
        o.crew_id = c.id
    db.commit(); db.refresh(o)
    return object_out(db, o, full=True, detail=True)


@router.patch("/{oid}/crews/{lid}", response_model=ObjectDetail)
def set_object_crew(oid: int, lid: int, data: ObjectCrewPatch, user: m.User = Depends(director), db: Session = Depends(get_db)):
    """Задать долю монтажника; пусто — делится поровну из остатка."""
    o = _get(db, oid, user)
    l = next((x for x in o.crew_links if x.id == lid), None)
    if not l:
        raise HTTPException(404)
    l.amount = data.amount
    db.commit(); db.refresh(o)
    return object_out(db, o, full=True, detail=True)


@router.delete("/{oid}/crews/{lid}", response_model=ObjectDetail)
def del_object_crew(oid: int, lid: int, user: m.User = Depends(director), db: Session = Depends(get_db)):
    o = _get(db, oid, user)
    l = next((x for x in o.crew_links if x.id == lid), None)
    if not l:
        raise HTTPException(404)
    if any(p.crew_id == l.crew_id for p in o.payouts):
        raise HTTPException(400, "Этому монтажнику уже были выплаты по объекту — сначала удалите их")
    o.crew_links.remove(l)
    if o.crew_id == l.crew_id:
        o.crew_id = o.crew_links[0].crew_id if o.crew_links else None
    db.commit(); db.refresh(o)
    return object_out(db, o, full=True, detail=True)


# ---------- доп. работы ----------
@router.post("/{oid}/extra-works", response_model=ObjectDetail)
def add_extra(oid: int, data: ExtraWorkIn, user: m.User = Depends(director), db: Session = Depends(get_db)):
    o = _get(db, oid, user)
    db.add(m.ExtraWork(object_id=o.id, **data.model_dump()))
    db.commit()
    db.refresh(o)
    return object_out(db, o, full=True, detail=True)


@router.delete("/{oid}/extra-works/{eid}", response_model=ObjectDetail)
def del_extra(oid: int, eid: int, user: m.User = Depends(director), db: Session = Depends(get_db)):
    o = _get(db, oid, user)
    e = db.get(m.ExtraWork, eid)
    if e and e.object_id == o.id:
        db.delete(e)
        db.commit()
    db.refresh(o)
    return object_out(db, o, full=True, detail=True)


# ---------- материалы (первая версия — суммами; прораб тоже может вносить) ----------
@router.post("/{oid}/materials", response_model=ObjectDetail)
def add_material(oid: int, data: MaterialIn, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    o = _get(db, oid, user)
    db.add(m.MaterialLine(object_id=o.id, user_id=user.id, **data.model_dump()))
    db.commit()
    db.refresh(o)
    return object_out(db, o, full=user.is_director, detail=True)


@router.delete("/{oid}/materials/{mid}", response_model=ObjectDetail)
def del_material(oid: int, mid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    o = _get(db, oid, user)
    line = db.get(m.MaterialLine, mid)
    if line and line.object_id == o.id and (user.is_director or line.user_id == user.id):
        db.delete(line)
        db.commit()
    db.refresh(o)
    return object_out(db, o, full=user.is_director, detail=True)
