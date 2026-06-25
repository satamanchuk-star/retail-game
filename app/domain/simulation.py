"""Симуляция дня (legacy) + харнесс баланса для измерения здоровья экономики.

Харнесс прогоняет мир на N дней без игрока (только NPC) и считает метрики:
инфляция цен, банкротства, концентрация рынка (HHI), оборот. Это объективный
«тест на баланс» для калибровки экономических изменений (см. docs/ROADMAP.md).
"""

import random
from copy import deepcopy

from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import CompanyStatus, DayResult, GameState, Role
from pydantic import BaseModel, Field


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


class BalanceReport(BaseModel):
    """Срез здоровья экономики после прогона мира на N дней (без игрока)."""

    days: int
    companies: int
    bankruptcies: int
    game_over: bool
    winner_name: str | None
    leader_cash_rub: int
    min_cash_rub: int
    cash_hhi: float = Field(description="Концентрация капитала, 0..10000 (выше = монополия)")
    total_units_sold: int
    price_inflation_pct: float = Field(description="Рост среднего чека с начала прогона, %")
    producible_products: int = Field(description="Товаров с рецептом (глубина цепочки)")
    catalog_products: int

    def summary(self) -> str:
        flags = []
        if self.bankruptcies:
            flags.append(f"банкротств {self.bankruptcies}")
        if self.cash_hhi > 5000:
            flags.append("монополизация")
        if abs(self.price_inflation_pct) > 50:
            flags.append("ценовой разнос")
        if self.producible_products * 2 < self.catalog_products:
            flags.append("полая цепочка")
        health = "⚠️ " + ", ".join(flags) if flags else "✅ в норме"
        return (
            f"{self.days} дн · компаний {self.companies} · {health}\n"
            f"  лидер {self.leader_cash_rub:,} ₽ · аутсайдер {self.min_cash_rub:,} ₽ · "
            f"HHI {self.cash_hhi:.0f}\n"
            f"  продано {self.total_units_sold:,} ед · инфляция чека {self.price_inflation_pct:+.1f}% · "
            f"цепочка {self.producible_products}/{self.catalog_products} товаров"
        )


# Фиксированная staple-корзина: меряем инфляцию по одним и тем же товарам, чтобы
# расширение ассортимента в дорогие позиции не выдавалось за инфляцию.
_STAPLE_BASKET = ("bread", "milk")


def _basket_price_on_day(state: GameState, day: int) -> float:
    """Цена staple-корзины за день, взвешенная по проданным единицам."""
    points = [
        p
        for p in state.price_history
        if p.day == day and p.product_id in _STAPLE_BASKET
    ]
    units = sum(p.total_units_sold for p in points)
    if not units:
        return 0.0
    return sum(p.avg_price_rub * p.total_units_sold for p in points) / units


def run_balance_simulation(days: int = 30, seed: int | None = 42) -> BalanceReport:
    """Прогнать мир на N дней (только NPC) и вернуть метрики здоровья экономики."""
    if seed is not None:
        random.seed(seed)
    engine = GameEngine(build_initial_state())
    for _ in range(days):
        if engine.state.game_over:
            break
        engine.close_day()

    state = engine.state
    cashes = [c.cash_rub for c in state.companies]
    positive = [c for c in cashes if c > 0]
    total_positive = sum(positive) or 1
    cash_hhi = sum((c / total_positive) ** 2 for c in positive) * 10_000

    basket_days = sorted(
        {p.day for p in state.price_history if p.product_id in _STAPLE_BASKET}
    )
    first_day = basket_days[0] if basket_days else 0
    last_day = basket_days[-1] if basket_days else 0
    start_price = _basket_price_on_day(state, first_day)
    end_price = _basket_price_on_day(state, last_day)
    inflation = ((end_price - start_price) / start_price * 100) if start_price else 0.0

    winner = next((c for c in state.companies if c.id == state.winner_company_id), None)

    return BalanceReport(
        days=state.day,
        companies=len(state.companies),
        bankruptcies=sum(1 for c in state.companies if c.status == CompanyStatus.BANKRUPT),
        game_over=state.game_over,
        winner_name=winner.name if winner else None,
        leader_cash_rub=max(cashes) if cashes else 0,
        min_cash_rub=min(cashes) if cashes else 0,
        cash_hhi=cash_hhi,
        total_units_sold=sum(p.total_units_sold for p in state.price_history),
        price_inflation_pct=inflation,
        producible_products=len({r.product_id for r in state.production_recipes}),
        catalog_products=len(state.products),
    )


if __name__ == "__main__":  # pragma: no cover
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    print(run_balance_simulation(days=n).summary())
