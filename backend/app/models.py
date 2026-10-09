from datetime import date as Date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

Money = Numeric(14, 2)


# ---------- справочники (в коде, чтобы не плодить таблиц в первой версии) ----------

SOURCES = {
    "profi": "профи.ру",
    "site_direct": "сайт · Директ",
    "site_seo": "сайт · поиск",
    "site_other": "сайт · другое",
    "avito": "Авито",
    "yandex_maps": "Яндекс Карты",
    "recommendation": "рекомендация",
    "designer": "дизайнер",
    "renovation": "ремонтная компания",
    "other": "другое",
}

LEAD_STAGES = ["new", "contacted", "measure", "offer_sent", "won", "lost"]
LEAD_STAGE_NAMES = {
    "new": "Новая", "contacted": "Связались", "measure": "Замер",
    "offer_sent": "Смета отправлена", "won": "Договор", "lost": "Проиграна",
}
LOST_REASONS = ["дорого", "не дозвонились", "выбрали других", "передумали делать ремонт", "не наш профиль", "другое"]

OBJECT_STAGES = ["contract", "purchase", "install", "panel", "handover", "act", "warranty"]
OBJECT_STAGE_NAMES = {
    "contract": "Договор", "purchase": "Закупка", "install": "Монтаж", "panel": "Сборка щита",
    "handover": "Сдача", "act": "Акт подписан", "warranty": "Гарантия",
}
TARIFFS = ["Базовый", "Стандарт", "Под ключ"]
PROJECT_KINDS = {"none": "без проекта", "designer": "проект дизайнера", "own": "свой проект"}
PAY_METHODS = {"transfer": "перевод", "cash": "наличные"}

# категория расхода -> (название, тип, канал)
# тип: channel — маркетинг по каналу, marketing — общий маркетинг, staff — персонал, operating — операционные
EXPENSE_CATEGORIES = {
    "direct": ("Яндекс Директ", "channel", "site_direct"),
    "profi": ("профи.ру", "channel", "profi"),
    "avito": ("Авито", "channel", "avito"),
    "yandex_maps": ("Яндекс Карты (продвижение)", "channel", "yandex_maps"),
    "partners": ("Выплаты партнёрам (дизайнеры, ремонтники)", "channel", "designer"),
    "hosting": ("Сервер и хостинг", "marketing", None),
    "domain": ("Домен и сайт", "marketing", None),
    "ai": ("ИИ-сервисы", "marketing", None),
    "content": ("Фото, 3D-туры, контент", "marketing", None),
    "calltracking": ("Коллтрекинг и телефония", "marketing", None),
    "salary": ("Зарплата прораба", "staff", None),
    "staff_other": ("Персонал прочее", "staff", None),
    "tools": ("Инструмент", "operating", None),
    "transport": ("Транспорт", "operating", None),
    "warehouse_rent": ("Аренда склада", "operating", None),
    "accounting": ("Бухгалтерия и банк", "operating", None),
    "taxes": ("Налоги", "operating", None),
    "other": ("Прочее", "operating", None),
}
DOC_KINDS = {
    "offer": "КП", "contract": "Договор", "appendix": "Приложение", "act": "Акт",
    "plan": "План / проект", "photo": "Фото", "tour": "3D-тур", "other": "Другое",
}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(200))
    is_director: Mapped[bool] = mapped_column(Boolean, default=False)
    is_foreman: Mapped[bool] = mapped_column(Boolean, default=False)
    salary: Mapped[Decimal | None] = mapped_column(Money)  # месячная зарплата прораба
    phone: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    crews: Mapped[list["Crew"]] = relationship(back_populates="foreman")


class Crew(Base, TimestampMixin):
    __tablename__ = "crews"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    foreman_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    members_count: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    foreman: Mapped["User | None"] = relationship(back_populates="crews")
    history: Mapped[list["CrewAssignment"]] = relationship(back_populates="crew", order_by="CrewAssignment.id")


class CrewAssignment(Base):
    """История закрепления бригады за прорабом."""
    __tablename__ = "crew_assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    crew_id: Mapped[int] = mapped_column(ForeignKey("crews.id"))
    foreman_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    from_date: Mapped[Date] = mapped_column(Date)
    to_date: Mapped[Date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)

    crew: Mapped["Crew"] = relationship(back_populates="history")
    foreman: Mapped["User | None"] = relationship()


class Lead(Base, TimestampMixin):
    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(String(300))
    area_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 1))
    project_kind: Mapped[str] = mapped_column(String(20), default="none")
    source: Mapped[str] = mapped_column(String(30), index=True)
    lead_cost: Mapped[Decimal] = mapped_column(Money, default=0)
    stage: Mapped[str] = mapped_column(String(20), default="new", index=True)
    lost_reason: Mapped[str | None] = mapped_column(String(100))
    offer_sum: Mapped[Decimal | None] = mapped_column(Money)  # сумма отправленного КП
    tariff: Mapped[str | None] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(Text)
    won_at: Mapped[Date | None] = mapped_column(Date)
    object_id: Mapped[int | None] = mapped_column(ForeignKey("objects.id"))

    activities: Mapped[list["LeadActivity"]] = relationship(back_populates="lead", order_by="LeadActivity.id.desc()", cascade="all, delete-orphan")
    documents: Mapped[list["Document"]] = relationship(back_populates="lead", foreign_keys="Document.lead_id")
    object: Mapped["WorkObject | None"] = relationship(foreign_keys=[object_id])


class LeadActivity(Base):
    __tablename__ = "lead_activities"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"))
    kind: Mapped[str] = mapped_column(String(20))  # call, message, measure, offer, note, stage
    text: Mapped[str] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    lead: Mapped["Lead"] = relationship(back_populates="activities")
    user: Mapped["User | None"] = relationship()


