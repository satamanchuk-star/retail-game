"""Тесты игрового движка защищают развитие рынка поверх первого прототипа."""

from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import CompanyCreate, CompanyDecision, ContractCreate, Role


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
