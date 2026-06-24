"""Демо-сценарий делает результат разработки видимым без ручной настройки рынка."""

from app.domain.engine import GameEngine
from app.domain.models import (
    CompanyDecision,
    ContractCreate,
    ContractStatus,
    DemoDaySnapshot,
    DemoRunResult,
    GameState,
    Role,
)


def run_demo_scenario(state: GameState, days: int = 7) -> DemoRunResult:
    """Запустить короткий сценарий рынка и вернуть сводку по каждому дню."""
    engine = GameEngine(state)
    snapshots: list[DemoDaySnapshot] = []

    for step in range(days):
        _prepare_demo_decisions(state, step)
        _ensure_demo_contract(state, engine)
        result = engine.close_day()
        fulfilled = sum(
            1 for contract in state.contracts if contract.status == ContractStatus.FULFILLED
        )
        breached = sum(
            1 for contract in state.contracts if contract.status == ContractStatus.BREACHED
        )
        snapshots.append(
            DemoDaySnapshot(
                day=result.day,
                total_cash_rub=sum(company.cash_rub for company in state.companies),
                total_profit_rub=sum(report.profit_rub for report in result.reports),
                sold_units=sum(report.sold_units for report in result.reports),
                produced_units=sum(report.produced_units for report in result.reports),
                delivered_units=sum(report.delivered_units for report in result.reports),
                fulfilled_contracts=fulfilled,
                breached_contracts=breached,
            )
        )

    return DemoRunResult(
        days=snapshots,
        summary=f"Демо завершено: рассчитано {days} игровых дней рынка.",
    )


def _prepare_demo_decisions(state: GameState, step: int) -> None:
    """Задать разные решения ролям, чтобы в отчёте была динамика."""
    for company in state.companies:
        if company.role == Role.RETAILER:
            state.decisions[company.id] = CompanyDecision(
                target_price_index=0.95 + (step % 3) * 0.08,
                marketing_budget_rub=40_000 + step * 8_000,
                ready=True,
            )
        elif company.role == Role.PRODUCER:
            state.decisions[company.id] = CompanyDecision(
                production_units=1_200 + step * 120,
                ready=True,
            )
        elif company.role == Role.DISTRIBUTOR:
            state.decisions[company.id] = CompanyDecision(
                logistics_capacity_units=1_500 + step * 150,
                ready=True,
            )


def _ensure_demo_contract(state: GameState, engine: GameEngine) -> None:
    """Создать ближайший контракт поставки хлеба, если на день нет активных контрактов."""
    has_active_contract = any(
        contract.status == ContractStatus.ACTIVE and contract.due_day == state.day + 1
        for contract in state.contracts
    )
    if has_active_contract:
        return

    producer = next(company for company in state.companies if company.role == Role.PRODUCER)
    retailer = next(company for company in state.companies if company.role == Role.RETAILER)
    engine.create_contract(
        ContractCreate(
            contract_type="supply",
            seller_id=producer.id,
            buyer_id=retailer.id,
            product_id="bread",
            quantity=350,
            unit_price_rub=52,
            due_day=state.day + 1,
            penalty_rub=5_000,
        )
    )
