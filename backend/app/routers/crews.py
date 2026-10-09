from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..auth import current_user, director
from ..db import get_db
from ..schemas import CrewAssignmentOut, CrewCreate, CrewOut, CrewReassign, CrewUpdate

router = APIRouter(prefix="/api/crews", tags=["crews"])


def _out(c: m.Crew) -> CrewOut:
    o = CrewOut.model_validate(c)
    o.foreman_name = c.foreman.name if c.foreman else None
    o.history = [CrewAssignmentOut(id=h.id, foreman_id=h.foreman_id, foreman_name=h.foreman.name if h.foreman else None,
                                   from_date=h.from_date, to_date=h.to_date, note=h.note) for h in c.history]
    return o


@router.get("", response_model=list[CrewOut])
def list_crews(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    qs = select(m.Crew).order_by(m.Crew.id)
    if not user.is_director:
        qs = qs.where(m.Crew.foreman_id == user.id)
    return [_out(c) for c in db.scalars(qs).all()]


@router.post("", response_model=CrewOut)
def create_crew(data: CrewCreate, _: m.User = Depends(director), db: Session = Depends(get_db)):
    if data.foreman_id:
        busy = db.scalar(select(m.Crew).where(m.Crew.foreman_id == data.foreman_id, m.Crew.is_active == True))  # noqa: E712
        if busy:
            raise HTTPException(400, f"У этого прораба уже есть бригада «{busy.name}»")
    c = m.Crew(**data.model_dump())
    db.add(c)
    db.flush()
    if c.foreman_id:
        db.add(m.CrewAssignment(crew_id=c.id, foreman_id=c.foreman_id, from_date=date.today()))
    db.commit()
    db.refresh(c)
    return _out(c)


@router.patch("/{cid}", response_model=CrewOut)
def update_crew(cid: int, data: CrewUpdate, _: m.User = Depends(director), db: Session = Depends(get_db)):
    c = db.get(m.Crew, cid)
    if not c:
        raise HTTPException(404)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return _out(c)


@router.post("/{cid}/reassign", response_model=CrewOut)
def reassign(cid: int, data: CrewReassign, _: m.User = Depends(director), db: Session = Depends(get_db)):
    """Передать бригаду другому прорабу. Объекты в работе переходят вместе с ней."""
    c = db.get(m.Crew, cid)
    if not c:
        raise HTTPException(404)
    new = db.get(m.User, data.foreman_id)
    if not new or not new.is_foreman:
        raise HTTPException(400, "Это не прораб")
    busy = db.scalar(select(m.Crew).where(m.Crew.foreman_id == new.id, m.Crew.is_active == True, m.Crew.id != c.id))  # noqa: E712
    if busy:
        raise HTTPException(400, f"У прораба уже есть бригада «{busy.name}»")
    today = date.today()
    for h in c.history:
        if h.to_date is None:
            h.to_date = today
    old_id = c.foreman_id
    c.foreman_id = new.id
    db.add(m.CrewAssignment(crew_id=c.id, foreman_id=new.id, from_date=today, note=data.note))
    if data.move_objects and old_id:
        for o in db.scalars(select(m.WorkObject).where(m.WorkObject.crew_id == c.id, m.WorkObject.stage.not_in(["act", "warranty"]))).all():
            o.foreman_id = new.id
    db.commit()
    db.refresh(c)
    return _out(c)
