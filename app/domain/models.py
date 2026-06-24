"""Доменные модели фиксируют минимальное ядро рынка без преждевременной БД."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Role(StrEnum):
    """Игровые роли единого рынка."""

    RETAILER = "retailer"
    PRODUCER = "producer"
    DISTRIBUTOR = "distributor"


class ContractType(StrEnum):
    """Типы контрактов, которые нужны для первого игрового цикла."""

    SUPPLY = "supply"
    LOGISTICS = "logistics"


class AssetType(StrEnum):
    """Тип операционного объекта компании."""

    STORE = "store"
    FACTORY = "factory"
    WAREHOUSE = "warehouse"


class StoreFormat(StrEnum):
    """Формат магазина задаёт мощность, расходы и стоимость постройки."""

    KIOSK = "kiosk"
    CONVENIENCE = "convenience"
    SUPERMARKET = "supermarket"


class ContractStatus(StrEnum):
    """Жизненный цикл контракта в прототипе."""

    ACTIVE = "active"
    FULFILLED = "fulfilled"
    BREACHED = "breached"


class Region(BaseModel):
    """Регион задаёт спрос, доходы и логистическую сложность."""

    id: str
    name: str
    description: str
    demand_index: float = Field(ge=0.1)
    income_index: float = Field(ge=0.1)
    logistics_risk: float = Field(ge=0.0, le=1.0)


class Product(BaseModel):
    """Товарная позиция FMCG с базовыми параметрами баланса."""

    id: str
    name: str
    storage: str
    shelf_life_days: int = Field(gt=0)
    base_price_rub: int = Field(gt=0)
    base_daily_demand: int = Field(gt=0)


class RawMaterial(BaseModel):
    """Сырьё ограничивает производство и делает заводскую роль осмысленной."""

    id: str
    name: str
    storage: str
    base_price_rub: int = Field(gt=0)


class RecipeInput(BaseModel):
    """Расход одного вида сырья на единицу готового продукта."""

    raw_material_id: str
    quantity_per_unit: float = Field(gt=0.0)


class ProductionRecipe(BaseModel):
    """Рецептура связывает товар с сырьём и базовой себестоимостью."""

    product_id: str
    inputs: list[RecipeInput]
    conversion_cost_rub: int = Field(ge=0)


class Company(BaseModel):
    """Компания игрока или NPC в первом прототипе."""

    model_config = ConfigDict(use_enum_values=True)

    id: str
    name: str = Field(min_length=2, max_length=60)
    role: Role
    region_id: str
    cash_rub: int
    reputation: float = Field(default=75.0, ge=0.0, le=100.0)
    is_npc: bool = False
    owner_user_id: str | None = None


class BusinessAsset(BaseModel):
    """Операционный объект задаёт реальные мощности роли, а не магические лимиты."""

    model_config = ConfigDict(use_enum_values=True)

    id: str
    company_id: str
    asset_type: AssetType
    name: str
    region_id: str
    capacity_units_per_day: int = Field(gt=0)
    fixed_cost_rub_per_day: int = Field(ge=0)
    storage_type: str
    quality_level: float = Field(default=1.0, ge=0.1, le=2.0)
    store_format: StoreFormat | None = None


class StoreFormatOption(BaseModel):
    """Параметры формата магазина для витрины постройки в интерфейсе."""

    model_config = ConfigDict(use_enum_values=True)

    store_format: StoreFormat
    name: str
    capacity_units_per_day: int = Field(gt=0)
    fixed_cost_rub_per_day: int = Field(ge=0)
    build_cost_rub: int = Field(gt=0)
    storage_type: str


class StoreBuildRequest(BaseModel):
    """Запрос ритейлера на постройку новой торговой точки выбранного формата."""

    store_format: StoreFormat
    name: str | None = Field(default=None, min_length=2, max_length=60)


class StoreUpgradeRequest(BaseModel):
    """Запрос на повышение формата существующего магазина."""

    new_format: StoreFormat


class CompanyCreate(BaseModel):
    """Запрос создания компании для входа нового игрока в рынок."""

    name: str = Field(min_length=2, max_length=60)
    role: Role
    region_id: str


class UserRegister(BaseModel):
    """Регистрация игрока без хранения пароля в публичных ответах."""

    username: str = Field(
        min_length=3, max_length=32, pattern=r"^[A-Za-zА-Яа-яЁё0-9_-]+$"
    )
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    """Вход игрока по имени и паролю."""

    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)


class User(BaseModel):
    """Внутренняя модель пользователя с хешем пароля."""

    id: str
    username: str
    password_hash: str


class PublicUser(BaseModel):
    """Безопасная модель пользователя для API-ответов."""

    id: str
    username: str


class AuthToken(BaseModel):
    """Bearer-токен прототипа для управления своей компанией."""

    access_token: str
    token_type: str = "bearer"
    user: PublicUser


class CompanyDecision(BaseModel):
    """Решения игрока на день с безопасными лимитами прототипа."""

    target_price_index: float = Field(default=1.0, ge=0.65, le=1.6)
    production_units: int = Field(default=1_000, ge=0, le=50_000)
    logistics_capacity_units: int = Field(default=1_000, ge=0, le=50_000)
    marketing_budget_rub: int = Field(default=0, ge=0, le=5_000_000)
    ready: bool = False


class ContractCreate(BaseModel):
    """Формальный оффер между компаниями."""

    contract_type: ContractType
    seller_id: str
    buyer_id: str
    product_id: str
    quantity: int = Field(gt=0, le=1_000_000)
    unit_price_rub: int = Field(gt=0, le=1_000_000)
    due_day: int = Field(gt=0)
    penalty_rub: int = Field(default=0, ge=0, le=100_000_000)

    @field_validator("buyer_id")
    @classmethod
    def parties_must_differ(cls, value: str, info) -> str:
        """Запретить контракт компании самой с собой."""
        seller_id = info.data.get("seller_id")
        if seller_id == value:
            raise ValueError("Покупатель и продавец должны отличаться")
        return value


class Contract(ContractCreate):
    """Контракт хранит факт обязательства и статус исполнения."""

    id: str
    status: ContractStatus = ContractStatus.ACTIVE


class DayResult(BaseModel):
    """Итог расчёта игрового дня по одной компании."""

    day: int
    revenue_rub: int
    costs_rub: int
    profit_rub: int
    sold_units: int
    news: list[str]


class InventoryBatch(BaseModel):
    """Партия товара нужна для FMCG: FIFO, срок годности и качество."""

    id: str
    company_id: str
    product_id: str
    quantity: int = Field(ge=0)
    quality: float = Field(default=1.0, ge=0.0, le=1.0)
    created_day: int = Field(ge=0)
    expires_day: int = Field(gt=0)
    storage: str


class CompanyDayReport(BaseModel):
    """Ролевой отчёт компании после закрытия дня."""

    company_id: str
    revenue_rub: int = 0
    costs_rub: int = 0
    profit_rub: int = 0
    sold_units: int = 0
    produced_units: int = 0
    delivered_units: int = 0
    expired_units: int = 0
    vat_output_rub: int = 0
    vat_input_rub: int = 0
    profit_tax_rub: int = 0


class LedgerEntry(BaseModel):
    """Финансовая проводка сохраняет проверяемый денежный след дня."""

    id: str
    day: int
    company_id: str
    entry_type: str
    amount_rub: int
    description: str


class FinancialReport(BaseModel):
    """Управленческий отчёт компании: P&L, cash-flow и налоговые резервы."""

    company_id: str
    company_name: str
    day: int
    cash_rub: int
    revenue_rub: int
    costs_rub: int
    profit_before_tax_rub: int
    profit_tax_rub: int
    net_profit_rub: int
    vat_output_rub: int
    vat_input_rub: int
    vat_payable_rub: int
    loan_principal_rub: int
    accrued_interest_rub: int
    ledger_entries: list[LedgerEntry]


class DayClosureRequest(BaseModel):
    """Опциональный ключ идемпотентности для безопасного закрытия дня."""

    closure_id: str | None = Field(default=None, min_length=3, max_length=80)


class DayClosureOperation(BaseModel):
    """Одна проверяемая операция расчёта дня для журнала аудита."""

    step: str
    company_id: str | None = None
    amount_rub: int = 0
    quantity: int = 0
    message: str


class WorldDayResult(BaseModel):
    """Итог закрытия дня для всего рынка."""

    day: int
    reports: list[CompanyDayReport]
    news: list[str]
    closure_id: str | None = None
    repeated: bool = False
    operations: list[DayClosureOperation] = Field(default_factory=list)


class DayClosureRecord(BaseModel):
    """Сохранённый результат закрытия дня защищает рынок от дублей."""

    closure_id: str
    target_day: int
    result: WorldDayResult


class Bank(BaseModel):
    """NPC-банк с отдельной кредитной стратегией."""

    id: str
    name: str
    description: str
    annual_rate: float = Field(gt=0.0, le=1.0)
    max_loan_rub: int = Field(gt=0)
    risk_appetite: float = Field(ge=0.0, le=1.0)


class LoanCreate(BaseModel):
    """Запрос кредита компанией у NPC-банка."""

    company_id: str
    bank_id: str
    principal_rub: int = Field(gt=0, le=100_000_000)
    term_days: int = Field(ge=7, le=365)


class Loan(BaseModel):
    """Кредит влияет на cash-flow через ежедневные проценты."""

    id: str
    company_id: str
    bank_id: str
    principal_rub: int
    outstanding_rub: int
    annual_rate: float
    start_day: int
    term_days: int
    accrued_interest_rub: int = 0
    is_defaulted: bool = False


class RatingEntry(BaseModel):
    """Позиция компании в рейтинге рынка."""

    company_id: str
    company_name: str
    role: Role
    score: float
    cash_rub: int
    reputation: float
    last_profit_rub: int
    rank: int


class RatingBoard(BaseModel):
    """Сводный и ролевой рейтинг компаний."""

    day: int
    overall: list[RatingEntry]
    by_role: dict[Role, list[RatingEntry]]


class DemoDaySnapshot(BaseModel):
    """Сводка дня для видимого демо-прогона рынка."""

    day: int
    total_cash_rub: int
    total_profit_rub: int
    sold_units: int
    produced_units: int
    delivered_units: int
    fulfilled_contracts: int
    breached_contracts: int


class DemoRunResult(BaseModel):
    """Результат сценария, который быстро показывает динамику прототипа."""

    days: list[DemoDaySnapshot]
    summary: str


class PersistenceStatus(BaseModel):
    """Статус файлового сохранения прототипа."""

    enabled: bool
    path: str | None = None
    day: int
    companies: int
    contracts: int
    loans: int


class DatabaseStatus(BaseModel):
    """Публичный статус DB-снимка без утечки URL и секретов."""

    enabled: bool
    active: bool
    dialect: str | None = None
    day: int
    companies: int
    contracts: int
    loans: int


class ProjectMilestone(BaseModel):
    """Этап разработки с понятным статусом для владельца продукта."""

    title: str
    status: str = Field(pattern=r"^(done|next|planned)$")
    description: str


class ProjectStatus(BaseModel):
    """Публичный статус разработки игры и ближайшая цель."""

    name: str
    status: str
    current_focus: str
    progress_percent: float = Field(ge=0.0, le=100.0)
    milestones: list[ProjectMilestone]


class PublicGameState(BaseModel):
    """Публичный снимок мира без секретов пользователей и сессий."""

    day: int
    regions: list[Region]
    products: list[Product]
    raw_materials: list[RawMaterial] = Field(default_factory=list)
    production_recipes: list[ProductionRecipe] = Field(default_factory=list)
    companies: list[Company]
    news: list[str]
    contracts: list[Contract] = Field(default_factory=list)
    inventories: dict[str, dict[str, int]] = Field(default_factory=dict)
    raw_inventories: dict[str, dict[str, float]] = Field(default_factory=dict)
    inventory_batches: list[InventoryBatch] = Field(default_factory=list)
    assets: list[BusinessAsset] = Field(default_factory=list)
    decisions: dict[str, CompanyDecision] = Field(default_factory=dict)
    last_reports: list[CompanyDayReport] = Field(default_factory=list)
    banks: list[Bank] = Field(default_factory=list)
    loans: list[Loan] = Field(default_factory=list)
    day_closures: list[DayClosureRecord] = Field(default_factory=list)
    ledger_entries: list[LedgerEntry] = Field(default_factory=list)


class GameState(BaseModel):
    """Внутренний снимок мира, который сохраняется и используется симулятором."""

    day: int
    regions: list[Region]
    products: list[Product]
    raw_materials: list[RawMaterial] = Field(default_factory=list)
    production_recipes: list[ProductionRecipe] = Field(default_factory=list)
    companies: list[Company]
    news: list[str]
    contracts: list[Contract] = Field(default_factory=list)
    inventories: dict[str, dict[str, int]] = Field(default_factory=dict)
    raw_inventories: dict[str, dict[str, float]] = Field(default_factory=dict)
    inventory_batches: list[InventoryBatch] = Field(default_factory=list)
    assets: list[BusinessAsset] = Field(default_factory=list)
    decisions: dict[str, CompanyDecision] = Field(default_factory=dict)
    last_reports: list[CompanyDayReport] = Field(default_factory=list)
    banks: list[Bank] = Field(default_factory=list)
    loans: list[Loan] = Field(default_factory=list)
    day_closures: list[DayClosureRecord] = Field(default_factory=list)
    ledger_entries: list[LedgerEntry] = Field(default_factory=list)
    users: list[User] = Field(default_factory=list)
    sessions: dict[str, str] = Field(default_factory=dict)

    def to_public(self) -> PublicGameState:
        """Вернуть состояние без password hash и bearer-сессий."""
        return PublicGameState(**self.model_dump(exclude={"users", "sessions"}))
