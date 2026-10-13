"""Складская логика: остатки, средняя себестоимость, проводки."""
from collections import defaultdict
from datetime import date as Date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import MaterialLine, Product, StockMovement, Warehouse

Q2 = Decimal("0.01")
Q3 = Decimal("0.001")


def q2(x) -> Decimal: return Decimal(x or 0).quantize(Q2)
def q3(x) -> Decimal: return Decimal(x or 0).quantize(Q3)


def balance(db: Session, warehouse_id: int, product_id: int) -> tuple[Decimal, Decimal]:
    """(остаток, средняя себестоимость за единицу) по подтверждённым проводкам.
    Средняя = стоимость остатка / остаток; стоимость считаем проводками: приходы по своей цене,
    расходы по средней на момент проводки (unit_cost хранится в каждой проводке)."""
    rows = db.execute(select(StockMovement.qty, StockMovement.unit_cost).where(
        StockMovement.warehouse_id == warehouse_id, StockMovement.product_id == product_id,
        StockMovement.confirmed == True).order_by(StockMovement.date, StockMovement.id)).all()  # noqa: E712
    qty = Decimal(0); value = Decimal(0)
    for mq, uc in rows:
        qty += mq; value += mq * uc
    if qty <= 0:
        return q3(qty), Decimal(0)
    return q3(qty), q2(value / qty)


