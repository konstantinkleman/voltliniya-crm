"""Справочник калькулятора в БД: заполнение по умолчанию и сборка словаря P для движка с учётом привязки к складу."""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .calc_defaults import DEFAULTS, SECTIONS
from .stock import all_balances

# какие колонки строки можно привязать к позиции склада: (колонка значения, поле привязки)
PRICE_KEYS_V1 = {"mat.vvg15", "mat.vvg25", "mat.vvg54", "mat.vvg36", "mat.pugv6", "mat.pugv4", "mat.twisted", "mat.box",
                 "mat.box_cap", "mat.junction", "mat.kup_box", "mat.sleeve", "mat.corr_pvc", "mat.corr_pnd", "mat.tape",
                 "mat.wago", "mat.chase_clips", "mat.corr_clip", "mat.pad", "mat.dowel", "panel.relay_price", "panel.busbar"}


def links_for(key: str, section: str) -> list[tuple[str, str]]:
    if section == "auto":
        return [("v1", "product_id"), ("v2", "product2_id")]
    if section == "cases":
        return [("v3", "product_id")]
    if key in PRICE_KEYS_V1:
        return [("v1", "product_id")]
    return []


def seed(db: Session) -> None:
    """Добавляет недостающие строки справочника; изменённые значения не трогает."""
    have = {k for (k,) in db.execute(select(m.CalcParam.key))}
    for i, (key, section, label, unit, v1, v2, v3, note, vtext) in enumerate(DEFAULTS):
        if key in have:
            continue
        db.add(m.CalcParam(key=key, section=section, label=label, unit=unit or None, note=note, sort=i,
                           v1=None if v1 is None else Decimal(str(v1)), v2=None if v2 is None else Decimal(str(v2)),
                           v3=None if v3 is None else Decimal(str(v3)), vtext=vtext))
    db.commit()


def avg_costs(db: Session) -> dict[int, float]:
    """Средняя себестоимость позиции по всем складам (по остатку)."""
    acc: dict[int, list[float]] = {}
    for (_wh, pid), (qty, cost) in all_balances(db).items():
        if qty > 0:
            a = acc.setdefault(pid, [0.0, 0.0])
            a[0] += float(qty); a[1] += float(qty) * float(cost)
    return {pid: v / q for pid, (q, v) in acc.items() if q > 0}


def load(db: Session) -> dict:
    """P для движка: значения справочника; цена связанной позиции склада заменяет значение, если задана."""
    rows = db.scalars(select(m.CalcParam)).all()
    pids = {r.product_id for r in rows if r.product_id} | {r.product2_id for r in rows if r.product2_id}
    prods = {p.id: p for p in db.scalars(select(m.Product).where(m.Product.id.in_(pids)))} if pids else {}
    costs = avg_costs(db) if pids else {}
    P = {}
    for r in rows:
        item = {"v1": _f(r.v1), "v2": _f(r.v2), "v3": _f(r.v3), "vtext": r.vtext}
        for col, field in links_for(r.key, r.section):
            pid = getattr(r, field)
            if not pid or pid not in prods:
                continue
            pr = prods[pid]
            if pr.client_price is not None:
                item[col] = float(pr.client_price)
            item["cost1" if col in ("v1", "v3") else "cost2"] = costs.get(pid)
        P[r.key] = item
    return P


def describe(db: Session) -> list[dict]:
    """Справочник для страницы «Расценки»: разделы, строки, привязки к складу."""
    rows = db.scalars(select(m.CalcParam).order_by(m.CalcParam.sort)).all()
    pids = {r.product_id for r in rows if r.product_id} | {r.product2_id for r in rows if r.product2_id}
    prods = {p.id: p for p in db.scalars(select(m.Product).where(m.Product.id.in_(pids)))} if pids else {}
    costs = avg_costs(db) if pids else {}
    out = []
    for sec, (title, cols) in SECTIONS.items():
        items = []
        for r in rows:
            if r.section != sec:
                continue
            links = []
            for col, field in links_for(r.key, r.section):
                pid = getattr(r, field)
                p = prods.get(pid) if pid else None
                links.append({"col": col, "field": field, "product_id": pid, "product_name": p.name if p else None,
                              "product_price": float(p.client_price) if p and p.client_price is not None else None,
                              "product_cost": costs.get(pid) if pid else None})
            items.append({"key": r.key, "label": r.label, "unit": r.unit, "note": r.note, "v1": _f(r.v1), "v2": _f(r.v2),
                          "v3": _f(r.v3), "vtext": r.vtext, "links": links,
                          "updated_at": r.updated_at.isoformat() if r.updated_at else None})
        if items:
            out.append({"section": sec, "title": title, "cols": list(cols), "items": items})
    return out


def _f(v):
    return None if v is None else float(v)
