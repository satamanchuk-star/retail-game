"""Совместимость старого API симуляции с новым движком закрытия рынка."""

from copy import deepcopy

from app.domain.engine import GameEngine
from app.domain.models import DayResult, GameState, Role


def simulate_retail_day(state: GameState, company_id: str) -> DayResult:
    """Рассчитать один день продаж для ритейлера.

    Функция сохранена для обратной совместимости тестов и API первой версии.
    Новый код должен использовать `GameEngine.close_day()`.
    """
    company = next((item for item in state.companies if item.id == company_id), None)
    if company is None:
        raise ValueError("Компания не найдена")

    if company.role != Role.RETAILER:
        raise ValueError("Первый симулятор поддерживает только ритейлера")

    sandbox = deepcopy(state)
    result = GameEngine(sandbox).close_day()
    report = next(item for item in result.reports if item.company_id == company_id)
    return DayResult(
        day=result.day,
        revenue_rub=report.revenue_rub,
        costs_rub=report.costs_rub,
        profit_rub=report.profit_rub,
        sold_units=report.sold_units,
        news=result.news,
    )
