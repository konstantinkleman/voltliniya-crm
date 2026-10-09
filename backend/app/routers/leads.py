from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..auth import director
from ..db import get_db
from ..schemas import ActivityCreate, ActivityOut, LeadConvert, LeadCreate, LeadDetail, LeadOut, LeadStage, LeadUpdate, ObjectOut
from .objects import object_out

router = APIRouter(prefix="/api/leads", tags=["leads"])


def _get(db: Session, lid: int) -> m.Lead:
    lead = db.get(m.Lead, lid)
    if not lead:
        raise HTTPException(404, "Заявка не найдена")
    return lead


def _activity(db: Session, lead: m.Lead, user: m.User, kind: str, text: str):
    db.add(m.LeadActivity(lead_id=lead.id, kind=kind, text=text, user_id=user.id))


def _detail(lead: m.Lead) -> LeadDetail:
    d = LeadDetail.model_validate(lead)
    d.activities = [ActivityOut(id=a.id, kind=a.kind, text=a.text, created_at=a.created_at,
                                user_name=a.user.name if a.user else None) for a in lead.activities]
    return d


@router.get("", response_model=list[LeadOut])
def list_leads(stage: str | None = None, source: str | None = None, include_closed: bool = True,
               _: m.User = Depends(director), db: Session = Depends(get_db)):
    qs = select(m.Lead).order_by(m.Lead.updated_at.desc())
    if stage:
        qs = qs.where(m.Lead.stage == stage)
    if source:
        qs = qs.where(m.Lead.source == source)
    if not include_closed:
        qs = qs.where(m.Lead.stage.not_in(["won", "lost"]))
    return db.scalars(qs).all()


@router.post("", response_model=LeadDetail)
def create_lead(data: LeadCreate, user: m.User = Depends(director), db: Session = Depends(get_db)):
    if data.source not in m.SOURCES:
        raise HTTPException(400, "Неизвестный источник")
    lead = m.Lead(**data.model_dump())
    db.add(lead)
    db.flush()
    txt = "Заявка создана"
    if lead.lead_cost:
        txt += f", стоимость лида {lead.lead_cost:.0f} ₽"
    _activity(db, lead, user, "stage", txt)
    db.commit()
    db.refresh(lead)
    return _detail(lead)


@router.get("/{lid}", response_model=LeadDetail)
def get_lead(lid: int, _: m.User = Depends(director), db: Session = Depends(get_db)):
    return _detail(_get(db, lid))


@router.patch("/{lid}", response_model=LeadDetail)
def update_lead(lid: int, data: LeadUpdate, _: m.User = Depends(director), db: Session = Depends(get_db)):
    lead = _get(db, lid)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(lead, k, v)
    db.commit()
    db.refresh(lead)
    return _detail(lead)


@router.post("/{lid}/stage", response_model=LeadDetail)
def set_stage(lid: int, data: LeadStage, user: m.User = Depends(director), db: Session = Depends(get_db)):
    lead = _get(db, lid)
    if data.stage not in m.LEAD_STAGES:
        raise HTTPException(400, "Неизвестный этап")
    if data.stage == "won":
        raise HTTPException(400, "Этап «Договор» ставится через создание объекта")
    if data.stage == "lost" and not data.lost_reason:
        raise HTTPException(400, "Укажите причину отказа")
    if lead.stage == "won":
        raise HTTPException(400, "Заявка уже стала объектом")
    lead.stage = data.stage
    lead.lost_reason = data.lost_reason if data.stage == "lost" else None
    txt = m.LEAD_STAGE_NAMES[data.stage]
    if data.lost_reason:
        txt += f": {data.lost_reason}"
    if data.comment:
        txt += f" — {data.comment}"
    _activity(db, lead, user, "stage", txt)
    db.commit()
    db.refresh(lead)
    return _detail(lead)


@router.post("/{lid}/activities", response_model=LeadDetail)
def add_activity(lid: int, data: ActivityCreate, user: m.User = Depends(director), db: Session = Depends(get_db)):
    lead = _get(db, lid)
    _activity(db, lead, user, data.kind, data.text)
    db.commit()
    db.refresh(lead)
    return _detail(lead)


@router.post("/{lid}/convert", response_model=ObjectOut)
def convert(lid: int, data: LeadConvert, user: m.User = Depends(director), db: Session = Depends(get_db)):
    """Договор подписан: заявка превращается в объект, документы переезжают."""
    lead = _get(db, lid)
    if lead.object_id:
        raise HTTPException(400, "Объект уже создан")
    foreman_id = data.foreman_id
    crew_id = None
    if foreman_id:
        crew = db.scalar(select(m.Crew).where(m.Crew.foreman_id == foreman_id, m.Crew.is_active == True))  # noqa: E712
        crew_id = crew.id if crew else None
    obj = m.WorkObject(
        client_name=lead.name, phone=lead.phone, address=lead.address, area_m2=lead.area_m2,
        tariff=data.tariff or lead.tariff, source=lead.source, foreman_id=foreman_id, crew_id=crew_id, salary_foreman_id=foreman_id,
        start_date=data.start_date, works_sum=data.works_sum, materials_client_sum=data.materials_client_sum,
        contract_number=data.contract_number, note=lead.note,
    )
    db.add(obj)
    db.flush()
    db.add(m.ObjectStageLog(object_id=obj.id, stage="contract", user_id=user.id))
    for doc in lead.documents:
        doc.object_id = obj.id
    lead.stage = "won"
    lead.won_at = date.today()
    lead.object_id = obj.id
    _activity(db, lead, user, "stage", f"Договор подписан, создан объект № {obj.id}")
    db.commit()
    db.refresh(obj)
    return object_out(db, obj, full=True)
