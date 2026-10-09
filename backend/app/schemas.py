from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth / users ----------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORM):
    id: int
    email: str
    name: str
    phone: str | None = None
    is_director: bool
    is_foreman: bool
    salary: Decimal | None = None
    is_active: bool


class UserCreate(BaseModel):
    email: str
    name: str
    password: str = Field(min_length=6)
    phone: str | None = None
    is_director: bool = False
    is_foreman: bool = True
    salary: Decimal | None = None


class UserUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    password: str | None = Field(default=None, min_length=6)
    is_director: bool | None = None
    is_foreman: bool | None = None
    salary: Decimal | None = None
    is_active: bool | None = None


# ---------- crews ----------
class CrewAssignmentOut(ORM):
    id: int
    foreman_id: int | None
    foreman_name: str | None = None
    from_date: date
    to_date: date | None
    note: str | None


class CrewOut(ORM):
    id: int
    name: str
    foreman_id: int | None
    foreman_name: str | None = None
    members_count: int | None
    note: str | None
    is_active: bool
    history: list[CrewAssignmentOut] = []


class CrewCreate(BaseModel):
    name: str
    foreman_id: int | None = None
    members_count: int | None = None
    note: str | None = None


class CrewUpdate(BaseModel):
    name: str | None = None
    members_count: int | None = None
    note: str | None = None
    is_active: bool | None = None


class CrewReassign(BaseModel):
    foreman_id: int
    note: str | None = None
    move_objects: bool = True  # перевести объекты в работе на нового прораба


# ---------- documents ----------
class DocumentOut(ORM):
    id: int
    lead_id: int | None
    object_id: int | None
    kind: str
    title: str
    filename: str
    mime: str | None
    size: int
    created_at: datetime


# ---------- leads ----------
class ActivityOut(ORM):
    id: int
    kind: str
    text: str
    user_name: str | None = None
    created_at: datetime


class ActivityCreate(BaseModel):
    kind: str = "note"
    text: str


class LeadBase(BaseModel):
    name: str
    phone: str | None = None
    address: str | None = None
    area_m2: Decimal | None = None
    project_kind: str = "none"
    source: str
    lead_cost: Decimal = Decimal(0)
    tariff: str | None = None
    offer_sum: Decimal | None = None
    note: str | None = None


class LeadCreate(LeadBase):
    pass


class LeadUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    address: str | None = None
    area_m2: Decimal | None = None
    project_kind: str | None = None
    source: str | None = None
    lead_cost: Decimal | None = None
    tariff: str | None = None
    offer_sum: Decimal | None = None
    note: str | None = None


class LeadStage(BaseModel):
    stage: str
    lost_reason: str | None = None
    comment: str | None = None


class LeadOut(ORM):
    id: int
    name: str
    phone: str | None
    address: str | None
    area_m2: Decimal | None
    project_kind: str
    source: str
    lead_cost: Decimal
    stage: str
    lost_reason: str | None
    offer_sum: Decimal | None
    tariff: str | None
    note: str | None
    won_at: date | None
    object_id: int | None
    created_at: datetime
    updated_at: datetime


class LeadDetail(LeadOut):
    activities: list[ActivityOut] = []
    documents: list[DocumentOut] = []


class LeadConvert(BaseModel):
    works_sum: Decimal
    materials_client_sum: Decimal = Decimal(0)
    tariff: str | None = None
    foreman_id: int | None = None
    start_date: date | None = None
    contract_number: str | None = None


# ---------- objects ----------
class PaymentIn(BaseModel):
    number: int = 1
    amount: Decimal
    date: date
    method: str = "transfer"
    note: str | None = None


class PaymentOut(ORM, PaymentIn):
    id: int


class PayoutIn(BaseModel):
    amount: Decimal
    date: date
    method: str = "transfer"
    note: str | None = None


class PayoutOut(ORM, PayoutIn):
    id: int
    crew_id: int | None
    foreman_id: int | None


class ExtraWorkIn(BaseModel):
    title: str
    amount: Decimal
    date: date | None = None


class ExtraWorkOut(ORM, ExtraWorkIn):
    id: int


