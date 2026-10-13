import uuid
from datetime import date as Date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import stock as S
from ..auth import current_user, director
from ..db import get_db

router = APIRouter(prefix="/api/stock", tags=["stock"])


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- склады ----------
class WarehouseOut(ORM):
    id: int
    name: str
    foreman_id: int | None
    foreman_name: str | None = None
    address: str | None
    is_active: bool
    value: Decimal = Decimal(0)        # стоимость остатков
    positions: int = 0
    low: int = 0                        # позиций ниже минимума
    pending_in: int = 0                 # перемещений, ждущих подтверждения


class WarehouseIn(BaseModel):
    name: str
    foreman_id: int | None = None
    address: str | None = None


def _wh_out(db: Session, w: m.Warehouse, bal: dict) -> WarehouseOut:
    o = WarehouseOut.model_validate(w)
    o.foreman_name = w.foreman.name if w.foreman else None
    mine = {k: v for k, v in bal.items() if k[0] == w.id and v[0] > 0}
    o.value = S.q2(sum((q * c for q, c in mine.values()), Decimal(0)))
    o.positions = len(mine)
    prods = {p.id: p for p in db.scalars(select(m.Product).where(m.Product.id.in_([k[1] for k in mine]))).all()} if mine else {}
    o.low = sum(1 for (wid, pid), (q, _) in mine.items() if prods.get(pid) and prods[pid].min_qty and q < prods[pid].min_qty)
    o.pending_in = db.scalar(select(m.StockMovement).where(m.StockMovement.warehouse_id == w.id, m.StockMovement.confirmed == False).limit(1)) is not None and \
        len(db.scalars(select(m.StockMovement.id).where(m.StockMovement.warehouse_id == w.id, m.StockMovement.confirmed == False)).all())  # noqa: E712
    return o


def _visible_warehouses(db: Session, user: m.User) -> list[m.Warehouse]:
    qs = select(m.Warehouse).where(m.Warehouse.is_active == True).order_by(m.Warehouse.id)  # noqa: E712
    if not user.is_director:
        qs = qs.where(m.Warehouse.foreman_id == user.id)
    return db.scalars(qs).all()


def _check_wh_access(db: Session, user: m.User, wid: int) -> m.Warehouse:
    w = db.get(m.Warehouse, wid)
    if not w:
        raise HTTPException(404, "Склад не найден")
    if not user.is_director and w.foreman_id != user.id:
        raise HTTPException(403, "Это не ваш склад")
    return w


