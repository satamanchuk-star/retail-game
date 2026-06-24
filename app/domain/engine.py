"""Игровой движок закрывает день единообразно для трёх ролей рынка."""

from copy import deepcopy
from uuid import uuid4

from app.domain.balance import (
    BANKS,
    INITIAL_ASSETS,
    INITIAL_INVENTORIES,
    INITIAL_RAW_INVENTORIES,
    PRODUCTION_RECIPES,
    PRODUCTS,
    RAW_MATERIALS,
    REGIONS,
    STARTER_COMPANIES,
)
from app.domain.models import (
    AssetType,
    BusinessAsset,
    Company,
    CompanyCreate,
    CompanyDayReport,
    CompanyDecision,
    Contract,
    ContractCreate,
    ContractStatus,
    DayClosureOperation,
    DayClosureRecord,
    FinancialReport,
    GameState,
    InventoryBatch,
    LedgerEntry,
    Loan,
    LoanCreate,
    ProductionRecipe,
    RawMaterial,
    Region,
    Role,
    WorldDayResult,
)

VAT_RATE = 0.20
PROFIT_TAX_RATE = 0.20

STARTING_CASH_BY_ROLE: dict[Role, int] = {
    Role.RETAILER: 7_500_000,
    Role.PRODUCER: 35_000_000,
    Role.DISTRIBUTOR: 22_000_000,
}


def build_initial_state() -> GameState:
    """Создать независимый стартовый мир для приложения или теста."""
    return GameState(
        day=0,
        regions=deepcopy(REGIONS),
        products=deepcopy(PRODUCTS),
        raw_materials=deepcopy(RAW_MATERIALS),
        production_recipes=deepcopy(PRODUCTION_RECIPES),
        companies=deepcopy(STARTER_COMPANIES),
        assets=deepcopy(INITIAL_ASSETS),
        news=["Добро пожаловать в «Цепочку прибыли»: живой рынок запускается."],
        inventories=deepcopy(INITIAL_INVENTORIES),
        raw_inventories=deepcopy(INITIAL_RAW_INVENTORIES),
        banks=deepcopy(BANKS),
    )


