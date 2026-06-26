"""Игровой движок закрывает день единообразно для трёх ролей рынка."""

import random
from copy import deepcopy
from uuid import uuid4

from app.domain.balance import (
    BANKS,
    FACILITY_FORMATS,
    INITIAL_ASSETS,
    INITIAL_INVENTORIES,
    INITIAL_RAW_INVENTORIES,
    PRODUCTION_RECIPES,
    PRODUCTS,
    RAW_MATERIALS,
    REGIONS,
    SEASONAL_DEMAND,
    STARTER_COMPANIES,
    STORE_FORMATS,
)
from app.domain.models import (
    AdvisorTip,
    AssetType,
    BusinessAsset,
    Company,
    CompanyCreate,
    CompanyDayReport,
    CompanyDecision,
    CompanyStatus,
    Contract,
    ContractCreate,
    ContractStatus,
    DayClosureOperation,
    DayClosureRecord,
    DeliveryOrder,
    DeliveryOrderCreate,
    DeliveryStatus,
    FactoryFormat,
    FinalStanding,
    FinancialReport,
    GameState,
    InventoryBatch,
    LedgerEntry,
    Loan,
    LoanCreate,
    MarketEvent,
    MarketEventType,
    MarketListing,
    NpcStrategy,
    PricePoint,
    ProductionRecipe,
    RawMaterial,
    Region,
    Role,
    StoreFormat,
    WarehouseFormat,
    WorldDayResult,
)

VAT_RATE = 0.20
PROFIT_TAX_RATE = 0.20
STORE_CLOSE_REFUND = 0.40


