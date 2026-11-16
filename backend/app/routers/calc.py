"""Калькулятор: справочник расценок, расчёты (в заявке или отдельно), КП/смета/щит, ссылка на КП для клиента."""
import json
import secrets
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import calc, calc_html, calc_params
from .. import models as m
from ..auth import director
from ..db import get_db

router = APIRouter(prefix="/api", tags=["calc"])


# ---------- справочник ----------
@router.get("/calc/params")
def get_params(_: m.User = Depends(director), db: Session = Depends(get_db)):
    return {"sections": calc_params.describe(db)}


class ParamPatch(BaseModel):
    v1: float | None = None
    v2: float | None = None
    v3: float | None = None
    vtext: str | None = None
    product_id: int | None = None
    product2_id: int | None = None
    unlink: list[str] = []          # ["product_id"] — снять привязку


@router.patch("/calc/params/{key}")
def patch_param(key: str, data: ParamPatch, _: m.User = Depends(director), db: Session = Depends(get_db)):
    r = db.get(m.CalcParam, key)
    if not r:
        raise HTTPException(404, "Нет такой строки справочника")
    fields = data.model_fields_set
    for col in ("v1", "v2", "v3"):
        if col in fields:
            val = getattr(data, col)
            if val is not None and val < 0:
                raise HTTPException(400, "Значение не может быть отрицательным")
            setattr(r, col, None if val is None else Decimal(str(val)))
    if "vtext" in fields:
        if key == "general.brand" and data.vtext not in ("Dekraft", "ABB"):
            raise HTTPException(400, "Автоматика: Dekraft или ABB")
        r.vtext = data.vtext
    allowed = {f for _, f in calc_params.links_for(r.key, r.section)}
    for f in ("product_id", "product2_id"):
        if f in fields and getattr(data, f):
            if f not in allowed:
                raise HTTPException(400, "Эту строку нельзя привязать к складу")
            if not db.get(m.Product, getattr(data, f)):
                raise HTTPException(404, "Позиция склада не найдена")
            setattr(r, f, getattr(data, f))
    for f in data.unlink:
        if f in ("product_id", "product2_id"):
            setattr(r, f, None)
    db.commit()
    return {"ok": True}


@router.get("/calc/defaults")
def defaults(_: m.User = Depends(director), db: Session = Depends(get_db)):
    P = calc_params.load(db)
    return {"inputs": calc.default_inputs(P), "room_types": calc.ROOM_TYPES, "tariffs": calc.TARIFF_NAMES}


class ComputeIn(BaseModel):
    inputs: dict
    estimate_id: int | None = None     # считать по снимку справочника этого расчёта


def compact(res: dict, tariff: str) -> dict:
    """Ответ для экрана расчёта (без построчных таблиц документов)."""
    return {
        "inputs": res["inputs"], "volumes": res["volumes"], "tariffs": res["tariffs"], "kp": res["kp"],
        "prices": res["prices"], "warnings": res["warnings"], "margin": res["margin"],
        "works": res["works"], "materials": res["materials"], "finishing": res["finishing"],
        "panel": {k: {x: v[x] for x in ("devices", "modules", "case_text", "cases", "assembly_qty", "assembly_sum",
                                         "materials_sum", "capacity")} for k, v in res["panel"].items()},
        "tariff": tariff,
    }


@router.post("/calc/compute")
def compute(data: ComputeIn, _: m.User = Depends(director), db: Session = Depends(get_db)):
    P = _params_for(db, data.estimate_id)
    return compact(calc.compute(data.inputs, P), "std")


def _params_for(db: Session, estimate_id: int | None) -> dict:
    if estimate_id:
        e = db.get(m.Estimate, estimate_id)
        if e and e.params and e.params != "{}":
            return json.loads(e.params)
    return calc_params.load(db)


# ---------- расчёты ----------
class EstimateIn(BaseModel):
    lead_id: int | None = None
    title: str | None = None
    inputs: dict | None = None
    tariff: str | None = None
    refresh_params: bool = False     # пересчитать по текущему справочнику


def _summary(res: dict) -> dict:
    return {t: {"price": res["kp"][t]["price"], "exact": round(res["tariffs"][t]["price"], 2)} for t in calc.TARIFFS} | {
        "area": res["inputs"]["area"], "points": res["volumes"]["points"]}