@router.get("/warehouses", response_model=list[WarehouseOut])
def list_warehouses(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    bal = S.all_balances(db)
    return [_wh_out(db, w, bal) for w in _visible_warehouses(db, user)]


@router.post("/warehouses", response_model=WarehouseOut)
def create_warehouse(data: WarehouseIn, _: m.User = Depends(director), db: Session = Depends(get_db)):
    if data.foreman_id:
        busy = db.scalar(select(m.Warehouse).where(m.Warehouse.foreman_id == data.foreman_id, m.Warehouse.is_active == True))  # noqa: E712
        if busy:
            raise HTTPException(400, f"У этого прораба уже есть склад «{busy.name}»")
    w = m.Warehouse(**data.model_dump())
    db.add(w); db.commit(); db.refresh(w)
    return _wh_out(db, w, {})


@router.patch("/warehouses/{wid}", response_model=WarehouseOut)
def update_warehouse(wid: int, data: WarehouseIn, _: m.User = Depends(director), db: Session = Depends(get_db)):
    w = db.get(m.Warehouse, wid)
    if not w:
        raise HTTPException(404)
    for k, v in data.model_dump().items():
        setattr(w, k, v)
    db.commit(); db.refresh(w)
    return _wh_out(db, w, S.all_balances(db, wid))


# ---------- категории ----------
class CategoryOut(ORM):
    id: int
    name: str
    parent_id: int | None
    sort: int
    markup_pct: Decimal | None


class CategoryIn(BaseModel):
    name: str
    parent_id: int | None = None
    markup_pct: Decimal | None = None
    sort: int = 0


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(_: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(m.Category).order_by(m.Category.sort, m.Category.name)).all()


@router.post("/categories", response_model=CategoryOut)
def create_category(data: CategoryIn, _: m.User = Depends(director), db: Session = Depends(get_db)):
    c = m.Category(**data.model_dump())
    db.add(c); db.commit(); db.refresh(c)
    return c


@router.patch("/categories/{cid}", response_model=CategoryOut)
def update_category(cid: int, data: CategoryIn, _: m.User = Depends(director), db: Session = Depends(get_db)):
    c = db.get(m.Category, cid)
    if not c:
        raise HTTPException(404)
    if data.parent_id == cid:
        raise HTTPException(400, "Категория не может быть вложена в себя")
    for k, v in data.model_dump().items():
        setattr(c, k, v)
    db.commit(); db.refresh(c)
    return c


@router.delete("/categories/{cid}")
def delete_category(cid: int, _: m.User = Depends(director), db: Session = Depends(get_db)):
    c = db.get(m.Category, cid)
    if not c:
        return {"ok": True}
    if db.scalar(select(m.Category).where(m.Category.parent_id == cid)) or db.scalar(select(m.Product).where(m.Product.category_id == cid)):
        raise HTTPException(400, "Сначала перенесите вложенные категории и позиции")
    db.delete(c); db.commit()
    return {"ok": True}


# ---------- номенклатура ----------
class ProductOut(ORM):
    id: int
    name: str
    category_id: int | None
    category_path: str = ""
    unit: str
    sku: str | None
    pack_qty: Decimal | None
    pack_name: str | None
    markup_pct: Decimal | None
    client_price: Decimal | None
    min_qty: Decimal | None
    note: str | None
    is_active: bool
    # остатки по складам: {warehouse_id: {qty, avg_cost, value}}
    stock: dict[int, dict] = {}
    total_qty: Decimal = Decimal(0)
    total_value: Decimal = Decimal(0)
    price: Decimal | None = None      # цена клиенту от средней себестоимости по всем складам


class ProductIn(BaseModel):
    name: str
    category_id: int | None = None
    unit: str = "шт"
    sku: str | None = None
    pack_qty: Decimal | None = None
    pack_name: str | None = None
    markup_pct: Decimal | None = None
    client_price: Decimal | None = None
    min_qty: Decimal | None = None
    note: str | None = None
    is_active: bool = True


def _cat_path(db: Session, cats: dict[int, m.Category], cid: int | None) -> str:
    parts = []
    seen = set()
    while cid and cid in cats and cid not in seen:
        seen.add(cid); parts.append(cats[cid].name); cid = cats[cid].parent_id
    return " → ".join(reversed(parts))


def _products_out(db: Session, prods: list[m.Product], bal: dict, wh_ids: set[int] | None) -> list[ProductOut]:
    cats = {c.id: c for c in db.scalars(select(m.Category)).all()}
    out = []
    for p in prods:
        o = ProductOut.model_validate(p)
        o.category_path = _cat_path(db, cats, p.category_id)
        tq = Decimal(0); tv = Decimal(0)
        for (wid, pid), (q, c) in bal.items():
            if pid != p.id or (wh_ids is not None and wid not in wh_ids):
                continue
            o.stock[wid] = {"qty": q, "avg_cost": c, "value": S.q2(q * c)}
            tq += q; tv += q * c
        o.total_qty = S.q3(tq); o.total_value = S.q2(tv)
        avg = S.q2(tv / tq) if tq > 0 else Decimal(0)
        o.price = S.client_price(db, p, avg)
        out.append(o)
    return out


@router.get("/products", response_model=list[ProductOut])
def list_products(warehouse_id: int | None = None, category_id: int | None = None, q: str | None = None, include_inactive: bool = False,
                  user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    qs = select(m.Product).order_by(m.Product.name)
    if not include_inactive:
        qs = qs.where(m.Product.is_active == True)  # noqa: E712
    if q:
        qs = qs.where(m.Product.name.ilike(f"%{q}%"))
    if category_id:
        # категория и все вложенные
        cats = db.scalars(select(m.Category)).all()
        ids = {category_id}; changed = True
        while changed:
            changed = False
            for c in cats:
                if c.parent_id in ids and c.id not in ids:
                    ids.add(c.id); changed = True
        qs = qs.where(m.Product.category_id.in_(ids))
    visible = {w.id for w in _visible_warehouses(db, user)}
    if warehouse_id:
        if warehouse_id not in visible:
            raise HTTPException(403)
        visible = {warehouse_id}
    bal = S.all_balances(db)
    return _products_out(db, db.scalars(qs).all(), bal, visible if not user.is_director or warehouse_id else None)


@router.post("/products", response_model=ProductOut)
def create_product(data: ProductIn, _: m.User = Depends(director), db: Session = Depends(get_db)):
    p = m.Product(**data.model_dump())
    db.add(p); db.commit(); db.refresh(p)
    return _products_out(db, [p], {}, None)[0]


@router.patch("/products/{pid}", response_model=ProductOut)
def update_product(pid: int, data: ProductIn, _: m.User = Depends(director), db: Session = Depends(get_db)):
    p = db.get(m.Product, pid)
    if not p:
        raise HTTPException(404)
    for k, v in data.model_dump().items():
        setattr(p, k, v)
    db.commit(); db.refresh(p)
    return _products_out(db, [p], S.all_balances(db), None)[0]


# ---------- движения ----------
class MovementOut(ORM):
    id: int
    kind: str
    kind_name: str = ""
    warehouse_id: int
    warehouse_name: str = ""
    product_id: int
    product_name: str = ""
    unit: str = ""
    qty: Decimal
    unit_cost: Decimal
    date: Date
    object_id: int | None
    object_name: str | None = None
    supplier: str | None
    doc_number: str | None
    batch: str | None
    confirmed: bool
    note: str | None
    user_name: str | None = None


def _mv_out(mv: m.StockMovement) -> MovementOut:
    o = MovementOut.model_validate(mv)
    o.kind_name = m.MOVEMENT_KINDS.get(mv.kind, mv.kind)
    o.warehouse_name = mv.warehouse.name if mv.warehouse else ""
    o.product_name = mv.product.name if mv.product else ""
    o.unit = mv.product.unit if mv.product else ""
    o.object_name = mv.object.client_name if mv.object else None
    o.user_name = mv.user.name if mv.user else None
    return o


@router.get("/movements", response_model=list[MovementOut])
def list_movements(warehouse_id: int | None = None, product_id: int | None = None, object_id: int | None = None,
                   kind: str | None = None, limit: int = 200, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    qs = select(m.StockMovement).order_by(m.StockMovement.date.desc(), m.StockMovement.id.desc()).limit(min(limit, 1000))
    visible = {w.id for w in _visible_warehouses(db, user)}
    if warehouse_id:
        if warehouse_id not in visible:
            raise HTTPException(403)
        qs = qs.where(m.StockMovement.warehouse_id == warehouse_id)
    elif not user.is_director:
        qs = qs.where(m.StockMovement.warehouse_id.in_(visible))
    if product_id:
        qs = qs.where(m.StockMovement.product_id == product_id)
    if object_id:
        qs = qs.where(m.StockMovement.object_id == object_id)
    if kind:
        qs = qs.where(m.StockMovement.kind == kind)
    return [_mv_out(x) for x in db.scalars(qs).all()]


class ReceiptLine(BaseModel):
    product_id: int | None = None
    new_product: ProductIn | None = None   # создать позицию на лету
    qty: Decimal
    unit_cost: Decimal = Decimal(0)


class ReceiptIn(BaseModel):
    warehouse_id: int
    date: Date
    supplier: str | None = None
    doc_number: str | None = None
    note: str | None = None
    lines: list[ReceiptLine]
    add_expense: bool = False   # записать сумму прихода в расходы компании (категория «Материалы»)


@router.post("/receipt", response_model=list[MovementOut])
def post_receipt(data: ReceiptIn, user: m.User = Depends(director), db: Session = Depends(get_db)):
    if not data.lines:
        raise HTTPException(400, "Нет строк")
    lines = []
    for ln in data.lines:
        pid = ln.product_id
        if not pid and ln.new_product:
            p = m.Product(**ln.new_product.model_dump()); db.add(p); db.flush(); pid = p.id
        if not pid:
            raise HTTPException(400, "В строке не указана позиция")
        lines.append({"product_id": pid, "qty": ln.qty, "unit_cost": ln.unit_cost})
    batch = uuid.uuid4().hex[:12]
    mvs = S.receipt(db, warehouse_id=data.warehouse_id, lines=lines, date=data.date, supplier=data.supplier,
                    doc_number=data.doc_number, note=data.note, user_id=user.id, batch=batch)
    if data.add_expense:
        total = sum((Decimal(str(l["qty"])) * Decimal(str(l["unit_cost"])) for l in lines), Decimal(0))
        if total > 0:
            db.add(m.Expense(date=data.date, amount=S.q2(total), category="materials", channel=None, user_id=user.id,
                             note=f"Закупка материалов{(' · ' + data.supplier) if data.supplier else ''}{(' · накладная ' + data.doc_number) if data.doc_number else ''}"))
    db.commit()
    for mv in mvs:
        db.refresh(mv)
    return [_mv_out(x) for x in mvs]


class IssueIn(BaseModel):
    warehouse_id: int
    product_id: int
    qty: Decimal
    object_id: int
    date: Date | None = None
    note: str | None = None


@router.post("/issue", response_model=MovementOut)
def post_issue(data: IssueIn, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    _check_wh_access(db, user, data.warehouse_id)
    o = db.get(m.WorkObject, data.object_id)
    if not o:
        raise HTTPException(404, "Объект не найден")
    if not user.is_director and o.foreman_id != user.id:
        raise HTTPException(403, "Это не ваш объект")
    mv = S.issue(db, warehouse_id=data.warehouse_id, product_id=data.product_id, qty=data.qty, object_id=data.object_id,
                 date=data.date or Date.today(), note=data.note, user_id=user.id)
    db.commit(); db.refresh(mv)
    return _mv_out(mv)


@router.post("/return", response_model=MovementOut)
def post_return(data: IssueIn, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    _check_wh_access(db, user, data.warehouse_id)
    o = db.get(m.WorkObject, data.object_id)
    if not o or (not user.is_director and o.foreman_id != user.id):
        raise HTTPException(403, "Это не ваш объект")
    mv = S.return_from_object(db, warehouse_id=data.warehouse_id, product_id=data.product_id, qty=data.qty,
                              object_id=data.object_id, date=data.date or Date.today(), note=data.note, user_id=user.id)
    db.commit(); db.refresh(mv)
    return _mv_out(mv)


class TransferIn(BaseModel):
    from_warehouse_id: int
    to_warehouse_id: int
    product_id: int
    qty: Decimal
    date: Date | None = None
    note: str | None = None


@router.post("/transfer", response_model=list[MovementOut])
def post_transfer(data: TransferIn, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    _check_wh_access(db, user, data.from_warehouse_id)
    out, inc = S.transfer(db, from_wh=data.from_warehouse_id, to_wh=data.to_warehouse_id, product_id=data.product_id,
                          qty=data.qty, date=data.date or Date.today(), note=data.note, user_id=user.id, batch=uuid.uuid4().hex[:12])
    db.commit(); db.refresh(out); db.refresh(inc)
    return [_mv_out(out), _mv_out(inc)]


@router.post("/movements/{mid}/confirm", response_model=MovementOut)
def confirm_transfer(mid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    """Получатель подтверждает перемещение (или директор)."""
    mv = db.get(m.StockMovement, mid)
    if not mv or mv.kind != "transfer_in":
        raise HTTPException(404)
    _check_wh_access(db, user, mv.warehouse_id)
    mv.confirmed = True
    db.commit(); db.refresh(mv)
    return _mv_out(mv)


@router.delete("/movements/{mid}")
def cancel_transfer(mid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    """Отмена неподтверждённого перемещения: товар возвращается отправителю."""
    mv = db.get(m.StockMovement, mid)
    if not mv or mv.kind != "transfer_in" or mv.confirmed:
        raise HTTPException(400, "Отменить можно только неподтверждённое перемещение")
    out = db.get(m.StockMovement, mv.counterpart_id) if mv.counterpart_id else None
    _check_wh_access(db, user, out.warehouse_id if out else mv.warehouse_id)
    db.delete(mv)
    if out:
        db.delete(out)
    db.commit()
    return {"ok": True}


class AdjustIn(BaseModel):
    warehouse_id: int
    lines: list[dict]  # [{product_id, actual_qty}]
    date: Date | None = None
    note: str | None = None


@router.post("/adjust", response_model=list[MovementOut])
def post_adjust(data: AdjustIn, user: m.User = Depends(director), db: Session = Depends(get_db)):
    out = []
    for ln in data.lines:
        mv = S.adjust(db, warehouse_id=data.warehouse_id, product_id=int(ln["product_id"]), actual_qty=Decimal(str(ln["actual_qty"])),
                      date=data.date or Date.today(), note=data.note, user_id=user.id)
        if mv:
            out.append(mv)
    db.commit()
    for mv in out:
        db.refresh(mv)
    return [_mv_out(x) for x in out]


@router.get("/summary")
def summary(_: m.User = Depends(director), db: Session = Depends(get_db)):
    bal = S.all_balances(db)
    whs = {w.id: w for w in db.scalars(select(m.Warehouse)).all()}
    prods = {p.id: p for p in db.scalars(select(m.Product)).all()}
    by_wh = {}
    low = []
    for (wid, pid), (q, c) in bal.items():
        if q <= 0:
            continue
        by_wh.setdefault(wid, Decimal(0)); by_wh[wid] += q * c
        p = prods.get(pid)
        if p and p.min_qty and q < p.min_qty:
            low.append({"warehouse": whs[wid].name if wid in whs else wid, "product": p.name, "qty": q, "min_qty": p.min_qty, "unit": p.unit})
    pending = db.scalars(select(m.StockMovement).where(m.StockMovement.confirmed == False)).all()  # noqa: E712
    return {
        "total_value": S.q2(sum(by_wh.values(), Decimal(0))),
        "by_warehouse": [{"id": wid, "name": whs[wid].name if wid in whs else str(wid), "value": S.q2(v)} for wid, v in by_wh.items()],
        "low": low, "pending_transfers": len(pending),
    }