class GameEngine:
    """Минимальный движок рынка с явными операциями для API и тестов."""

    def __init__(self, state: GameState) -> None:
        self.state = state
        self._ensure_production_balance()
        self._ensure_company_assets()
        self._ensure_company_inventories()
        self._ensure_inventory_batches()

    def _ensure_production_balance(self) -> None:
        """Поддержать старые snapshot-ы без сырья и рецептур."""
        if not self.state.raw_materials:
            self.state.raw_materials = deepcopy(RAW_MATERIALS)
        if not self.state.production_recipes:
            self.state.production_recipes = deepcopy(PRODUCTION_RECIPES)
        for company in self.state.companies:
            if company.role != Role.PRODUCER:
                continue
            self.state.raw_inventories.setdefault(
                company.id, self._starting_raw_inventory()
            )

    def create_company(
        self, payload: CompanyCreate, owner_user_id: str | None = None
    ) -> Company:
        """Добавить новую компанию с ролью, регионом и стартовым капиталом."""
        self._require_region(payload.region_id)
        company = Company(
            id=f"company_{uuid4().hex[:10]}",
            name=payload.name,
            role=payload.role,
            region_id=payload.region_id,
            cash_rub=STARTING_CASH_BY_ROLE[payload.role],
            owner_user_id=owner_user_id,
        )
        self.state.companies.append(company)
        self.state.inventories[company.id] = self._starting_inventory(company.role)
        self.state.assets.append(self._starting_asset(company))
        self._create_batches_from_inventory(
            company.id, self.state.inventories[company.id]
        )
        self.state.news.insert(0, f"На рынок вышла компания «{company.name}».")
        if company.role == Role.PRODUCER:
            self.state.raw_inventories[company.id] = self._starting_raw_inventory()
        return company

    def set_decision(
        self, company_id: str, decision: CompanyDecision
    ) -> CompanyDecision:
        """Сохранить решения компании на следующий день."""
        self._require_company(company_id)
        self.state.decisions[company_id] = decision
        return decision

    def issue_loan(self, payload: LoanCreate) -> Loan:
        """Выдать кредит компании, если банк и лимит позволяют."""
        company = self._require_company(payload.company_id)
        bank = next(
            (item for item in self.state.banks if item.id == payload.bank_id), None
        )
        if bank is None:
            raise ValueError("Банк не найден")
        if payload.principal_rub > bank.max_loan_rub:
            raise ValueError("Сумма превышает лимит банка")

        loan = Loan(
            id=f"loan_{uuid4().hex[:10]}",
            company_id=company.id,
            bank_id=bank.id,
            principal_rub=payload.principal_rub,
            outstanding_rub=payload.principal_rub,
            annual_rate=bank.annual_rate,
            start_day=self.state.day,
            term_days=payload.term_days,
        )
        self.state.loans.append(loan)
        company.cash_rub += payload.principal_rub
        self.state.news.insert(
            0, f"Компания «{company.name}» получила кредит в банке «{bank.name}»."
        )
        return loan

    def create_contract(self, payload: ContractCreate) -> Contract:
        """Создать активный контракт между компаниями."""
        self._require_company(payload.seller_id)
        self._require_company(payload.buyer_id)
        self._require_product(payload.product_id)
        if payload.due_day <= self.state.day:
            raise ValueError("Срок контракта должен быть в будущем")

        contract = Contract(id=f"contract_{uuid4().hex[:10]}", **payload.model_dump())
        self.state.contracts.append(contract)
        self.state.news.insert(0, "Заключён новый формальный контракт поставки.")
        return contract

    def build_financial_report(self, company_id: str) -> FinancialReport:
        """Собрать P&L, cash-flow и налоговый срез компании на текущий день."""
        company = self._require_company(company_id)
        report = next(
            (item for item in self.state.last_reports if item.company_id == company_id),
            CompanyDayReport(company_id=company_id),
        )
        company_loans = [
            loan for loan in self.state.loans if loan.company_id == company_id
        ]
        ledger_entries = [
            entry
            for entry in self.state.ledger_entries
            if entry.company_id == company_id
        ][-50:]
        return FinancialReport(
            company_id=company.id,
            company_name=company.name,
            day=self.state.day,
            cash_rub=company.cash_rub,
            revenue_rub=report.revenue_rub,
            costs_rub=report.costs_rub,
            profit_before_tax_rub=report.revenue_rub
            - report.costs_rub
            + report.profit_tax_rub,
            profit_tax_rub=report.profit_tax_rub,
            net_profit_rub=report.profit_rub,
            vat_output_rub=report.vat_output_rub,
            vat_input_rub=report.vat_input_rub,
            vat_payable_rub=max(0, report.vat_output_rub - report.vat_input_rub),
            loan_principal_rub=sum(loan.outstanding_rub for loan in company_loans),
            accrued_interest_rub=sum(
                loan.accrued_interest_rub for loan in company_loans
            ),
            ledger_entries=ledger_entries,
        )

    def close_day(self, closure_id: str | None = None) -> WorldDayResult:
        """Закрыть день один раз, а при повторе вернуть сохранённый результат."""
        if closure_id:
            existing = next(
                (
                    item
                    for item in self.state.day_closures
                    if item.closure_id == closure_id
                ),
                None,
            )
            if existing is not None:
                repeated = existing.result.model_copy(deep=True)
                repeated.repeated = True
                return repeated

        operations: list[DayClosureOperation] = []
        reports_by_company = {
            company.id: CompanyDayReport(company_id=company.id)
            for company in self.state.companies
        }
        news: list[str] = []

        self._expire_inventory_batches(reports_by_company, operations)
        self._apply_production(reports_by_company, operations)
        self._apply_due_contracts(reports_by_company, news, operations)
        self._apply_retail_sales(reports_by_company, operations)
        self._apply_logistics_income(reports_by_company, operations)
        self._apply_loan_interest(reports_by_company, operations)
        self._apply_financial_accounting(reports_by_company, operations)

        for company in self.state.companies:
            report = reports_by_company[company.id]
            company.cash_rub += report.profit_rub

        self.state.day += 1
        self.state.last_reports = list(reports_by_company.values())
        news.insert(0, f"День {self.state.day}: рынок закрыл операционный цикл.")
        self.state.news = news + self.state.news[:8]
        result = WorldDayResult(
            day=self.state.day,
            reports=self.state.last_reports,
            news=news,
            closure_id=closure_id,
            operations=operations,
        )
        if closure_id:
            self.state.day_closures.append(
                DayClosureRecord(
                    closure_id=closure_id,
                    target_day=self.state.day,
                    result=result.model_copy(deep=True),
                )
            )
        return result

    def _ensure_company_assets(self) -> None:
        """Добавить базовые операционные объекты старым состояниям без assets."""
        existing_company_ids = {asset.company_id for asset in self.state.assets}
        for company in self.state.companies:
            if company.id in existing_company_ids:
                continue
            self.state.assets.append(self._starting_asset(company))

    def _starting_asset(self, company: Company) -> BusinessAsset:
        """Создать минимальный объект роли при входе компании на рынок."""
        if company.role == Role.RETAILER:
            return BusinessAsset(
                id=f"asset_{uuid4().hex[:10]}",
                company_id=company.id,
                asset_type=AssetType.STORE,
                name=f"Магазин «{company.name}»",
                region_id=company.region_id,
                capacity_units_per_day=1_800,
                fixed_cost_rub_per_day=75_000,
                storage_type="смешанное",
                quality_level=1.0,
            )
        if company.role == Role.PRODUCER:
            return BusinessAsset(
                id=f"asset_{uuid4().hex[:10]}",
                company_id=company.id,
                asset_type=AssetType.FACTORY,
                name=f"Завод «{company.name}»",
                region_id=company.region_id,
                capacity_units_per_day=2_500,
                fixed_cost_rub_per_day=125_000,
                storage_type="производство",
                quality_level=1.0,
            )
        return BusinessAsset(
            id=f"asset_{uuid4().hex[:10]}",
            company_id=company.id,
            asset_type=AssetType.WAREHOUSE,
            name=f"Склад «{company.name}»",
            region_id=company.region_id,
            capacity_units_per_day=3_000,
            fixed_cost_rub_per_day=40_000,
            storage_type="смешанное",
            quality_level=1.0,
        )

    def _company_assets(
        self, company_id: str, asset_type: AssetType
    ) -> list[BusinessAsset]:
        """Вернуть объекты компании нужного типа."""
        return [
            asset
            for asset in self.state.assets
            if asset.company_id == company_id and asset.asset_type == asset_type
        ]

    def _daily_capacity(
        self, company_id: str, asset_type: AssetType, fallback: int
    ) -> int:
        """Посчитать дневную мощность роли через объекты с безопасным fallback."""
        assets = self._company_assets(company_id, asset_type)
        if not assets:
            return fallback
        return sum(asset.capacity_units_per_day for asset in assets)

    def _fixed_costs(
        self, company_id: str, asset_type: AssetType, fallback: int
    ) -> int:
        """Посчитать постоянные расходы объектов роли."""
        assets = self._company_assets(company_id, asset_type)
        if not assets:
            return fallback
        return sum(asset.fixed_cost_rub_per_day for asset in assets)

    def _ensure_company_inventories(self) -> None:
        """Добавить стартовые остатки старым состояниям без поля inventories."""
        for company in self.state.companies:
            if company.id not in self.state.inventories:
                self.state.inventories[company.id] = self._starting_inventory(
                    company.role
                )

    def _ensure_inventory_batches(self) -> None:
        """Создать партии для старых snapshot-ов с простыми остатками."""
        if self.state.inventory_batches:
            self._sync_legacy_inventories()
            return
        for company_id, inventory in list(self.state.inventories.items()):
            self._create_batches_from_inventory(company_id, inventory)
        self._sync_legacy_inventories()

    def _create_batches_from_inventory(
        self, company_id: str, inventory: dict[str, int]
    ) -> None:
        """Преобразовать простые остатки компании в свежие партии."""
        product_by_id = {product.id: product for product in self.state.products}
        existing = {
            (batch.company_id, batch.product_id)
            for batch in self.state.inventory_batches
            if batch.company_id == company_id
        }
        for product_id, quantity in inventory.items():
            if quantity <= 0 or (company_id, product_id) in existing:
                continue
            product = product_by_id.get(product_id)
            if product is None:
                continue
            self._add_inventory_batch(
                company_id=company_id,
                product_id=product_id,
                quantity=quantity,
                quality=1.0,
                created_day=self.state.day,
            )

    def _add_inventory_batch(
        self,
        *,
        company_id: str,
        product_id: str,
        quantity: int,
        quality: float,
        created_day: int,
    ) -> InventoryBatch:
        """Добавить партию и сохранить срок годности товара."""
        product = self._get_product(product_id)
        batch = InventoryBatch(
            id=f"batch_{uuid4().hex[:10]}",
            company_id=company_id,
            product_id=product_id,
            quantity=quantity,
            quality=quality,
            created_day=created_day,
            expires_day=created_day + product.shelf_life_days,
            storage=product.storage,
        )
        self.state.inventory_batches.append(batch)
        self._sync_legacy_inventories()
        return batch

    def _consume_fifo(self, company_id: str, product_id: str, quantity: int) -> int:
        """Списать товар FIFO и вернуть реально списанное количество."""
        remaining = quantity
        consumed = 0
        batches = sorted(
            [
                batch
                for batch in self.state.inventory_batches
                if batch.company_id == company_id
                and batch.product_id == product_id
                and batch.quantity > 0
            ],
            key=lambda batch: (batch.expires_day, batch.created_day, batch.id),
        )
        for batch in batches:
            if remaining <= 0:
                break
            take = min(batch.quantity, remaining)
            batch.quantity -= take
            remaining -= take
            consumed += take
        self._prune_empty_batches()
        self._sync_legacy_inventories()
        return consumed

    def _transfer_fifo(
        self, seller_id: str, buyer_id: str, product_id: str, quantity: int
    ) -> int:
        """Перенести товар покупателю FIFO с сохранением срока годности и качества."""
        remaining = quantity
        transferred = 0
        batches = sorted(
            [
                batch
                for batch in self.state.inventory_batches
                if batch.company_id == seller_id
                and batch.product_id == product_id
                and batch.quantity > 0
            ],
            key=lambda batch: (batch.expires_day, batch.created_day, batch.id),
        )
        for batch in batches:
            if remaining <= 0:
                break
            take = min(batch.quantity, remaining)
            batch.quantity -= take
            transferred += take
            remaining -= take
            self.state.inventory_batches.append(
                InventoryBatch(
                    id=f"batch_{uuid4().hex[:10]}",
                    company_id=buyer_id,
                    product_id=product_id,
                    quantity=take,
                    quality=batch.quality,
                    created_day=batch.created_day,
                    expires_day=batch.expires_day,
                    storage=batch.storage,
                )
            )
        self._prune_empty_batches()
        self._sync_legacy_inventories()
        return transferred

    def _expire_inventory_batches(
        self,
        reports: dict[str, CompanyDayReport],
        operations: list[DayClosureOperation],
    ) -> None:
        """Списать просроченные партии до продаж и поставок."""
        closing_day = self.state.day + 1
        for batch in list(self.state.inventory_batches):
            if batch.quantity <= 0 or batch.expires_day > closing_day:
                continue
            expired = batch.quantity
            batch.quantity = 0
            if batch.company_id in reports:
                reports[batch.company_id].expired_units += expired
            operations.append(
                DayClosureOperation(
                    step="inventory_expired",
                    company_id=batch.company_id,
                    quantity=expired,
                    message=f"Списано {expired} ед. просроченного товара {batch.product_id}.",
                )
            )
        self._prune_empty_batches()
        self._sync_legacy_inventories()

    def _prune_empty_batches(self) -> None:
        """Удалить пустые партии, чтобы snapshot не разрастался мусором."""
        self.state.inventory_batches = [
            batch for batch in self.state.inventory_batches if batch.quantity > 0
        ]

    def _sync_legacy_inventories(self) -> None:
        """Поддержать старое поле inventories для API и обратной совместимости."""
        previous_keys = {
            company_id: set(inventory.keys())
            for company_id, inventory in self.state.inventories.items()
        }
        synced: dict[str, dict[str, int]] = {
            company.id: {
                product_id: 0 for product_id in previous_keys.get(company.id, set())
            }
            for company in self.state.companies
        }
        for batch in self.state.inventory_batches:
            if batch.quantity <= 0:
                continue
            company_inventory = synced.setdefault(batch.company_id, {})
            company_inventory[batch.product_id] = (
                company_inventory.get(batch.product_id, 0) + batch.quantity
            )
        self.state.inventories = synced

    def _apply_production(
        self,
        reports: dict[str, CompanyDayReport],
        operations: list[DayClosureOperation],
    ) -> None:
        recipe = self._get_default_recipe()
        product = self._get_product(recipe.product_id)
        raw_by_id = {material.id: material for material in self.state.raw_materials}
        for company in self.state.companies:
            if company.role != Role.PRODUCER:
                continue
            raw_inventory = self.state.raw_inventories.setdefault(
                company.id, self._starting_raw_inventory()
            )
            decision = self.state.decisions.get(company.id, CompanyDecision())
            requested = min(
                decision.production_units,
                self._daily_capacity(company.id, AssetType.FACTORY, 0),
            )
            max_by_raw = self._max_production_by_raw(recipe, raw_inventory)
            produced = min(requested, max_by_raw)
            if requested and produced < requested:
                operations.append(
                    DayClosureOperation(
                        step="raw_material_shortage",
                        company_id=company.id,
                        quantity=requested - produced,
                        message=(
                            f"Не хватило сырья для {requested - produced} ед. "
                            f"товара {product.name}."
                        ),
                    )
                )
            if produced:
                self._consume_raw_materials(recipe, raw_inventory, produced)
            unit_cost = self._recipe_unit_cost(recipe, raw_by_id)
            if produced:
                self._add_inventory_batch(
                    company_id=company.id,
                    product_id=product.id,
                    quantity=produced,
                    quality=0.98,
                    created_day=self.state.day + 1,
                )
            reports[company.id].produced_units += produced
            reports[company.id].costs_rub += produced * unit_cost
            reports[company.id].profit_rub -= produced * unit_cost
            if produced:
                operations.append(
                    DayClosureOperation(
                        step="production",
                        company_id=company.id,
                        amount_rub=produced * unit_cost,
                        quantity=produced,
                        message=f"Произведено {produced} ед. товара {product.name}.",
                    )
                )

    def _get_default_recipe(self) -> ProductionRecipe:
        """Выбрать минимальную стартовую рецептуру для текущего прототипа."""
        recipe = next(
            (
                item
                for item in self.state.production_recipes
                if item.product_id == "bread"
            ),
            None,
        )
        if recipe is not None:
            return recipe
        if not self.state.production_recipes:
            raise ValueError("Нет рецептур производства")
        return self.state.production_recipes[0]

    @staticmethod
    def _max_production_by_raw(
        recipe: ProductionRecipe, raw_inventory: dict[str, float]
    ) -> int:
        """Посчитать максимум выпуска по самому дефицитному сырью."""
        if not recipe.inputs:
            return 0
        return min(
            int(raw_inventory.get(item.raw_material_id, 0.0) // item.quantity_per_unit)
            for item in recipe.inputs
        )

    @staticmethod
    def _consume_raw_materials(
        recipe: ProductionRecipe, raw_inventory: dict[str, float], produced: int
    ) -> None:
        """Списать сырьё под фактический выпуск без отрицательных остатков."""
        for item in recipe.inputs:
            current = raw_inventory.get(item.raw_material_id, 0.0)
            raw_inventory[item.raw_material_id] = max(
                0.0, current - item.quantity_per_unit * produced
            )

    @staticmethod
    def _recipe_unit_cost(
        recipe: ProductionRecipe, raw_by_id: dict[str, RawMaterial]
    ) -> int:
        """Оценить unit cost из сырья и конверсионной стоимости."""
        raw_cost = 0.0
        for item in recipe.inputs:
            material = raw_by_id.get(item.raw_material_id)
            if material is None:
                continue
            raw_cost += item.quantity_per_unit * material.base_price_rub
        return int(raw_cost + recipe.conversion_cost_rub)

    def _apply_due_contracts(
        self,
        reports: dict[str, CompanyDayReport],
        news: list[str],
        operations: list[DayClosureOperation],
    ) -> None:
        for contract in self.state.contracts:
            if (
                contract.status != ContractStatus.ACTIVE
                or contract.due_day > self.state.day + 1
            ):
                continue

            seller_inventory = self.state.inventories.setdefault(contract.seller_id, {})
            available = seller_inventory.get(contract.product_id, 0)
            if available < contract.quantity:
                contract.status = ContractStatus.BREACHED
                seller = self._require_company(contract.seller_id)
                seller.reputation = max(0.0, seller.reputation - 6.0)
                reports[contract.seller_id].costs_rub += contract.penalty_rub
                reports[contract.seller_id].profit_rub -= contract.penalty_rub
                news.append(
                    "Контракт сорван: поставщик получил штраф и потерял репутацию."
                )
                operations.append(
                    DayClosureOperation(
                        step="contract_breached",
                        company_id=contract.seller_id,
                        amount_rub=contract.penalty_rub,
                        quantity=contract.quantity,
                        message=f"Сорван контракт {contract.id}: недостаточно товара.",
                    )
                )
                continue

            amount = contract.quantity * contract.unit_price_rub
            transferred = self._transfer_fifo(
                contract.seller_id,
                contract.buyer_id,
                contract.product_id,
                contract.quantity,
            )
            if transferred < contract.quantity:
                contract.status = ContractStatus.BREACHED
                continue
            reports[contract.seller_id].revenue_rub += amount
            reports[contract.seller_id].profit_rub += amount
            reports[contract.buyer_id].costs_rub += amount
            reports[contract.buyer_id].profit_rub -= amount
            contract.status = ContractStatus.FULFILLED
            news.append("Контракт исполнен: товар перешёл покупателю.")
            operations.append(
                DayClosureOperation(
                    step="contract_fulfilled",
                    company_id=contract.seller_id,
                    amount_rub=amount,
                    quantity=contract.quantity,
                    message=f"Исполнен контракт {contract.id}.",
                )
            )

    def _apply_retail_sales(
        self,
        reports: dict[str, CompanyDayReport],
        operations: list[DayClosureOperation],
    ) -> None:
        product_by_id = {product.id: product for product in self.state.products}
        for company in self.state.companies:
            if company.role != Role.RETAILER:
                continue
            region = self._require_region(company.region_id)
            decision = self.state.decisions.get(company.id, CompanyDecision())
            inventory = self.state.inventories.setdefault(company.id, {})
            for product_id, available in list(inventory.items()):
                product = product_by_id[product_id]
                demand = int(
                    product.base_daily_demand
                    * region.demand_index
                    * (1.08 if decision.marketing_budget_rub else 1.0)
                    / decision.target_price_index
                )
                remaining_capacity = max(
                    0,
                    self._daily_capacity(company.id, AssetType.STORE, 1_000_000)
                    - reports[company.id].sold_units,
                )
                sold = min(available, max(demand, 0), remaining_capacity)
                if sold:
                    sold = self._consume_fifo(company.id, product_id, sold)
                price = int(product.base_price_rub * decision.target_price_index)
                revenue = sold * price
                reports[company.id].sold_units += sold
                reports[company.id].revenue_rub += revenue
                reports[company.id].profit_rub += revenue
                if sold:
                    operations.append(
                        DayClosureOperation(
                            step="retail_sale",
                            company_id=company.id,
                            amount_rub=revenue,
                            quantity=sold,
                            message=f"Продано {sold} ед. товара {product.name}.",
                        )
                    )

            operating_costs = (
                self._fixed_costs(company.id, AssetType.STORE, 85_000)
                + decision.marketing_budget_rub
            )
            tax_reserve = int(max(reports[company.id].profit_rub, 0) * 0.2)
            reports[company.id].costs_rub += operating_costs + tax_reserve
            reports[company.id].profit_rub -= operating_costs + tax_reserve

    def _apply_loan_interest(
        self,
        reports: dict[str, CompanyDayReport],
        operations: list[DayClosureOperation],
    ) -> None:
        """Начислить ежедневные проценты по активным кредитам."""
        for loan in self.state.loans:
            if loan.is_defaulted or loan.outstanding_rub <= 0:
                continue
            daily_interest = max(1, int(loan.outstanding_rub * loan.annual_rate / 365))
            loan.accrued_interest_rub += daily_interest
            reports[loan.company_id].costs_rub += daily_interest
            reports[loan.company_id].profit_rub -= daily_interest
            operations.append(
                DayClosureOperation(
                    step="loan_interest",
                    company_id=loan.company_id,
                    amount_rub=daily_interest,
                    message=f"Начислены проценты по кредиту {loan.id}.",
                )
            )
            if self.state.day + 1 > loan.start_day + loan.term_days:
                loan.is_defaulted = True
                company = self._require_company(loan.company_id)
                company.reputation = max(0.0, company.reputation - 12.0)

    def _apply_financial_accounting(
        self,
        reports: dict[str, CompanyDayReport],
        operations: list[DayClosureOperation],
    ) -> None:
        """Начислить НДС, налог на прибыль и сохранить проводки дня."""
        posting_day = self.state.day + 1
        for company in self.state.companies:
            report = reports[company.id]
            report.vat_output_rub = int(report.revenue_rub * VAT_RATE / (1 + VAT_RATE))
            report.vat_input_rub = int(report.costs_rub * VAT_RATE / (1 + VAT_RATE))
            taxable_profit = max(0, report.revenue_rub - report.costs_rub)
            report.profit_tax_rub = int(taxable_profit * PROFIT_TAX_RATE)
            report.costs_rub += report.profit_tax_rub
            report.profit_rub -= report.profit_tax_rub
            vat_payable = max(0, report.vat_output_rub - report.vat_input_rub)
            self._append_ledger_entry(
                day=posting_day,
                company_id=company.id,
                entry_type="revenue",
                amount_rub=report.revenue_rub,
                description="Выручка операционного дня",
            )
            self._append_ledger_entry(
                day=posting_day,
                company_id=company.id,
                entry_type="cost",
                amount_rub=-report.costs_rub,
                description="Расходы операционного дня с налогом на прибыль",
            )
            if report.profit_tax_rub:
                self._append_ledger_entry(
                    day=posting_day,
                    company_id=company.id,
                    entry_type="profit_tax",
                    amount_rub=-report.profit_tax_rub,
                    description="Резерв налога на прибыль",
                )
            if vat_payable:
                self._append_ledger_entry(
                    day=posting_day,
                    company_id=company.id,
                    entry_type="vat_payable",
                    amount_rub=-vat_payable,
                    description="НДС к уплате по итогам дня",
                )
            operations.append(
                DayClosureOperation(
                    step="financial_accounting",
                    company_id=company.id,
                    amount_rub=report.profit_rub,
                    message=(
                        f"Финансы: прибыль {report.profit_rub} ₽, "
                        f"НДС к уплате {vat_payable} ₽."
                    ),
                )
            )

    def _append_ledger_entry(
        self,
        *,
        day: int,
        company_id: str,
        entry_type: str,
        amount_rub: int,
        description: str,
    ) -> None:
        """Добавить проводку без секретов и внешних побочных эффектов."""
        self.state.ledger_entries.append(
            LedgerEntry(
                id=f"ledger_{uuid4().hex[:10]}",
                day=day,
                company_id=company_id,
                entry_type=entry_type,
                amount_rub=amount_rub,
                description=description,
            )
        )

    def _apply_logistics_income(
        self,
        reports: dict[str, CompanyDayReport],
        operations: list[DayClosureOperation],
    ) -> None:
        for company in self.state.companies:
            if company.role != Role.DISTRIBUTOR:
                continue
            decision = self.state.decisions.get(company.id, CompanyDecision())
            delivered = min(
                decision.logistics_capacity_units,
                self._daily_capacity(company.id, AssetType.WAREHOUSE, 4_000),
            )
            revenue = delivered * 18
            costs = delivered * 9 + self._fixed_costs(
                company.id, AssetType.WAREHOUSE, 45_000
            )
            reports[company.id].delivered_units += delivered
            reports[company.id].revenue_rub += revenue
            reports[company.id].costs_rub += costs
            reports[company.id].profit_rub += revenue - costs
            if delivered:
                operations.append(
                    DayClosureOperation(
                        step="logistics_delivery",
                        company_id=company.id,
                        amount_rub=revenue,
                        quantity=delivered,
                        message=f"Доставлено {delivered} ед. грузовой мощности.",
                    )
                )

    def _require_company(self, company_id: str) -> Company:
        company = next(
            (item for item in self.state.companies if item.id == company_id),
            None,
        )
        if company is None:
            raise ValueError("Компания не найдена")
        return company

    def _require_region(self, region_id: str) -> Region:
        region = next(
            (item for item in self.state.regions if item.id == region_id), None
        )
        if region is None:
            raise ValueError("Регион не найден")
        return region

    def _require_product(self, product_id: str) -> None:
        self._get_product(product_id)

    def _get_product(self, product_id: str):
        product = next(
            (item for item in self.state.products if item.id == product_id), None
        )
        if product is None:
            raise ValueError("Товар не найден")
        return product

    @staticmethod
    def _starting_inventory(role: Role) -> dict[str, int]:
        if role == Role.RETAILER:
            return {"bread": 500, "milk": 450, "eggs": 300, "water": 500}
        if role == Role.PRODUCER:
            return {"bread": 2_000, "milk": 2_000}
        return {"bread": 800, "milk": 800, "water": 1_200}

    @staticmethod
    def _starting_raw_inventory() -> dict[str, float]:
        """Дать производителю сырьё для первых дней без отдельного рынка сырья."""
        return {
            "grain": 4_000.0,
            "raw_milk": 3_000.0,
            "packaging": 800.0,
        }
