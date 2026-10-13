"""Импорт номенклатуры и остатков из выгрузки старой системы (JSON от scripts/import_old_stock.sh).

Структура старых таблиц заранее неизвестна точно, поэтому поля ищутся по нескольким именам.
Повторный запуск безопасен: позиции сопоставляются по названию, остатки не дублируются (проводка kind=import
создаётся только если на складе ещё нет ни одной проводки по позиции).
"""
import json
import sys
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db import SessionLocal
from app import models as m


def pick(row: dict, *names, default=None):
    for n in names:
        if n in row and row[n] not in (None, ""):
            return row[n]
    return default


def main(path: str, target_wh: int | None):
    data = json.load(open(path, encoding="utf-8"))
    db = SessionLocal()
    # ---- склад назначения
    if target_wh:
        wh = db.get(m.Warehouse, target_wh)
    else:
        wh = db.scalar(select(m.Warehouse).where(m.Warehouse.is_active == True).order_by(m.Warehouse.id))  # noqa: E712
    if not wh:
        print("Нет склада в новой системе — заведите прораба/склад и запустите снова"); sys.exit(1)
    print(f"Остатки будут занесены на склад: {wh.name} (id={wh.id})")

    # ---- категории (старые id → новые)
    cat_map: dict = {}
    old_cats = data.get("categories", [])
    # сначала корневые, затем вложенные (несколько проходов)
    pending = list(old_cats)
    for _ in range(10):
        rest = []
        for c in pending:
            old_id = pick(c, "id"); name = pick(c, "name", "title", default="Без названия")
            parent_old = pick(c, "parent_id", "parent")
            if parent_old and parent_old not in cat_map:
                rest.append(c); continue
            parent_new = cat_map.get(parent_old)
            ex = db.scalar(select(m.Category).where(m.Category.name == name, m.Category.parent_id == parent_new))
            if not ex:
                ex = m.Category(name=name, parent_id=parent_new); db.add(ex); db.flush()
            cat_map[old_id] = ex.id
        pending = rest
        if not pending:
            break
    db.commit()
    print(f"Категорий: {len(cat_map)}")

    # ---- позиции
    prod_map: dict = {}
    n_new = 0
    for p in data.get("products", []):
        name = pick(p, "name", "title")
        if not name:
            continue
        unit = pick(p, "unit", "uom", "measure", default="шт")
        ex = db.scalar(select(m.Product).where(m.Product.name == name))
        if not ex:
            ex = m.Product(
                name=name, unit=str(unit)[:20], category_id=cat_map.get(pick(p, "category_id", "category")),
                sku=pick(p, "sku", "article", "code"),
                pack_qty=_dec(pick(p, "pack_qty", "package_qty", "units_per_pack")),
                min_qty=_dec(pick(p, "min_qty", "min_stock", "minimum", "low_stock_threshold")),
                client_price=_dec(pick(p, "sale_price", "client_price", "price")),
                note=pick(p, "description", "note"),
            )
            db.add(ex); db.flush(); n_new += 1
        prod_map[pick(p, "id")] = ex.id
    db.commit()
    print(f"Позиций: {len(prod_map)} (новых {n_new})")

    # ---- остатки → начальная проводка на склад назначения
    n_bal = 0; value = Decimal(0)
    for b in data.get("balances", []):
        pid = prod_map.get(pick(b, "product_id", "product"))
        qty = _dec(pick(b, "qty", "quantity", "balance", "amount"))
        if not pid or not qty or qty <= 0:
            continue
        has = db.scalar(select(m.StockMovement).where(m.StockMovement.product_id == pid, m.StockMovement.warehouse_id == wh.id))
        if has:
            continue
        cost = _dec(pick(b, "avg_cost", "average_cost", "cost", "unit_cost", "purchase_price")) or Decimal(0)
        db.add(m.StockMovement(kind="import", warehouse_id=wh.id, product_id=pid, qty=qty, unit_cost=cost, date=date.today(),
                               note="Перенос из старой системы"))
        n_bal += 1; value += qty * cost
    db.commit()
    print(f"Остатков перенесено: {n_bal}, стоимость {value:.2f} ₽")
    if n_bal and value == 0:
        print("Себестоимость в старой базе не найдена — у перенесённых остатков цена 0; при первом приходе средняя пересчитается.")


def _dec(x):
    if x in (None, ""):
        return None
    try:
        return Decimal(str(x))
    except Exception:
        return None


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else None)