class MaterialIn(BaseModel):
    name: str
    qty: Decimal | None = None
    unit: str | None = None
    cost_sum: Decimal
    date: date | None = None


class MaterialOut(ORM, MaterialIn):
    id: int


class StageLogOut(ORM):
    id: int
    stage: str
    created_at: datetime


class ObjectCreate(BaseModel):
    client_name: str
    phone: str | None = None
    address: str | None = None
    area_m2: Decimal | None = None
    tariff: str | None = None
    source: str | None = None
    foreman_id: int | None = None
    start_date: date | None = None
    works_sum: Decimal = Decimal(0)
    materials_client_sum: Decimal = Decimal(0)
    contract_number: str | None = None
    note: str | None = None


class ObjectUpdate(BaseModel):
    client_name: str | None = None
    phone: str | None = None
    address: str | None = None
    area_m2: Decimal | None = None
    tariff: str | None = None
    source: str | None = None
    foreman_id: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    works_sum: Decimal | None = None
    materials_client_sum: Decimal | None = None
    contract_number: str | None = None
    note: str | None = None


class ObjectStage(BaseModel):
    stage: str


class Finance(BaseModel):
    """Деньги объекта. Для прораба отдаётся усечённая версия."""
    works_sum: Decimal
    extra_works_sum: Decimal
    works_base: Decimal                 # работы + доп. работы — база для доли бригады
    materials_client_sum: Decimal
    contract_total: Decimal
    received: Decimal
    receivable: Decimal
    crew_share: Decimal                 # доля, напр. 0.55
    crew_plan: Decimal
    crew_paid: Decimal
    crew_due: Decimal
    crew_share_actual: Decimal | None   # фактическая доля выплат от базы работ
    materials_cost: Decimal | None = None
    materials_markup: Decimal | None = None
    foreman_share: Decimal | None = None
    foreman_objects_in_month: int | None = None
    client_cost: Decimal | None = None
    profit: Decimal | None = None
    margin: Decimal | None = None


class ObjectOut(ORM):
    id: int
    client_name: str
    phone: str | None
    address: str | None
    area_m2: Decimal | None
    tariff: str | None
    source: str | None
    stage: str
    foreman_id: int | None
    foreman_name: str | None = None
    crew_id: int | None
    crew_name: str | None = None
    start_date: date | None
    end_date: date | None
    contract_number: str | None
    note: str | None
    created_at: datetime
    finance: Finance | None = None


class ObjectDetail(ObjectOut):
    payments: list[PaymentOut] = []
    payouts: list[PayoutOut] = []
    extra_works: list[ExtraWorkOut] = []
    materials: list[MaterialOut] = []
    documents: list[DocumentOut] = []
    stage_log: list[StageLogOut] = []


# ---------- expenses ----------
class ExpenseIn(BaseModel):
    date: date
    amount: Decimal
    category: str
    foreman_id: int | None = None
    period: str | None = None
    method: str | None = None
    note: str | None = None


class ExpenseOut(ORM, ExpenseIn):
    id: int
    channel: str | None
    foreman_name: str | None = None
    created_at: datetime


# ---------- stats ----------
class ChannelStat(BaseModel):
    source: str
    name: str
    spent: Decimal
    leads: int
    contacted: int
    measured: int
    offered: int
    won: int
    lost: int
    cost_per_lead: Decimal | None
    cost_per_client: Decimal | None
    revenue: Decimal
    profit: Decimal
    avg_check: Decimal | None


class ForemanStat(BaseModel):
    id: int
    name: str
    salary: Decimal | None
    objects_total: int
    objects_in_month: int
    salary_per_object: Decimal | None
    crew_accrued: Decimal
    crew_paid: Decimal
    crew_due: Decimal
    salary_paid: Decimal


class Dictionaries(BaseModel):
    sources: dict[str, str]
    lead_stages: list[str]
    lead_stage_names: dict[str, str]
    lost_reasons: list[str]
    object_stages: list[str]
    object_stage_names: dict[str, str]
    tariffs: list[str]
    project_kinds: dict[str, str]
    pay_methods: dict[str, str]
    expense_categories: dict[str, dict]
    doc_kinds: dict[str, str]
    crew_share: Decimal