def _out(e: m.Estimate, with_result: bool = False, current_params: dict | None = None) -> dict:
    out = {"id": e.id, "lead_id": e.lead_id, "lead_name": e.lead.name if e.lead else None, "title": e.title,
           "tariff": e.tariff, "summary": json.loads(e.summary or "{}"), "share_token": e.share_token,
           "created_at": e.created_at.isoformat() if e.created_at else None,
           "updated_at": e.updated_at.isoformat() if e.updated_at else None}
    if with_result:
        P = json.loads(e.params or "{}")
        res = calc.compute(json.loads(e.inputs or "{}"), P)
        out["result"] = compact(res, e.tariff)
        out["params_outdated"] = current_params is not None and _strip(current_params) != _strip(P)
    return out


def _strip(P: dict) -> dict:
    return {k: {c: v.get(c) for c in ("v1", "v2", "v3", "vtext")} for k, v in P.items()}


@router.get("/estimates")
def list_estimates(lead_id: int | None = None, _: m.User = Depends(director), db: Session = Depends(get_db)):
    qs = select(m.Estimate).order_by(m.Estimate.updated_at.desc())
    if lead_id:
        qs = qs.where(m.Estimate.lead_id == lead_id)
    return [_out(e) for e in db.scalars(qs.limit(300)).all()]


@router.post("/estimates")
def create_estimate(data: EstimateIn, user: m.User = Depends(director), db: Session = Depends(get_db)):
    P = calc_params.load(db)
    inputs = calc.default_inputs(P)
    lead = None
    if data.lead_id:
        lead = db.get(m.Lead, data.lead_id)
        if not lead:
            raise HTTPException(404, "Заявка не найдена")
        inputs["object"] = ", ".join(x for x in (lead.address, lead.name) if x)
        if lead.area_m2:
            inputs["area"] = float(lead.area_m2)
    if data.inputs:
        inputs.update(data.inputs)
    res = calc.compute(inputs, P)
    e = m.Estimate(lead_id=data.lead_id, title=data.title or res["inputs"]["object"] or "Расчёт",
                   inputs=json.dumps(res["inputs"], ensure_ascii=False), params=json.dumps(P, ensure_ascii=False),
                   tariff=data.tariff if data.tariff in calc.TARIFFS else "std",
                   summary=json.dumps(_summary(res), ensure_ascii=False), user_id=user.id)
    db.add(e)
    if lead:
        db.add(m.LeadActivity(lead_id=lead.id, kind="note", text="Создан расчёт", user_id=user.id))
    db.commit()
    db.refresh(e)
    return _out(e, True, P)


def _get(db: Session, eid: int) -> m.Estimate:
    e = db.get(m.Estimate, eid)
    if not e:
        raise HTTPException(404, "Расчёт не найден")
    return e


@router.get("/estimates/{eid}")
def get_estimate(eid: int, _: m.User = Depends(director), db: Session = Depends(get_db)):
    return _out(_get(db, eid), True, calc_params.load(db))


@router.put("/estimates/{eid}")
def update_estimate(eid: int, data: EstimateIn, _: m.User = Depends(director), db: Session = Depends(get_db)):
    e = _get(db, eid)
    current = calc_params.load(db)
    if data.refresh_params:
        e.params = json.dumps(current, ensure_ascii=False)
    P = json.loads(e.params or "{}") or current
    inputs = json.loads(e.inputs or "{}")
    if data.inputs is not None:
        inputs = data.inputs
    res = calc.compute(inputs, P)
    e.inputs = json.dumps(res["inputs"], ensure_ascii=False)
    if data.tariff in calc.TARIFFS:
        e.tariff = data.tariff
    if data.title is not None:
        e.title = data.title.strip()[:300] or res["inputs"]["object"] or "Расчёт"
    elif not e.title or e.title == "Расчёт":
        e.title = res["inputs"]["object"] or "Расчёт"
    if "lead_id" in data.model_fields_set:
        if data.lead_id and not db.get(m.Lead, data.lead_id):
            raise HTTPException(404, "Заявка не найдена")
        e.lead_id = data.lead_id
    e.summary = json.dumps(_summary(res), ensure_ascii=False)
    db.commit()
    db.refresh(e)
    return _out(e, True, current)


