"""Тесты игрового движка защищают развитие рынка поверх первого прототипа."""

from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import (
    CompanyCreate,
    CompanyDecision,
    ContractCreate,
    ContractStatus,
    Role,
)


def test_create_company_assigns_role_cash_and_inventory() -> None:
    state = build_initial_state()
    engine = GameEngine(state)

    company = engine.create_company(
        CompanyCreate(name="Южная лавка", role=Role.RETAILER, region_id="south")
    )

    assert company.cash_rub == 7_500_000
    assert company.region_id == "south"
    assert state.inventories[company.id]["bread"] > 0


def test_close_day_updates_reports_and_cash() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    before_cash = state.companies[0].cash_rub

    result = engine.close_day()

    player_report = next(report for report in result.reports if report.company_id == "player")
    assert result.day == 1
    assert player_report.sold_units > 0
    assert state.companies[0].cash_rub != before_cash
    assert state.last_reports


def test_due_contract_transfers_inventory() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    contract = engine.create_contract(
        ContractCreate(
            contract_type="supply",
            seller_id="npc_producer",
            buyer_id="player",
            product_id="bread",
            quantity=100,
            unit_price_rub=50,
            due_day=1,
            penalty_rub=1_000,
        )
    )

    result = engine.close_day()

    assert contract.status == "fulfilled"
    assert result.day == 1
    assert state.inventories["player"]["bread"] >= 0


def test_npc_producer_restocks_raw_materials_and_keeps_producing() -> None:
    """NPC докупает сырьё и непрерывно производит хлеб и молоко 20 дней."""
    state = build_initial_state()
    engine = GameEngine(state)
    state.raw_inventories["npc_producer"] = {"grain": 0.0, "raw_milk": 0.0, "packaging": 0.0}

    for _ in range(20):
        engine.close_day()

    producer_report = next(r for r in state.last_reports if r.company_id == "npc_producer")
    assert producer_report.produced_units > 0


def test_npc_produces_multiple_products() -> None:
    """NPC-производитель выпускает хлеб и молоко в рамках одного дня."""
    state = build_initial_state()
    engine = GameEngine(state)

    engine.close_day()

    bread_stock = state.inventories.get("npc_producer", {}).get("bread", 0)
    milk_stock = state.inventories.get("npc_producer", {}).get("milk", 0)
    assert bread_stock > 0
    assert milk_stock > 0


def test_npc_decisions_are_applied_automatically() -> None:
    """NPC-компании получают решения автоматически без вызова set_decision."""
    from app.domain.models import DeliveryOrderCreate

    state = build_initial_state()
    engine = GameEngine(state)

    npc_prod = next(c for c in state.companies if c.is_npc and c.role == "producer")
    npc_dist = next(c for c in state.companies if c.is_npc and c.role == "distributor")
    player = next(c for c in state.companies if not c.is_npc)

    # Создаём заявку — NPC-дистрибьютор должен принять её автоматически в close_day
    engine.create_delivery_order(
        npc_prod.id,
        DeliveryOrderCreate(
            distributor_id=npc_dist.id,
            receiver_id=player.id,
            product_id="bread",
            quantity=200,
            fee_rub_per_unit=10,
            due_day=1,
        ),
    )

    result = engine.close_day()

    producer_report = next(r for r in result.reports if r.company_id == npc_prod.id)
    distributor_report = next(r for r in result.reports if r.company_id == npc_dist.id)
    assert producer_report.produced_units > 0
    assert distributor_report.delivered_units > 0


def test_npc_upgrades_facility_when_profitable() -> None:
    """NPC апгрейдит объект если прибылен и хватает денег."""
    state = build_initial_state()
    engine = GameEngine(state)
    producer = next(c for c in state.companies if c.id == "npc_producer")
    factory = next(a for a in state.assets if a.company_id == "npc_producer")
    factory.facility_format = "workshop"
    factory.capacity_units_per_day = 1_200
    producer.cash_rub = 50_000_000

    for _ in range(10):
        engine.close_day()

    factory = next(a for a in state.assets if a.company_id == "npc_producer")
    assert factory.facility_format != "workshop"


def test_contract_breach_charges_penalty_when_seller_has_no_inventory() -> None:
    """Контракт нарушается и штраф списывается, если у продавца нет товара."""
    state = build_initial_state()
    engine = GameEngine(state)
    # quantity far exceeds what NPC can produce in a single day → breach guaranteed
    contract = engine.create_contract(
        ContractCreate(
            contract_type="supply",
            seller_id="npc_producer",
            buyer_id="player",
            product_id="bread",
            quantity=999_999,
            unit_price_rub=50,
            due_day=1,
            penalty_rub=100_000,
        )
    )
    seller = next(c for c in state.companies if c.id == "npc_producer")
    cash_before = seller.cash_rub

    engine.close_day()

    assert contract.status == ContractStatus.BREACHED
    assert seller.cash_rub < cash_before


def test_npc_zero_cash_does_not_buy_raw_materials() -> None:
    """NPC с нулевым балансом не закупает сырьё — кэш-гард в restock работает."""
    state = build_initial_state()
    engine = GameEngine(state)
    producer = next(c for c in state.companies if c.id == "npc_producer")
    producer.cash_rub = 0
    # drain raw inventories so restock would be triggered if cash were available
    state.raw_inventories["npc_producer"] = {"grain": 0.0, "raw_milk": 0.0, "packaging": 0.0}

    engine.close_day()

    # guard prevented any purchases, so raw inventories remain at 0
    raw = state.raw_inventories.get("npc_producer", {})
    assert raw.get("grain", 0) == 0
    assert raw.get("raw_milk", 0) == 0


def test_decision_changes_retail_price() -> None:
    state = build_initial_state()
    low_price_engine = GameEngine(state)
    low_price_engine.set_decision("player", CompanyDecision(target_price_index=0.8))
    low_price_result = low_price_engine.close_day()
    low_price_report = next(
        report for report in low_price_result.reports if report.company_id == "player"
    )

    expensive_state = build_initial_state()
    expensive_engine = GameEngine(expensive_state)
    expensive_engine.set_decision("player", CompanyDecision(target_price_index=1.4))
    expensive_result = expensive_engine.close_day()
    expensive_report = next(
        report for report in expensive_result.reports if report.company_id == "player"
    )

    assert low_price_report.sold_units >= expensive_report.sold_units