def all_balances(db: Session, warehouse_id: int | None = None) -> dict[tuple[int, int], tuple[Decimal, Decimal]]:
    """Остатки по всем (склад, позиция) одним проходом."""
    qs = select(StockMovement.warehouse_id, StockMovement.product_id, StockMovement.qty, StockMovement.unit_cost).where(
        StockMovement.confirmed == True).order_by(StockMovement.date, StockMovement.id)  # noqa: E712
    if warehouse_id:
        qs = qs.where(StockMovement.warehouse_id == warehouse_id)
    acc: dict[tuple[int, int], list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for w, p, mq, uc in db.execute(qs):
        a = acc[(w, p)]; a[0] += mq; a[1] += mq * uc
    out = {}
    for k, (qty, value) in acc.items():
        out[k] = (q3(qty), q2(value / qty) if qty > 0 else Decimal(0))
    return out


def client_price(db: Session, p: Product, avg_cost: Decimal) -> Decimal | None:
    """Цена клиенту задаётся вручную у каждой позиции (процентных наценок нет — решение директора)."""
    return q2(p.client_price) if p.client_price is not None else None


def _check_wh(db: Session, warehouse_id: int) -> Warehouse:
    w = db.get(Warehouse, warehouse_id)
    if not w or not w.is_active:
        raise HTTPException(404, "Склад не найден")
    return w


def receipt(db: Session, *, warehouse_id: int, lines: list[dict], date: Date, supplier: str | None, doc_number: str | None,
            note: str | None, user_id: int, batch: str) -> list[StockMovement]:
    """Приход: lines = [{product_id, qty, unit_cost}]."""
    _check_wh(db, warehouse_id)
    out = []
    for ln in lines:
        p = db.get(Product, ln["product_id"])
        if not p:
            raise HTTPException(400, f"Позиция {ln['product_id']} не найдена")
        qty = Decimal(str(ln["qty"]))
        if qty <= 0:
            raise HTTPException(400, f"Количество должно быть больше нуля: {p.name}")
        mv = StockMovement(kind="receipt", warehouse_id=warehouse_id, product_id=p.id, qty=qty,
                           unit_cost=q2(ln.get("unit_cost") or 0), date=date, supplier=supplier, doc_number=doc_number,
                           batch=batch, note=note, user_id=user_id)
        db.add(mv); out.append(mv)
    db.flush()
    return out


def issue(db: Session, *, warehouse_id: int, product_id: int, qty: Decimal, object_id: int, date: Date, note: str | None,
          user_id: int) -> StockMovement:
    """Списание на объект по средней себестоимости; создаёт строку материалов на объекте."""
    _check_wh(db, warehouse_id)
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Позиция не найдена")
    have, avg = balance(db, warehouse_id, product_id)
    if qty <= 0:
        raise HTTPException(400, "Количество должно быть больше нуля")
    if qty > have:
        raise HTTPException(400, f"На складе только {have:g} {p.unit} «{p.name}»")
    mv = StockMovement(kind="issue", warehouse_id=warehouse_id, product_id=product_id, qty=-qty, unit_cost=avg,
                       date=date, object_id=object_id, note=note, user_id=user_id)
    db.add(mv); db.flush()
    db.add(MaterialLine(object_id=object_id, name=p.name, qty=qty, unit=p.unit, cost_sum=q2(qty * avg), date=date,
                        user_id=user_id, movement_id=mv.id))
    db.flush()
    return mv


def return_from_object(db: Session, *, warehouse_id: int, product_id: int, qty: Decimal, object_id: int, date: Date,
                       note: str | None, user_id: int) -> StockMovement:
    """Возврат неиспользованного с объекта: на склад по той же себестоимости, с объекта списывается обратно."""
    _check_wh(db, warehouse_id)
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Позиция не найдена")
    # сколько уходило на этот объект и по какой цене — берём среднюю по списаниям на объект
    rows = db.execute(select(StockMovement.qty, StockMovement.unit_cost).where(
        StockMovement.kind == "issue", StockMovement.object_id == object_id, StockMovement.product_id == product_id)).all()
    issued = -sum((r[0] for r in rows), Decimal(0))
    returned = sum((r[0] for r in db.execute(select(StockMovement.qty).where(
        StockMovement.kind == "return", StockMovement.object_id == object_id, StockMovement.product_id == product_id))), Decimal(0))
    if qty <= 0 or qty > issued - returned:
        raise HTTPException(400, f"На объект уходило {issued - returned:g} {p.unit}, вернуть больше нельзя")
    avg = q2(-sum((r[0] * r[1] for r in rows), Decimal(0)) / issued) if issued else Decimal(0)
    mv = StockMovement(kind="return", warehouse_id=warehouse_id, product_id=product_id, qty=qty, unit_cost=avg,
                       date=date, object_id=object_id, note=note, user_id=user_id)
    db.add(mv); db.flush()
    db.add(MaterialLine(object_id=object_id, name=f"Возврат: {p.name}", qty=-qty, unit=p.unit, cost_sum=-q2(qty * avg),
                        date=date, user_id=user_id, movement_id=mv.id))
    db.flush()
    return mv


def transfer(db: Session, *, from_wh: int, to_wh: int, product_id: int, qty: Decimal, date: Date, note: str | None,
             user_id: int, batch: str) -> tuple[StockMovement, StockMovement]:
    """Перемещение: со склада-отправителя уходит сразу, на склад-получатель — после подтверждения."""
    if from_wh == to_wh:
        raise HTTPException(400, "Склады совпадают")
    _check_wh(db, from_wh); _check_wh(db, to_wh)
    have, avg = balance(db, from_wh, product_id)
    if qty <= 0 or qty > have:
        raise HTTPException(400, f"На складе только {have:g}")
    out = StockMovement(kind="transfer_out", warehouse_id=from_wh, product_id=product_id, qty=-qty, unit_cost=avg,
                        date=date, note=note, user_id=user_id, batch=batch)
    db.add(out); db.flush()
    inc = StockMovement(kind="transfer_in", warehouse_id=to_wh, product_id=product_id, qty=qty, unit_cost=avg,
                        date=date, note=note, user_id=user_id, batch=batch, counterpart_id=out.id, confirmed=False)
    db.add(inc); db.flush()
    out.counterpart_id = inc.id
    db.flush()
    return out, inc


def adjust(db: Session, *, warehouse_id: int, product_id: int, actual_qty: Decimal, date: Date, note: str | None,
           user_id: int) -> StockMovement | None:
    """Инвентаризация: приводит остаток к фактическому, разница — отдельной проводкой."""
    _check_wh(db, warehouse_id)
    have, avg = balance(db, warehouse_id, product_id)
    diff = q3(actual_qty - have)
    if diff == 0:
        return None
    mv = StockMovement(kind="adjust", warehouse_id=warehouse_id, product_id=product_id, qty=diff, unit_cost=avg,
                       date=date, note=note or f"факт {actual_qty:g}, было {have:g}", user_id=user_id)
    db.add(mv); db.flush()
    return mv
