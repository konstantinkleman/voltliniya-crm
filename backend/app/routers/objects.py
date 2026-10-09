from fastapi import APIRouter, Depends, HTTPException
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
    out.crew_name = o.crew.name if o.crew else None
    out.finance = compute(db, o, full=full)
    return out


def _get(db: Session, oid: int, user: m.User) -> m.WorkObject:
    o = db.get(m.WorkObject, oid)
    if not o:
        raise HTTPException(404, "Объект не найден")
    if not user.is_director and o.foreman_id != user.id:
        raise HTTPException(403, "Это не ваш объект")
    return o


def _crew_for(db: Session, foreman_id: int | None) -> int | None:
    if not foreman_id:
        return None
    crew = db.scalar(select(m.Crew).where(m.Crew.foreman_id == foreman_id, m.Crew.is_active == True))  # noqa: E712
    return crew.id if crew else None


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
    o = m.WorkObject(**data.model_dump(), crew_id=_crew_for(db, data.foreman_id))
    db.add(o)
    db.flush()
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
    if "foreman_id" in patch:
        o.crew_id = _crew_for(db, patch["foreman_id"])
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
    db.add(m.ObjectStageLog(object_id=o.id, stage=data.stage, user_id=user.id))
    db.commit()
    db.refresh(o)
    return object_out(db, o, full=user.is_director, detail=True)


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
    db.add(m.CrewPayout(object_id=o.id, crew_id=o.crew_id, foreman_id=o.foreman_id, **data.model_dump()))
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