@router.delete("/estimates/{eid}")
def delete_estimate(eid: int, _: m.User = Depends(director), db: Session = Depends(get_db)):
    db.delete(_get(db, eid))
    db.commit()
    return {"ok": True}


@router.post("/estimates/{eid}/copy")
def copy_estimate(eid: int, user: m.User = Depends(director), db: Session = Depends(get_db)):
    e = _get(db, eid)
    c = m.Estimate(lead_id=e.lead_id, title=(e.title + " (копия)")[:300], inputs=e.inputs, params=e.params, tariff=e.tariff,
                   summary=e.summary, user_id=user.id)
    db.add(c)
    db.commit()
    db.refresh(c)
    return _out(c)


def _result(e: m.Estimate) -> dict:
    return calc.compute(json.loads(e.inputs or "{}"), json.loads(e.params or "{}"))


@router.get("/estimates/{eid}/doc/{kind}", response_class=HTMLResponse)
def doc(eid: int, kind: str, tariff: str | None = None, _: m.User = Depends(director), db: Session = Depends(get_db)):
    e = _get(db, eid)
    res = _result(e)
    t = tariff if tariff in calc.TARIFFS else e.tariff
    when = e.updated_at.date() if e.updated_at else date.today()
    if kind == "kp":
        return calc_html.kp_html(res, when)
    if kind == "smeta":
        return calc_html.smeta_html(res, t, when)
    if kind == "panel":
        return calc_html.panel_html(res, t)
    raise HTTPException(404, "Нет такого документа")


@router.post("/estimates/{eid}/share")
def share(eid: int, user: m.User = Depends(director), db: Session = Depends(get_db)):
    """Ссылка на КП для клиента (без входа в CRM). Повторный вызов возвращает ту же ссылку."""
    e = _get(db, eid)
    if not e.share_token:
        e.share_token = secrets.token_urlsafe(18)
    if e.lead_id:
        db.add(m.LeadActivity(lead_id=e.lead_id, kind="offer", text=f"Ссылка на КП: «{e.title}»", user_id=user.id))
    db.commit()
    return {"url": f"/api/public/kp/{e.share_token}", "token": e.share_token}


@router.delete("/estimates/{eid}/share")
def unshare(eid: int, _: m.User = Depends(director), db: Session = Depends(get_db)):
    e = _get(db, eid)
    e.share_token = None
    db.commit()
    return {"ok": True}


@router.post("/estimates/{eid}/to-lead")
def to_lead(eid: int, user: m.User = Depends(director), db: Session = Depends(get_db)):
    """Записать в заявку сумму КП по выбранному тарифу (поле «Сумма КП» и тариф)."""
    e = _get(db, eid)
    if not e.lead_id:
        raise HTTPException(400, "Расчёт не привязан к заявке")
    lead = db.get(m.Lead, e.lead_id)
    res = _result(e)
    price = res["kp"][e.tariff]["price"]
    lead.offer_sum = Decimal(str(price))
    lead.tariff = calc.TARIFF_NAMES[e.tariff]
    if not lead.area_m2 and res["inputs"]["area"]:
        lead.area_m2 = Decimal(str(res["inputs"]["area"]))
    if lead.stage in ("new", "contacted", "measure"):
        lead.stage = "offer_sent"
    db.add(m.LeadActivity(lead_id=lead.id, kind="offer",
                          text=f"КП по расчёту «{e.title}»: тариф «{calc.TARIFF_NAMES[e.tariff]}», {price:,.0f} ₽".replace(",", " "),
                          user_id=user.id))
    db.commit()
    return {"ok": True, "offer_sum": price, "tariff": lead.tariff, "stage": lead.stage}


@router.get("/public/kp/{token}", response_class=HTMLResponse)
def public_kp(token: str, db: Session = Depends(get_db)):
    if not token or len(token) < 16:
        raise HTTPException(404, "КП не найдено")
    e = db.scalar(select(m.Estimate).where(m.Estimate.share_token == token))
    if not e:
        return HTMLResponse("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                            "<p style='font:16px sans-serif;padding:24px'>Ссылка на коммерческое предложение больше не действует.</p>",
                            status_code=404)
    res = _result(e)
    return calc_html.kp_html(res, e.updated_at.date() if e.updated_at else date.today(), public=True)