class GameOverError(ValueError):
    """Партия завершена: новые действия запрещены до сброса."""

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
        self._backfill_asset_formats()

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

    def build_store(
        self, company_id: str, store_format: StoreFormat, name: str | None = None
    ) -> BusinessAsset:
        """Построить ритейлеру новую торговую точку выбранного формата за наличные."""
        company = self._require_company(company_id)
        if company.role != Role.RETAILER:
            raise ValueError("Магазины может строить только ритейлер")
        preset = STORE_FORMATS.get(store_format)
        if preset is None:
            raise ValueError("Неизвестный формат магазина")
        if company.cash_rub < preset.build_cost_rub:
            raise ValueError("Недостаточно средств на постройку магазина")

        store_number = len(self._company_assets(company.id, AssetType.STORE)) + 1
        asset = BusinessAsset(
            id=f"asset_{uuid4().hex[:10]}",
            company_id=company.id,
            asset_type=AssetType.STORE,
            name=name or f"{preset.name} «{company.name}» №{store_number}",
            region_id=company.region_id,
            capacity_units_per_day=preset.capacity_units_per_day,
            fixed_cost_rub_per_day=preset.fixed_cost_rub_per_day,
            storage_type=preset.storage_type,
            quality_level=1.0,
            store_format=store_format,
        )
        company.cash_rub -= preset.build_cost_rub
        self.state.assets.append(asset)
        self.state.news.insert(
            0,
            f"Компания «{company.name}» открыла новый объект: {asset.name}.",
        )
        return asset

    def upgrade_store(
        self, company_id: str, asset_id: str, new_format: StoreFormat
    ) -> BusinessAsset:
        """Повысить формат магазина, доплатив разницу в стоимости постройки."""
        company = self._require_company(company_id)
        asset = self._require_store(company_id, asset_id)
        new_preset = STORE_FORMATS.get(new_format)
        if new_preset is None:
            raise ValueError("Неизвестный формат магазина")
        current_cost = (
            STORE_FORMATS[asset.store_format].build_cost_rub
            if asset.store_format in STORE_FORMATS
            else 0
        )
        if new_preset.build_cost_rub <= current_cost:
            raise ValueError("Апгрейд возможен только на более крупный формат")
        upgrade_cost = new_preset.build_cost_rub - current_cost
        if company.cash_rub < upgrade_cost:
            raise ValueError("Недостаточно средств на апгрейд магазина")

        company.cash_rub -= upgrade_cost
        asset.store_format = new_format
        asset.capacity_units_per_day = new_preset.capacity_units_per_day
        asset.fixed_cost_rub_per_day = new_preset.fixed_cost_rub_per_day
        asset.storage_type = new_preset.storage_type
        self.state.news.insert(
            0,
            f"Компания «{company.name}» провела апгрейд: {asset.name} → {new_preset.name}.",
        )
        return asset

    def close_store(self, company_id: str, asset_id: str) -> BusinessAsset:
        """Закрыть магазин, вернув часть вложений и сняв постоянные расходы."""
        company = self._require_company(company_id)
        asset = self._require_store(company_id, asset_id)
        stores = self._company_assets(company_id, AssetType.STORE)
        if len(stores) <= 1:
            raise ValueError("Нельзя закрыть последний магазин компании")

        refund = 0
        if asset.store_format in STORE_FORMATS:
            refund = int(
                STORE_FORMATS[asset.store_format].build_cost_rub * STORE_CLOSE_REFUND
            )
        company.cash_rub += refund
        self.state.assets = [item for item in self.state.assets if item.id != asset.id]
        self.state.news.insert(
            0,
            f"Компания «{company.name}» закрыла объект {asset.name} "
            f"(возврат {refund} ₽).",
        )
        return asset

    def _require_store(self, company_id: str, asset_id: str) -> BusinessAsset:
        """Найти магазин компании или сообщить понятную ошибку."""
        asset = next(
            (
                item
                for item in self.state.assets
                if item.id == asset_id and item.company_id == company_id
            ),
            None,
        )
        if asset is None:
            raise ValueError("Магазин не найден")
        if asset.asset_type != AssetType.STORE:
            raise ValueError("Объект не является магазином")
        return asset

    def _facility_catalog(self, role: Role) -> tuple[AssetType, dict]:
        """Сопоставить роль с типом строящегося объекта и его форматами."""
        if role == Role.PRODUCER:
            return AssetType.FACTORY, FACILITY_FORMATS[AssetType.FACTORY]
        if role == Role.DISTRIBUTOR:
            return AssetType.WAREHOUSE, FACILITY_FORMATS[AssetType.WAREHOUSE]
        raise ValueError("Эта роль строит магазины, а не заводы или склады")

    def build_facility(
        self, company_id: str, tier: str, name: str | None = None
    ) -> BusinessAsset:
        """Построить производителю завод или дистрибьютору склад за наличные."""
        company = self._require_company(company_id)
        asset_type, presets = self._facility_catalog(company.role)
        preset = presets.get(tier)
        if preset is None:
            raise ValueError("Неизвестный формат объекта")
        if company.cash_rub < preset.build_cost_rub:
            raise ValueError("Недостаточно средств на постройку объекта")

        count = len(self._company_assets(company.id, asset_type)) + 1
        asset = BusinessAsset(
            id=f"asset_{uuid4().hex[:10]}",
            company_id=company.id,
            asset_type=asset_type,
            name=name or f"{preset.name} «{company.name}» №{count}",
            region_id=company.region_id,
            capacity_units_per_day=preset.capacity_units_per_day,
            fixed_cost_rub_per_day=preset.fixed_cost_rub_per_day,
            storage_type=preset.storage_type,
            quality_level=1.0,
            facility_format=tier,
        )
        company.cash_rub -= preset.build_cost_rub
        self.state.assets.append(asset)
        self.state.news.insert(
            0, f"Компания «{company.name}» открыла новый объект: {asset.name}."
        )
        return asset

    def upgrade_facility(
        self, company_id: str, asset_id: str, new_tier: str
    ) -> BusinessAsset:
        """Повысить формат завода или склада, доплатив разницу постройки."""
        company = self._require_company(company_id)
        asset_type, presets = self._facility_catalog(company.role)
        asset = self._require_facility(company_id, asset_id, asset_type)
        new_preset = presets.get(new_tier)
        if new_preset is None:
            raise ValueError("Неизвестный формат объекта")
        current_cost = (
            presets[asset.facility_format].build_cost_rub
            if asset.facility_format in presets
            else 0
        )
        if new_preset.build_cost_rub <= current_cost:
            raise ValueError("Апгрейд возможен только на более крупный формат")
        upgrade_cost = new_preset.build_cost_rub - current_cost
        if company.cash_rub < upgrade_cost:
            raise ValueError("Недостаточно средств на апгрейд объекта")

        company.cash_rub -= upgrade_cost
        asset.facility_format = new_tier
        asset.capacity_units_per_day = new_preset.capacity_units_per_day
        asset.fixed_cost_rub_per_day = new_preset.fixed_cost_rub_per_day
        asset.storage_type = new_preset.storage_type
        self.state.news.insert(
            0,
            f"Компания «{company.name}» провела апгрейд: {asset.name} → {new_preset.name}.",
        )
        return asset

    def close_facility(self, company_id: str, asset_id: str) -> BusinessAsset:
        """Закрыть завод или склад, вернув часть вложений и сняв расходы."""
        company = self._require_company(company_id)
        asset_type, presets = self._facility_catalog(company.role)
        asset = self._require_facility(company_id, asset_id, asset_type)
        if len(self._company_assets(company_id, asset_type)) <= 1:
            raise ValueError("Нельзя закрыть последний объект компании")

        refund = 0
        if asset.facility_format in presets:
            refund = int(presets[asset.facility_format].build_cost_rub * STORE_CLOSE_REFUND)
        company.cash_rub += refund
        self.state.assets = [item for item in self.state.assets if item.id != asset.id]
        self.state.news.insert(
            0,
            f"Компания «{company.name}» закрыла объект {asset.name} "
            f"(возврат {refund} ₽).",
        )
        return asset

    def _require_facility(
        self, company_id: str, asset_id: str, asset_type: AssetType
    ) -> BusinessAsset:
        """Найти завод или склад компании нужного типа."""
        asset = next(
            (
                item
                for item in self.state.assets
                if item.id == asset_id and item.company_id == company_id
            ),
            None,
        )
        if asset is None:
            raise ValueError("Объект не найден")
        if asset.asset_type != asset_type:
            raise ValueError("Тип объекта не соответствует роли компании")
        return asset

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

        if self.state.game_over:
            raise GameOverError("Партия завершена — начните новую игру.")

        operations: list[DayClosureOperation] = []
        reports_by_company = {
            company.id: CompanyDayReport(company_id=company.id)
            for company in self.state.companies
        }
        news: list[str] = []

        self._apply_npc_decisions()
        self._reconcile_npc_listings()
        self._expire_inventory_batches(reports_by_company, operations)
        self._apply_production(reports_by_company, operations)
        self._apply_market_npc_listing(operations)
        self._apply_due_contracts(reports_by_company, news, operations)
        self._apply_market_npc_purchases(operations)
        self._apply_retail_sales(reports_by_company, operations)
        self._apply_due_delivery_orders(reports_by_company, operations)
        self._apply_loan_interest(reports_by_company, operations)
        self._generate_market_events(operations)
        self._apply_financial_accounting(reports_by_company, operations)

        for company in self.state.companies:
            # Банкрот заморожен: кэш не меняется (инвариант — не воскресает)
            if company.status == CompanyStatus.BANKRUPT:
                continue
            report = reports_by_company[company.id]
            company.cash_rub += report.profit_rub

        for company in self.state.companies:
            if company.is_npc and company.status == CompanyStatus.ACTIVE:
                upgrade_news = self._npc_try_upgrade(company, reports_by_company)
                if upgrade_news:
                    news.insert(0, upgrade_news)
                expand_news = self._npc_try_expand(company, reports_by_company)
                if expand_news:
                    news.insert(0, expand_news)

        self._check_bankruptcy_and_victory(news, operations)

        self.state.day += 1
        self.state.season = (self.state.day // 7) % 4 + 1
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

    BANKRUPTCY_THRESHOLD = -10_000_000
    WIN_CASH_THRESHOLD = 100_000_000
    # Эластичность спроса по цене: дешевле рынка → пул растёт, дороже → сжимается.
    BASE_PRICE_ELASTICITY = 0.9
    # Расширение ассортимента NPC-ритейлера: только если здоров, и постепенно.
    DIVERSIFY_CASH_FLOOR = 4_000_000
    MAX_NEW_LINES_PER_DAY = 2
    # Транзитные расходы дистрибьютора на единицу × риск маршрута (топливо/потери/страховка).
    TRANSIT_RISK_COST_PER_UNIT = 45
    # Сколько заявок на доставку NPC-дистрибьютор создаёт за день (логистический спрос).
    MAX_NPC_LOGISTICS_ORDERS_PER_DAY = 4

    def _check_bankruptcy_and_victory(
        self,
        news: list[str],
        operations: list[DayClosureOperation],
    ) -> None:
        """Пометить банкротов и определить победителя."""
        if self.state.game_over:
            return

        for company in self.state.companies:
            if company.status == CompanyStatus.BANKRUPT:
                continue
            if company.cash_rub < self.BANKRUPTCY_THRESHOLD:
                company.status = CompanyStatus.BANKRUPT
                msg = f"«{company.name}» объявила банкротство (кэш {company.cash_rub:,} руб.)."
                news.append(msg)
                operations.append(
                    DayClosureOperation(
                        step="bankruptcy",
                        company_id=company.id,
                        amount_rub=company.cash_rub,
                        message=msg,
                    )
                )

        active = [c for c in self.state.companies if c.status == CompanyStatus.ACTIVE]

        # Победа по капиталу
        for company in active:
            if company.cash_rub >= self.WIN_CASH_THRESHOLD:
                self.state.game_over = True
                self.state.winner_company_id = company.id
                news.append(f"«{company.name}» выиграла — капитал {company.cash_rub:,} руб.!")
                return

        # Победа, если остался один активный
        if len(active) == 1:
            self.state.game_over = True
            self.state.winner_company_id = active[0].id
            news.append(f"«{active[0].name}» — последняя выжившая компания на рынке!")

    def compute_standings(self) -> list[FinalStanding]:
        """Итоговый рейтинг: активные по убыванию кэша, затем банкроты."""
        ordered = sorted(
            self.state.companies,
            key=lambda c: (c.status == CompanyStatus.BANKRUPT, -c.cash_rub),
        )
        return [
            FinalStanding(
                rank=index,
                company_id=company.id,
                name=company.name,
                role=company.role,
                cash_rub=company.cash_rub,
                status=company.status,
                is_winner=company.id == self.state.winner_company_id,
            )
            for index, company in enumerate(ordered, start=1)
        ]

    def build_advice(self, company_id: str) -> list[AdvisorTip]:
        """Советник: читаемые подсказки «что происходит и что делать» по компании."""
        company = next((c for c in self.state.companies if c.id == company_id), None)
        if company is None:
            return [AdvisorTip(severity="info", message="Компания не найдена.")]
        if company.status == CompanyStatus.BANKRUPT:
            return [AdvisorTip(severity="danger", message="Компания банкрот — партия для неё окончена.")]

        tips: list[AdvisorTip] = []

        # Финансы — для всех ролей
        if company.cash_rub < 0:
            tips.append(AdvisorTip(
                severity="danger",
                message="Кэш в минусе — подними цены, сократи закупки или возьми кредит, иначе банкротство.",
            ))
        elif company.cash_rub < 2_000_000:
            tips.append(AdvisorTip(
                severity="warning",
                message="Низкий запас кэша — следи за расходами и не перетаривайся.",
            ))
        elif company.cash_rub > 15_000_000:
            tips.append(AdvisorTip(
                severity="info",
                message="Свободный капитал простаивает — построй/улучши объект или расширь ассортимент, чтобы расти.",
            ))

        # Скорая просрочка — для всех, кто держит товар (срабатывает раньше списания)
        soon_day = self.state.day + 2
        expiring = sum(
            b.quantity
            for b in self.state.inventory_batches
            if b.company_id == company_id and b.quantity > 0 and 0 < b.expires_day <= soon_day
        )
        if expiring > 0:
            tips.append(AdvisorTip(
                severity="warning",
                message=f"Скоро просрочка: {expiring:,} ед. спишутся в ближайшие дни — продай или снизь цену.",
            ))

        report = next(
            (r for r in self.state.last_reports if r.company_id == company_id), None
        )

        if company.role == Role.RETAILER:
            inventory = self.state.inventories.get(company_id, {})
            total_stock = sum(inventory.values())
            store_cap = self._daily_capacity(company_id, AssetType.STORE, 1_000)
            if total_stock > store_cap * 6:
                tips.append(AdvisorTip(
                    severity="warning",
                    message=f"Затоваривание: запас {total_stock:,} ед. при дневной мощности {store_cap:,}. Снизь закупки или цену.",
                ))
            stocked = sum(1 for q in inventory.values() if q > 0)
            if stocked < 6:
                tips.append(AdvisorTip(
                    severity="info",
                    message=f"Узкий ассортимент ({stocked} товаров) — расширь закупки с рынка, чтобы продавать больше.",
                ))
            # Конкурент демпингует в твоём регионе
            rivals = [
                c for c in self.state.companies
                if c.role == Role.RETAILER and c.id != company_id
                and c.region_id == company.region_id and c.status == CompanyStatus.ACTIVE
            ]
            my_price = self.state.decisions.get(company_id, CompanyDecision()).target_price_index
            for rival in rivals:
                rival_price = self.state.decisions.get(rival.id, CompanyDecision()).target_price_index
                if rival_price < my_price - 0.15:
                    tips.append(AdvisorTip(
                        severity="warning",
                        message=f"Конкурент «{rival.name}» демпингует в твоём регионе — рискуешь потерять долю.",
                    ))
                    break

        elif company.role == Role.PRODUCER:
            raws = self.state.raw_inventories.get(company_id, {})
            low = [rid for rid, q in raws.items() if q < 300]
            if low:
                tips.append(AdvisorTip(
                    severity="warning",
                    message=f"Дефицит сырья ({', '.join(low)}) — докупи, иначе выпуск просядет.",
                ))
            if report and report.produced_units == 0:
                tips.append(AdvisorTip(
                    severity="info",
                    message="Завод не выпускал товар в прошлый день — проверь сырьё и мощность.",
                ))

        elif company.role == Role.DISTRIBUTOR:
            if report and report.delivered_units == 0:
                tips.append(AdvisorTip(
                    severity="info",
                    message="Нет доставок — прими заявки или вози излишки в дефицитные регионы.",
                ))

        if not tips:
            tips.append(AdvisorTip(
                severity="ok",
                message="Дела стабильны — оптимизируй цепочку, цены и ассортимент, чтобы оторваться от ботов.",
            ))
        # Сначала самое важное: danger → warning → info → ok
        severity_order = {"danger": 0, "warning": 1, "info": 2, "ok": 3}
        return sorted(tips, key=lambda t: severity_order.get(t.severity, 9))

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
            preset = STORE_FORMATS[StoreFormat.CONVENIENCE]
            return BusinessAsset(
                id=f"asset_{uuid4().hex[:10]}",
                company_id=company.id,
                asset_type=AssetType.STORE,
                name=f"Магазин «{company.name}»",
                region_id=company.region_id,
                capacity_units_per_day=preset.capacity_units_per_day,
                fixed_cost_rub_per_day=preset.fixed_cost_rub_per_day,
                storage_type=preset.storage_type,
                quality_level=1.0,
                store_format=StoreFormat.CONVENIENCE,
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
                facility_format=FactoryFormat.PLANT.value,
            )
        return BusinessAsset(
            id=f"asset_{uuid4().hex[:10]}",
            company_id=company.id,
            asset_type=AssetType.WAREHOUSE,
            name=f"Склад «{company.name}»",
            region_id=company.region_id,
            capacity_units_per_day=3_000,
            fixed_cost_rub_per_day=60_000,
            storage_type="смешанное",
            quality_level=1.0,
            facility_format=WarehouseFormat.CENTER.value,
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

    def _backfill_asset_formats(self) -> None:
        """Вывести форматы объектов, созданных до введения форматной системы."""
        store_tiers = list(STORE_FORMATS.items())
        for asset in self.state.assets:
            if asset.asset_type == AssetType.STORE and asset.store_format is None:
                asset.store_format = next(
                    (
                        fmt
                        for fmt, opt in reversed(store_tiers)
                        if asset.capacity_units_per_day >= opt.capacity_units_per_day
                    ),
                    StoreFormat.KIOSK,
                )
            elif (
                asset.asset_type in (AssetType.FACTORY, AssetType.WAREHOUSE)
                and asset.facility_format is None
            ):
                presets = FACILITY_FORMATS.get(asset.asset_type, {})
                asset.facility_format = next(
                    (
                        tier
                        for tier, opt in reversed(list(presets.items()))
                        if asset.capacity_units_per_day >= opt.capacity_units_per_day
                    ),
                    next(iter(presets), None),
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

    def _run_recipe(
        self,
        company: Company,
        recipe: ProductionRecipe,
        requested: int,
        raw_inventory: dict[str, float],
        raw_by_id: dict,
        reports: dict[str, CompanyDayReport],
        operations: list[DayClosureOperation],
        out_mult: float,
    ) -> None:
        product = self._get_product(recipe.product_id)
        max_by_raw = self._max_production_by_raw(recipe, raw_inventory)
        base_produced = min(requested, max_by_raw)
        produced = int(base_produced * out_mult)
        if requested and base_produced < requested:
            operations.append(
                DayClosureOperation(
                    step="raw_material_shortage",
                    company_id=company.id,
                    quantity=requested - base_produced,
                    message=(
                        f"Не хватило сырья для {requested - base_produced} ед. "
                        f"товара {product.name}."
                    ),
                )
            )
        if base_produced:
            self._consume_raw_materials(recipe, raw_inventory, base_produced)
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

    def _apply_production(
        self,
        reports: dict[str, CompanyDayReport],
        operations: list[DayClosureOperation],
    ) -> None:
        raw_by_id = {material.id: material for material in self.state.raw_materials}
        for company in self.state.companies:
            if company.role != Role.PRODUCER or company.status == CompanyStatus.BANKRUPT:
                continue
            raw_inventory = self.state.raw_inventories.setdefault(
                company.id, self._starting_raw_inventory()
            )
            out_mult = self._factory_output_multiplier(company.id)
            capacity = self._daily_capacity(company.id, AssetType.FACTORY, 0)
            if company.is_npc:
                for recipe, units in self._npc_production_plan(company):
                    self._run_recipe(
                        company, recipe, units, raw_inventory,
                        raw_by_id, reports, operations, out_mult,
                    )
            else:
                decision = self.state.decisions.get(company.id, CompanyDecision())
                recipe = self._resolve_recipe(decision.recipe_id)
                requested = min(decision.production_units, capacity)
                self._run_recipe(
                    company, recipe, requested, raw_inventory,
                    raw_by_id, reports, operations, out_mult,
                )

    def _resolve_recipe(self, recipe_id: str | None) -> ProductionRecipe:
        """Вернуть рецепт по ID или дефолтный (хлеб)."""
        if recipe_id:
            found = next(
                (r for r in self.state.production_recipes if r.product_id == recipe_id),
                None,
            )
            if found is not None:
                return found
        return self._get_default_recipe()

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

    def _npc_production_plan(self, company: Company) -> list[tuple[ProductionRecipe, int]]:
        """Умный план выпуска NPC: мощность распределяется по привлекательности.

        Привлекательность = маржа × спрос (с сезоном), с уклоном по стратегии. Половина
        мощности делится по привлекательности, половина — поровну (диверсификация).
        Так бот «строит цепочку» осмысленно: льёт мощность в маржинальное и ходовое.
        """
        recipes = self.state.production_recipes
        capacity = self._daily_capacity(company.id, AssetType.FACTORY, 0)
        budget = int(capacity * 0.9)
        if not recipes or budget <= 0:
            return []

        product_by_id = {p.id: p for p in self.state.products}
        raw_by_id = {m.id: m for m in self.state.raw_materials}
        season = SEASONAL_DEMAND.get(self.state.season, {})

        scores: list[float] = []
        for recipe in recipes:
            product = product_by_id.get(recipe.product_id)
            if product is None:
                scores.append(0.0)
                continue
            margin = max(1.0, product.base_price_rub - self._recipe_unit_cost(recipe, raw_by_id))
            demand = product.base_daily_demand * season.get(recipe.product_id, 1.0)
            score = margin * demand
            if company.npc_strategy == NpcStrategy.PREMIUM:
                score *= max(0.3, product.base_price_rub / 150.0)  # уклон в дорогое
            elif company.npc_strategy == NpcStrategy.AGGRESSIVE:
                score *= max(0.3, demand / 350.0)  # уклон в объём
            scores.append(score)

        score_total = sum(scores) or 1.0
        even = budget / len(recipes)
        plan: list[tuple[ProductionRecipe, int]] = []
        for recipe, score in zip(recipes, scores, strict=True):
            units = int(0.5 * even + 0.5 * budget * score / score_total)
            if units > 0:
                plan.append((recipe, units))
        return plan

    def _npc_restock_raw_materials(self, company: Company) -> None:
        """NPC докупает сырьё под план выпуска, если запас < 14 дней производства."""
        plan = self._npc_production_plan(company)
        if not plan:
            return
        raw_inventory = self.state.raw_inventories.setdefault(company.id, {})
        raw_by_id = {m.id: m for m in self.state.raw_materials}
        daily_use: dict[str, float] = {}
        for recipe, units in plan:
            for item in recipe.inputs:
                daily_use[item.raw_material_id] = (
                    daily_use.get(item.raw_material_id, 0.0)
                    + item.quantity_per_unit * units
                )
        for raw_id, use_per_day in daily_use.items():
            current = raw_inventory.get(raw_id, 0.0)
            if current >= use_per_day * 14:
                continue
            buy_amount = use_per_day * 30 - current
            material = raw_by_id.get(raw_id)
            if not material:
                continue
            cost = int(buy_amount * material.base_price_rub * 1.1)
            if company.cash_rub >= cost:
                company.cash_rub -= cost
                raw_inventory[raw_id] = current + buy_amount

    # -------------------------------------------------------------------------
    # NPC market participation
    # -------------------------------------------------------------------------

    def _reconcile_npc_listings(self) -> None:
        """Скорректировать объём NPC-лота под реальный инвентарь продавца."""
        for listing in self.state.market_listings:
            if not listing.is_active:
                continue
            seller = next(
                (c for c in self.state.companies if c.id == listing.seller_id and c.is_npc),
                None,
            )
            if seller is None:
                continue
            actual = self.state.inventories.get(seller.id, {}).get(listing.product_id, 0)
            if actual <= 0:
                listing.is_active = False
                listing.quantity_available = 0
            elif actual < listing.quantity_available:
                listing.quantity_available = actual

    def _apply_market_npc_listing(
        self,
        operations: list[DayClosureOperation],
    ) -> None:
        """NPC-производители выставляют излишки производства на рынок."""
        product_by_id = {p.id: p for p in self.state.products}
        for company in self.state.companies:
            if (
                not company.is_npc
                or company.role != Role.PRODUCER
                or company.status == CompanyStatus.BANKRUPT
            ):
                continue
            inventory = self.state.inventories.get(company.id, {})
            for product_id, available in inventory.items():
                if available < 100:
                    continue
                product = product_by_id.get(product_id)
                if product is None:
                    continue
                already_listed = any(
                    lst.seller_id == company.id
                    and lst.product_id == product_id
                    and lst.is_active
                    for lst in self.state.market_listings
                )
                if already_listed:
                    continue
                to_list = min(int(available * 0.6), product.base_daily_demand * 7)
                to_list = max(50, to_list)
                if to_list > available:
                    continue
                list_price = max(1, int(product.base_price_rub * 1.10))
                try:
                    self.create_listing(company.id, product_id, to_list, list_price)
                    operations.append(
                        DayClosureOperation(
                            step="npc_market_listing",
                            company_id=company.id,
                            quantity=to_list,
                            amount_rub=list_price * to_list,
                            message=(
                                f"NPC «{company.name}» выставил {to_list} ед."
                                f" {product.name} по {list_price} руб."
                            ),
                        )
                    )
                except ValueError:
                    continue

    def _apply_market_npc_purchases(
        self,
        operations: list[DayClosureOperation],
    ) -> None:
        """NPC-ритейлеры пополняют запасы с рынка, если цена приемлема."""
        product_by_id = {p.id: p for p in self.state.products}
        for company in self.state.companies:
            if (
                not company.is_npc
                or company.role != Role.RETAILER
                or company.status == CompanyStatus.BANKRUPT
            ):
                continue
            inventory = self.state.inventories.get(company.id, {})
            cash_budget = int(company.cash_rub * 0.30)

            # Диверсифицируют ассортимент только финансово здоровые ритейлеры —
            # это не даёт слабым компаниям перетариться дорогими новинками и разориться.
            can_diversify = company.cash_rub >= self.DIVERSIFY_CASH_FLOOR
            available_pids = {
                lst.product_id
                for lst in self.state.market_listings
                if lst.is_active
                and lst.seller_id != company.id
                and lst.quantity_available > 0
            }
            # Сначала пополняем то, что уже на полке; затем (если здоров) — новинки
            # по привлекательности (цена × спрос).
            existing = list(inventory.keys())
            new_lines = sorted(
                (available_pids - set(inventory)) if can_diversify else set(),
                key=lambda pid: (
                    product_by_id[pid].base_price_rub * product_by_id[pid].base_daily_demand
                    if pid in product_by_id else 0
                ),
                reverse=True,
            )
            new_lines_added = 0

            for product_id in [*existing, *new_lines]:
                product = product_by_id.get(product_id)
                if product is None:
                    continue
                current = inventory.get(product_id, 0)
                is_new_line = current <= 0
                if is_new_line and new_lines_added >= self.MAX_NEW_LINES_PER_DAY:
                    continue
                # Новинку заводим скромным объёмом (не вычищаем рынок за день)
                threshold = product.base_daily_demand * (2 if is_new_line else 5)
                if current >= threshold:
                    continue
                needed = threshold - current
                needed_before = needed

                listings = sorted(
                    [
                        lst for lst in self.state.market_listings
                        if lst.product_id == product_id
                        and lst.is_active
                        and lst.seller_id != company.id
                        and lst.quantity_available > 0
                    ],
                    key=lambda lst: lst.price_rub_per_unit,
                )
                for listing in listings:
                    if listing.price_rub_per_unit > int(product.base_price_rub * 1.4):
                        break
                    if cash_budget <= 0 or needed <= 0:
                        break
                    can_afford = cash_budget // listing.price_rub_per_unit
                    to_buy = min(needed, listing.quantity_available, max(0, can_afford))
                    if to_buy <= 0:
                        continue
                    try:
                        cost, _ = self.purchase_listing(listing.id, company.id, to_buy)
                        cash_budget -= cost
                        needed -= to_buy
                        operations.append(
                            DayClosureOperation(
                                step="npc_market_purchase",
                                company_id=company.id,
                                quantity=to_buy,
                                amount_rub=cost,
                                message=(
                                    f"NPC «{company.name}» купил {to_buy} ед."
                                    f" {product.name} по {listing.price_rub_per_unit} руб."
                                ),
                            )
                        )
                    except ValueError:
                        continue
                if is_new_line and needed < needed_before:
                    new_lines_added += 1

    def _npc_generate_logistics_orders(self, distributor: Company) -> None:
        """NPC-дистрибьютор создаёт заявки: излишки производителя → дефицит ритейлера в другом регионе."""
        product_by_id = {p.id: p for p in self.state.products}
        producers = [
            c for c in self.state.companies
            if c.is_npc and c.role == Role.PRODUCER and c.status == CompanyStatus.ACTIVE
        ]
        retailers = [
            c for c in self.state.companies
            if c.is_npc and c.role == Role.RETAILER and c.status == CompanyStatus.ACTIVE
        ]
        active_routes = {
            (o.shipper_id, o.receiver_id, o.product_id)
            for o in self.state.delivery_orders
            if o.status in (DeliveryStatus.PENDING, DeliveryStatus.ACCEPTED)
        }
        created = 0
        for producer in producers:
            if created >= self.MAX_NPC_LOGISTICS_ORDERS_PER_DAY:
                break
            for product_id, qty in self.state.inventories.get(producer.id, {}).items():
                if created >= self.MAX_NPC_LOGISTICS_ORDERS_PER_DAY:
                    break
                product = product_by_id.get(product_id)
                if product is None:
                    continue
                surplus = qty - product.base_daily_demand * 3  # сверх локального сбыта
                if surplus < 200:
                    continue
                receiver = next(
                    (
                        r for r in retailers
                        if r.region_id != producer.region_id
                        and self.state.inventories.get(r.id, {}).get(product_id, 0)
                        < product.base_daily_demand
                    ),
                    None,
                )
                if receiver is None:
                    continue
                if (producer.id, receiver.id, product_id) in active_routes:
                    continue
                self.state.delivery_orders.append(
                    DeliveryOrder(
                        status=DeliveryStatus.ACCEPTED,
                        shipper_id=producer.id,
                        distributor_id=distributor.id,
                        receiver_id=receiver.id,
                        product_id=product_id,
                        quantity=min(int(surplus), 500),
                        fee_rub_per_unit=max(5, int(product.base_price_rub * 0.16)),
                        due_day=self.state.day + 1,
                        created_day=self.state.day,
                    )
                )
                active_routes.add((producer.id, receiver.id, product_id))
                created += 1

    def _apply_npc_decisions(self) -> None:
        """Сформировать решения на день для всех NPC-компаний."""
        for company in self.state.companies:
            if not company.is_npc or company.status == CompanyStatus.BANKRUPT:
                continue
            if company.role == Role.PRODUCER:
                self._npc_restock_raw_materials(company)
            elif company.role == Role.DISTRIBUTOR:
                # NPC-дистрибьютор принимает все pending-заявки, в которых он назван
                for order in self.state.delivery_orders:
                    if (
                        order.distributor_id == company.id
                        and order.status == DeliveryStatus.PENDING
                    ):
                        order.status = DeliveryStatus.ACCEPTED
                # …и сам ищет работу: возит излишки производителя нуждающемуся
                # ритейлеру в другом регионе (логистический спрос в одиночке)
                self._npc_generate_logistics_orders(company)
            elif company.role == Role.RETAILER:
                inventory = self.state.inventories.get(company.id, {})
                total_stock = sum(inventory.values())
                store_cap = self._daily_capacity(company.id, AssetType.STORE, 1_000)
                if company.npc_strategy == NpcStrategy.AGGRESSIVE:
                    # Агрессивный: всегда демпингует, много маркетинга
                    price_index = 0.88 if total_stock < store_cap else 0.82
                    marketing = 60_000
                elif company.npc_strategy == NpcStrategy.PREMIUM:
                    # Премиум: высокая цена, мало маркетинга
                    price_index = 1.30 if total_stock < store_cap * 0.5 else 1.20
                    marketing = 15_000
                else:
                    # Balanced (по умолчанию)
                    price_index = 1.10 if total_stock < store_cap else 0.95
                    marketing = 30_000
                self.state.decisions[company.id] = CompanyDecision(
                    target_price_index=price_index,
                    marketing_budget_rub=marketing,
                )

    def _npc_try_expand(
        self, company: Company, day_reports: dict[str, CompanyDayReport]
    ) -> str | None:
        """NPC расширяется НОВЫМ объектом — только когда прибылен (пресс преимущества).

        Расширение несёт двойные фикс-расходы, поэтому окупается лишь у растущего
        бизнеса: гейтим по положительной прибыли дня, иначе бот «осушит» кассу.
        """
        report = day_reports.get(company.id)
        if report is None or report.profit_rub < 500_000:
            return None
        try:
            if company.role == Role.RETAILER:
                if len(self._company_assets(company.id, AssetType.STORE)) >= 3:
                    return None
                fmt = StoreFormat.CONVENIENCE
                if company.cash_rub >= STORE_FORMATS[fmt].build_cost_rub * 3:
                    self.build_store(company.id, fmt)
                    return f"NPC «{company.name}» открыл новый магазин ({STORE_FORMATS[fmt].name})."
            else:
                asset_type, presets = self._facility_catalog(company.role)
                if len(self._company_assets(company.id, asset_type)) >= 2:
                    return None
                # Новый объект начинаем с самого дешёвого тира (рост с малого, не осушая кассу)
                cheapest = min(presets.values(), key=lambda x: x.build_cost_rub)
                if company.cash_rub >= cheapest.build_cost_rub * 3:
                    self.build_facility(company.id, cheapest.tier)
                    return f"NPC «{company.name}» построил новый объект ({cheapest.name})."
        except ValueError:
            pass
        return None

    def _npc_try_upgrade(
        self,
        company: Company,
        day_reports: dict[str, CompanyDayReport],
    ) -> str | None:
        """Апгрейдить один объект NPC если хватает денег (двойной запас)."""
        try:
            if company.role == Role.RETAILER:
                stores = self._company_assets(company.id, AssetType.STORE)
                store_order = sorted(STORE_FORMATS.keys(), key=lambda f: STORE_FORMATS[f].build_cost_rub)
                for store in stores:
                    upgrade_fmt = next(
                        (
                            f for f in store_order
                            if STORE_FORMATS[f].build_cost_rub > STORE_FORMATS.get(store.store_format, STORE_FORMATS[StoreFormat.KIOSK]).build_cost_rub
                        ),
                        None,
                    )
                    if upgrade_fmt is None:
                        continue
                    cost = STORE_FORMATS[upgrade_fmt].build_cost_rub - STORE_FORMATS.get(store.store_format, STORE_FORMATS[StoreFormat.KIOSK]).build_cost_rub
                    if company.cash_rub >= cost * 2:
                        self.upgrade_store(company.id, store.id, upgrade_fmt)
                        return f"NPC «{company.name}» улучшил {store.name} → {STORE_FORMATS[upgrade_fmt].name}."
            else:
                asset_type, presets = self._facility_catalog(company.role)
                facilities = self._company_assets(company.id, asset_type)
                tiers_sorted = sorted(presets.values(), key=lambda x: x.build_cost_rub)
                for facility in facilities:
                    current_cost = presets[facility.facility_format].build_cost_rub if facility.facility_format in presets else 0
                    next_tier = next(
                        (t for t in tiers_sorted if t.build_cost_rub > current_cost),
                        None,
                    )
                    if next_tier is None:
                        continue
                    upgrade_cost = next_tier.build_cost_rub - current_cost
                    if company.cash_rub >= upgrade_cost * 2:
                        self.upgrade_facility(company.id, facility.id, next_tier.tier)
                        return f"NPC «{company.name}» апгрейдил {facility.name} → {next_tier.name}."
        except ValueError:
            pass
        return None

    def _warehouse_rate_multiplier(self, company_id: str) -> float:
        """Взвешенный по мощности мультипликатор ставки доставки складов компании."""
        warehouses = self._company_assets(company_id, AssetType.WAREHOUSE)
        total_cap = sum(w.capacity_units_per_day for w in warehouses)
        if not warehouses or not total_cap:
            return 1.0
        presets = FACILITY_FORMATS[AssetType.WAREHOUSE]
        return sum(
            w.capacity_units_per_day
            * presets.get(w.facility_format, presets[WarehouseFormat.CENTER.value]).output_multiplier
            for w in warehouses
        ) / total_cap

    def _factory_output_multiplier(self, company_id: str) -> float:
        """Взвешенный по мощности мультипликатор выхода продукции заводов компании."""
        factories = self._company_assets(company_id, AssetType.FACTORY)
        total_cap = sum(f.capacity_units_per_day for f in factories)
        if not factories or not total_cap:
            return 1.0
        presets = FACILITY_FORMATS[AssetType.FACTORY]
        return sum(
            f.capacity_units_per_day
            * presets.get(f.facility_format, presets[FactoryFormat.PLANT.value]).output_multiplier
            for f in factories
        ) / total_cap

    def _store_demand_multiplier(self, company_id: str) -> float:
        """Взвешенный по мощности мультипликатор спроса для форматов магазинов."""
        stores = self._company_assets(company_id, AssetType.STORE)
        total_cap = sum(s.capacity_units_per_day for s in stores)
        if not stores or not total_cap:
            return 1.0
        return sum(
            s.capacity_units_per_day
            * STORE_FORMATS.get(s.store_format, STORE_FORMATS[StoreFormat.CONVENIENCE]).demand_multiplier
            for s in stores
        ) / total_cap

    def _demand_event_multiplier(self, region_id: str, product_id: str) -> float:
        """Суммарный мультипликатор спроса от активных рыночных событий."""
        closing_day = self.state.day + 1
        mult = 1.0
        for event in self.state.market_events:
            if event.expires_day < closing_day:
                continue
            if event.region_id is not None and event.region_id != region_id:
                continue
            if event.product_id is not None and event.product_id != product_id:
                continue
            mult *= event.magnitude
        return mult

    _EVENT_TEMPLATES: list[tuple[str, float, str]] = [
        ("demand_shock", 0.80, "Снижение потребительского спроса на {p} в регионе {r} на 20%."),
        ("demand_shock", 1.25, "Рост потребительского спроса на {p} в регионе {r} на 25%."),
        ("demand_shock", 1.15, "Сезонный всплеск продаж {p} в регионе {r} на 15%."),
        ("supply_disruption", 0.75, "Перебои с поставками {p} в регионе {r}: дефицит на рынке."),
    ]

    def _generate_market_events(self, operations: list[DayClosureOperation]) -> None:
        """С вероятностью 15% генерировать рыночное событие на закрытие дня."""
        if random.random() > 0.15:
            return
        closing_day = self.state.day + 1
        product = random.choice(self.state.products)
        region = random.choice(self.state.regions)
        etype_str, magnitude, tmpl = random.choice(self._EVENT_TEMPLATES)
        description = tmpl.format(p=product.name, r=region.name)
        duration = random.randint(2, 5)
        event = MarketEvent(
            day=closing_day,
            event_type=MarketEventType(etype_str),
            region_id=region.id,
            product_id=product.id,
            magnitude=magnitude,
            description=description,
            expires_day=closing_day + duration,
        )
        self.state.market_events.append(event)
        self.state.news.insert(0, description)
        operations.append(
            DayClosureOperation(
                step="market_event",
                company_id="",
                message=description,
            )
        )

    def _retail_weight(self, company_id: str, decision: CompanyDecision) -> float:
        """Конкурентный вес ритейлера при дележе пула спроса."""
        return (
            self._store_demand_multiplier(company_id)
            * (1.08 if decision.marketing_budget_rub else 1.0)
            / decision.target_price_index
        )

    def _apply_retail_sales(
        self,
        reports: dict[str, CompanyDayReport],
        operations: list[DayClosureOperation],
    ) -> None:
        product_by_id = {product.id: product for product in self.state.products}

        # Группируем ритейлеров по регионам
        by_region: dict[str, list[Company]] = {}
        for company in self.state.companies:
            # Банкрот выбыл с рынка: не продаёт и не входит в знаменатель конкуренции
            if company.role == Role.RETAILER and company.status == CompanyStatus.ACTIVE:
                by_region.setdefault(company.region_id, []).append(company)

        closing_day = self.state.day + 1
        for region_id, retailers in by_region.items():
            region = self._require_region(region_id)
            decisions = {
                c.id: self.state.decisions.get(c.id, CompanyDecision())
                for c in retailers
            }
            weights = {c.id: self._retail_weight(c.id, decisions[c.id]) for c in retailers}

            # Собираем все продукты, которые есть хотя бы у одного ритейлера в регионе
            region_products: set[str] = set()
            for company in retailers:
                region_products.update(
                    self.state.inventories.setdefault(company.id, {}).keys()
                )

            # Данные для истории цен: product_id → (суммарная выручка, суммарные единицы)
            price_data: dict[str, list[int]] = {}

            for product_id in region_products:
                product = product_by_id.get(product_id)
                if not product:
                    continue

                # Стокированные в регионе ритейлеры этого товара
                stocked = [
                    c for c in retailers
                    if self.state.inventories.get(c.id, {}).get(product_id, 0) > 0
                ]
                # Знаменатель доли — конкурентные веса стокированных
                product_weight_total = sum(weights[c.id] for c in stocked) or 1.0

                # Средний по рынку индекс цены (взвешенно по весам) → эластичность спроса
                avg_price_index = (
                    sum(decisions[c.id].target_price_index * weights[c.id] for c in stocked)
                    / product_weight_total
                    if stocked
                    else 1.0
                )
                # Богатый регион (income_index выше) менее чувствителен к цене
                elasticity = self.BASE_PRICE_ELASTICITY / max(region.income_index, 0.5)
                demand_mult = avg_price_index ** (-elasticity)
                demand_mult = max(0.45, min(1.75, demand_mult))

                # Единый пул спроса: база × регион × события × сезон × эластичность по цене
                event_mult = self._demand_event_multiplier(region_id, product_id)
                season_mult = SEASONAL_DEMAND.get(self.state.season, {}).get(product_id, 1.0)
                total_demand = int(
                    product.base_daily_demand
                    * region.demand_index
                    * event_mult
                    * season_mult
                    * demand_mult
                )

                for company in retailers:
                    decision = decisions[company.id]
                    inventory = self.state.inventories.setdefault(company.id, {})
                    available = inventory.get(product_id, 0)
                    if not available:
                        continue

                    # Доля пула пропорциональна конкурентному весу среди стокированных
                    demand_share = int(total_demand * weights[company.id] / product_weight_total)
                    remaining_capacity = max(
                        0,
                        self._daily_capacity(company.id, AssetType.STORE, 1_000_000)
                        - reports[company.id].sold_units,
                    )
                    sold = min(available, max(demand_share, 0), remaining_capacity)
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
                        acc = price_data.setdefault(product_id, [0, 0])
                        acc[0] += revenue
                        acc[1] += sold

            # Записать историю цен региона за этот день
            for product_id, (rev, units) in price_data.items():
                if units > 0:
                    self.state.price_history.append(
                        PricePoint(
                            day=closing_day,
                            region_id=region_id,
                            product_id=product_id,
                            avg_price_rub=rev // units,
                            total_units_sold=units,
                        )
                    )

            # Операционные расходы каждого ритейлера в регионе
            for company in retailers:
                decision = decisions[company.id]
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
            if company.status == CompanyStatus.BANKRUPT:
                continue
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

    def _route_risk(self, shipper_id: str, receiver_id: str) -> float:
        """Риск маршрута = средний logistics_risk регионов отправителя и получателя."""
        risk_by_region = {r.id: r.logistics_risk for r in self.state.regions}
        company_by_id = {c.id: c for c in self.state.companies}
        risks = [
            risk_by_region.get(company_by_id[cid].region_id, 0.15)
            for cid in (shipper_id, receiver_id)
            if cid in company_by_id
        ]
        return sum(risks) / len(risks) if risks else 0.15

    def _apply_due_delivery_orders(
        self,
        reports: dict[str, CompanyDayReport],
        operations: list[DayClosureOperation],
    ) -> None:
        """Исполнить принятые заявки на доставку, срок которых наступил."""
        closing_day = self.state.day + 1
        # Трекеры в рамках одного закрытия дня
        charged_dist_ids: set[str] = set()  # уже списали постоянные расходы склада
        dist_delivered: dict[str, int] = {}  # уже доставлено единиц за день (кэп склада)

        for order in self.state.delivery_orders:
            if order.status != DeliveryStatus.ACCEPTED or order.due_day > closing_day:
                continue
            available = self.state.inventories.get(order.shipper_id, {}).get(
                order.product_id, 0
            )
            if available < order.quantity:
                order.status = DeliveryStatus.CANCELLED
                operations.append(
                    DayClosureOperation(
                        step="delivery_cancelled",
                        company_id=order.shipper_id,
                        quantity=order.quantity,
                        message=f"Заявка {order.id} отменена: у грузоотправителя нет товара.",
                    )
                )
                continue

            # Кэп по дневной мощности склада дистрибьютора
            dist_id = order.distributor_id
            warehouse_cap = self._daily_capacity(dist_id, AssetType.WAREHOUSE, 4_000)
            already_moved = dist_delivered.get(dist_id, 0)
            remaining_cap = max(0, warehouse_cap - already_moved)
            capped_qty = min(order.quantity, remaining_cap)
            if capped_qty == 0:
                operations.append(
                    DayClosureOperation(
                        step="delivery_capacity_exceeded",
                        company_id=dist_id,
                        quantity=order.quantity,
                        message=f"Заявка {order.id} перенесена: склад дистрибьютора исчерпан.",
                    )
                )
                continue

            transferred = self._transfer_fifo(
                order.shipper_id, order.receiver_id, order.product_id, capped_qty
            )
            dist_delivered[dist_id] = already_moved + transferred

            fee = order.fee_rub_per_unit * transferred
            # Грузоотправитель платит за доставку
            reports[order.shipper_id].costs_rub += fee
            reports[order.shipper_id].profit_rub -= fee
            # Транзитные расходы дистрибьютора по риску маршрута (отправитель ↔ получатель)
            route_risk = self._route_risk(order.shipper_id, order.receiver_id)
            transit_cost = int(transferred * route_risk * self.TRANSIT_RISK_COST_PER_UNIT)
            # Дистрибьютор получает вознаграждение (постоянные расходы — раз в день)
            warehouse_costs = self._fixed_costs(dist_id, AssetType.WAREHOUSE, 45_000)
            reports[dist_id].revenue_rub += fee
            reports[dist_id].delivered_units += transferred
            if dist_id not in charged_dist_ids:
                reports[dist_id].costs_rub += warehouse_costs
                reports[dist_id].profit_rub -= warehouse_costs
                charged_dist_ids.add(dist_id)
            reports[dist_id].costs_rub += transit_cost
            reports[dist_id].profit_rub += fee - transit_cost
            order.status = DeliveryStatus.FULFILLED
            operations.append(
                DayClosureOperation(
                    step="delivery_fulfilled",
                    company_id=dist_id,
                    amount_rub=fee - transit_cost,
                    quantity=transferred,
                    message=(
                        f"Заявка {order.id}: доставлено {transferred} ед. {order.product_id}"
                        f" (транзит по риску {route_risk:.2f}: −{transit_cost} ₽)."
                    ),
                )
            )

    # -------------------------------------------------------------------------
    # Delivery orders (public API)
    # -------------------------------------------------------------------------

    def create_delivery_order(
        self, shipper_id: str, payload: DeliveryOrderCreate
    ) -> DeliveryOrder:
        """Создать заявку на доставку. Статус PENDING — ждёт принятия дистрибьютором."""
        self._require_company(shipper_id)
        self._require_company(payload.distributor_id)
        self._require_company(payload.receiver_id)
        self._get_product(payload.product_id)
        if shipper_id == payload.distributor_id or shipper_id == payload.receiver_id:
            raise ValueError("Грузоотправитель, дистрибьютор и получатель должны быть разными.")
        dist = self._require_company(payload.distributor_id)
        if dist.role != Role.DISTRIBUTOR:
            raise ValueError("Указанная компания не является дистрибьютором.")
        order = DeliveryOrder(
            shipper_id=shipper_id,
            distributor_id=payload.distributor_id,
            receiver_id=payload.receiver_id,
            product_id=payload.product_id,
            quantity=payload.quantity,
            fee_rub_per_unit=payload.fee_rub_per_unit,
            due_day=payload.due_day,
            created_day=self.state.day,
        )
        self.state.delivery_orders.append(order)
        return order

    def accept_delivery_order(self, order_id: str, distributor_id: str) -> DeliveryOrder:
        """Дистрибьютор принимает заявку. Только именованный дистрибьютор может принять."""
        order = self._require_delivery_order(order_id)
        if order.distributor_id != distributor_id:
            raise ValueError("Принять заявку может только назначенный дистрибьютор.")
        if order.status != DeliveryStatus.PENDING:
            raise ValueError(f"Заявка {order_id} уже имеет статус {order.status}.")
        order.status = DeliveryStatus.ACCEPTED
        return order

    def cancel_delivery_order(self, order_id: str, requester_id: str) -> DeliveryOrder:
        """Отменить заявку: только грузоотправитель, пока она PENDING или ACCEPTED."""
        order = self._require_delivery_order(order_id)
        if order.shipper_id != requester_id:
            raise ValueError("Отменить заявку может только грузоотправитель.")
        if order.status == DeliveryStatus.FULFILLED:
            raise ValueError("Нельзя отменить уже исполненную заявку.")
        order.status = DeliveryStatus.CANCELLED
        return order

    def _require_delivery_order(self, order_id: str) -> DeliveryOrder:
        order = next(
            (o for o in self.state.delivery_orders if o.id == order_id), None
        )
        if not order:
            raise ValueError(f"Заявка {order_id} не найдена.")
        return order

    # -------------------------------------------------------------------------
    # Market listings
    # -------------------------------------------------------------------------

    def create_listing(
        self, company_id: str, product_id: str, quantity: int, price_rub_per_unit: int
    ) -> MarketListing:
        """Разместить лот на рынке. Товар остаётся у продавца до момента покупки."""
        self._require_company(company_id)
        self._get_product(product_id)
        raw_available = self.state.inventories.get(company_id, {}).get(product_id, 0)
        already_listed = sum(
            lst.quantity_available
            for lst in self.state.market_listings
            if lst.seller_id == company_id and lst.product_id == product_id and lst.is_active
        )
        available = raw_available - already_listed
        if available < quantity:
            raise ValueError(
                f"Недостаточно товара: есть {raw_available} ед., из них {already_listed} уже в активных лотах, свободно {available}"
            )
        listing = MarketListing(
            seller_id=company_id,
            product_id=product_id,
            quantity_available=quantity,
            price_rub_per_unit=price_rub_per_unit,
            day_posted=self.state.day,
        )
        self.state.market_listings.append(listing)
        return listing

    def cancel_listing(self, listing_id: str, company_id: str) -> MarketListing:
        """Отозвать лот с рынка (только продавец)."""
        listing = self._require_listing(listing_id)
        if listing.seller_id != company_id:
            raise PermissionError("Отменить лот может только его продавец")
        if not listing.is_active:
            raise ValueError("Лот уже неактивен")
        listing.is_active = False
        return listing

    def purchase_listing(
        self, listing_id: str, buyer_id: str, quantity: int
    ) -> tuple[int, MarketListing]:
        """Купить товар из лота: мгновенный перевод денег и товара."""
        listing = self._require_listing(listing_id)
        if not listing.is_active:
            raise ValueError("Лот не активен")
        if listing.seller_id == buyer_id:
            raise ValueError("Нельзя покупать у себя")
        if quantity > listing.quantity_available:
            raise ValueError(
                f"Запрошено {quantity}, доступно {listing.quantity_available}"
            )
        seller_stock = (
            self.state.inventories.get(listing.seller_id, {}).get(listing.product_id, 0)
        )
        if seller_stock < quantity:
            raise ValueError(
                f"Продавец имеет только {seller_stock} ед. на складе"
            )
        total_cost = quantity * listing.price_rub_per_unit
        buyer = self._require_company(buyer_id)
        if buyer.cash_rub < total_cost:
            raise ValueError(
                f"Недостаточно средств: нужно {total_cost} руб., есть {buyer.cash_rub} руб."
            )
        seller = self._require_company(listing.seller_id)
        buyer.cash_rub -= total_cost
        seller.cash_rub += total_cost
        self._transfer_fifo(listing.seller_id, buyer_id, listing.product_id, quantity)
        listing.quantity_available -= quantity
        if listing.quantity_available == 0:
            listing.is_active = False
        return total_cost, listing

    def _require_listing(self, listing_id: str) -> MarketListing:
        listing = next(
            (lst for lst in self.state.market_listings if lst.id == listing_id), None
        )
        if listing is None:
            raise ValueError("Лот не найден")
        return listing

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
            "raw_meat": 1_000.0,
            "raw_poultry": 1_200.0,
            "fruit_concentrate": 1_000.0,
            "cocoa": 600.0,
            "sugar_raw": 1_800.0,
            "oilseed": 1_200.0,
        }