class WorkObject(Base, TimestampMixin):
    __tablename__ = "objects"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(String(300))
    area_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 1))
    tariff: Mapped[str | None] = mapped_column(String(30))
    source: Mapped[str | None] = mapped_column(String(30), index=True)
    stage: Mapped[str] = mapped_column(String(20), default="contract", index=True)
    foreman_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    crew_id: Mapped[int | None] = mapped_column(ForeignKey("crews.id"))
    # кто вёл объект в месяце сделки — на него относится доля зарплаты, даже если бригаду потом переназначили
    salary_foreman_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    start_date: Mapped[Date | None] = mapped_column(Date)
    end_date: Mapped[Date | None] = mapped_column(Date)
    works_sum: Mapped[Decimal] = mapped_column(Money, default=0)            # работы по смете
    materials_client_sum: Mapped[Decimal] = mapped_column(Money, default=0)  # материалы для клиента по смете
    note: Mapped[str | None] = mapped_column(Text)
    contract_number: Mapped[str | None] = mapped_column(String(50))

    foreman: Mapped["User | None"] = relationship(foreign_keys=[foreman_id])
    crew: Mapped["Crew | None"] = relationship()
    payments: Mapped[list["Payment"]] = relationship(back_populates="object", cascade="all, delete-orphan", order_by="Payment.date")
    payouts: Mapped[list["CrewPayout"]] = relationship(back_populates="object", cascade="all, delete-orphan", order_by="CrewPayout.date")
    extra_works: Mapped[list["ExtraWork"]] = relationship(back_populates="object", cascade="all, delete-orphan")
    materials: Mapped[list["MaterialLine"]] = relationship(back_populates="object", cascade="all, delete-orphan")
    documents: Mapped[list["Document"]] = relationship(back_populates="object", foreign_keys="Document.object_id", order_by="Document.id.desc()")
    stage_log: Mapped[list["ObjectStageLog"]] = relationship(back_populates="object", cascade="all, delete-orphan", order_by="ObjectStageLog.id")


class ObjectStageLog(Base):
    __tablename__ = "object_stage_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"))
    stage: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    object: Mapped["WorkObject"] = relationship(back_populates="stage_log")


class ExtraWork(Base):
    """Дополнительные работы, оплаченные клиентом; входят в базу для доли бригады."""
    __tablename__ = "extra_works"
    id: Mapped[int] = mapped_column(primary_key=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"))
    title: Mapped[str] = mapped_column(String(300))
    amount: Mapped[Decimal] = mapped_column(Money)
    date: Mapped[Date | None] = mapped_column(Date)
    object: Mapped["WorkObject"] = relationship(back_populates="extra_works")


class MaterialLine(Base):
    """Материалы, ушедшие на объект (первая версия — суммами; позже заменяется складскими списаниями)."""
    __tablename__ = "material_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"))
    name: Mapped[str] = mapped_column(String(300))
    qty: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    unit: Mapped[str | None] = mapped_column(String(20))
    cost_sum: Mapped[Decimal] = mapped_column(Money, default=0)  # себестоимость, итого
    date: Mapped[Date | None] = mapped_column(Date)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    object: Mapped["WorkObject"] = relationship(back_populates="materials")


class Payment(Base):
    """Платёж клиента по договору."""
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"))
    number: Mapped[int] = mapped_column(Integer, default=1)  # 1 — до старта, 2 — после сдачи, 3+ — доп.
    amount: Mapped[Decimal] = mapped_column(Money)
    date: Mapped[Date] = mapped_column(Date)
    method: Mapped[str] = mapped_column(String(20), default="transfer")
    note: Mapped[str | None] = mapped_column(Text)
    object: Mapped["WorkObject"] = relationship(back_populates="payments")


class CrewPayout(Base):
    """Выплата бригаде по объекту (через прораба)."""
    __tablename__ = "crew_payouts"
    id: Mapped[int] = mapped_column(primary_key=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"))
    crew_id: Mapped[int | None] = mapped_column(ForeignKey("crews.id"))
    foreman_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[Decimal] = mapped_column(Money)
    date: Mapped[Date] = mapped_column(Date)
    method: Mapped[str] = mapped_column(String(20), default="transfer")
    note: Mapped[str | None] = mapped_column(Text)
    object: Mapped["WorkObject"] = relationship(back_populates="payouts")
    crew: Mapped["Crew | None"] = relationship()
    foreman: Mapped["User | None"] = relationship()


class Expense(Base, TimestampMixin):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[Date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    category: Mapped[str] = mapped_column(String(30), index=True)
    channel: Mapped[str | None] = mapped_column(String(30))     # источник, если расход по каналу
    foreman_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # для зарплаты
    period: Mapped[str | None] = mapped_column(String(7))       # YYYY-MM, за какой месяц (зарплата)
    method: Mapped[str | None] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    foreman: Mapped["User | None"] = relationship(foreign_keys=[foreman_id])


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), index=True)
    object_id: Mapped[int | None] = mapped_column(ForeignKey("objects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="other")
    title: Mapped[str] = mapped_column(String(300))
    filename: Mapped[str] = mapped_column(String(300))
    path: Mapped[str] = mapped_column(String(500))
    mime: Mapped[str | None] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer, default=0)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    lead: Mapped["Lead | None"] = relationship(back_populates="documents", foreign_keys=[lead_id])
    object: Mapped["WorkObject | None"] = relationship(back_populates="documents", foreign_keys=[object_id])
    user: Mapped["User | None"] = relationship()
