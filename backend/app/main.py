import os

from fastapi import FastAPI
from sqlalchemy import select

from . import models as m
from .auth import hash_password
from .config import settings
from .db import Base, SessionLocal, engine
from .avito import review as avito_review
from .avito.router import router as avito_router
from .routers import auth, crews, documents, expenses, leads, objects, stats, stock

app = FastAPI(title="ВольтЛиния CRM", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

for r in (auth.router, leads.router, objects.router, crews.router, expenses.router, documents.router, stats.router, stock.router,
          avito_router):
    app.include_router(r)

# Версия сборки: deploy.sh кладёт короткий хеш коммита в APP_VERSION. Фронт сравнивает заголовок
# в каждом ответе и перезагружает страницу, если на сервере вышло обновление (SPA иначе живёт со старым JS неделями).
import time as _time
APP_VERSION = os.environ.get("APP_VERSION") or f"dev-{int(_time.time())}"


@app.middleware("http")
async def add_version(request, call_next):
    resp = await call_next(request)
    resp.headers["X-App-Version"] = APP_VERSION
    return resp


@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    migrate()
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    if settings.ADMIN_EMAIL and settings.ADMIN_PASSWORD:
        with SessionLocal() as db:
            if not db.scalar(select(m.User).where(m.User.email == settings.ADMIN_EMAIL.lower())):
                u = m.User(email=settings.ADMIN_EMAIL.lower(), name=settings.ADMIN_NAME,
                           password_hash=hash_password(settings.ADMIN_PASSWORD), is_director=True, is_foreman=True)
                db.add(u); db.flush()
                db.add(m.Warehouse(name=f"Склад {u.name}", foreman_id=u.id))
                db.commit()
            # склады для прорабов, созданных до появления складского модуля
            for u in db.scalars(select(m.User).where(m.User.is_foreman == True, m.User.is_active == True)).all():  # noqa: E712
                if not db.scalar(select(m.Warehouse).where(m.Warehouse.foreman_id == u.id)):
                    db.add(m.Warehouse(name=f"Склад {u.name}", foreman_id=u.id))
            db.commit()
    avito_review.start_scheduler()


def migrate():
    """Добавляет новые колонки в существующие таблицы (create_all этого не делает)."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    wanted = {
        "objects": [("crew_sum_override", "NUMERIC(14,2)"), ("salary_foreman_id", "INTEGER")],
        "material_lines": [("movement_id", "INTEGER")],
    }
    with engine.begin() as conn:
        for table, cols in wanted.items():
            if table not in insp.get_table_names():
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for name, typ in cols:
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {typ}"))


@app.get("/api/health")
def health():
    return {"ok": True, "version": APP_VERSION}
