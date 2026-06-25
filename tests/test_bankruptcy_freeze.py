"""Тесты заморозки банкрота: выбывшая компания не торгует, не тратит и не воскресает."""

from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import CompanyStatus, Role


def _engine() -> GameEngine:
    return GameEngine(build_initial_state())


def test_bankrupt_company_cash_is_frozen_over_many_days() -> None:
    """Кэш банкрота не двигается: ни fixed costs, ни проценты, ни продажи."""
    engine = _engine()
    company = engine.state.companies[0]
    company.status = CompanyStatus.BANKRUPT
    company.cash_rub = -15_000_000

    for _ in range(5):
        engine.close_day()

    assert company.cash_rub == -15_000_000
    # и статус не «воскресает»
    assert company.status == CompanyStatus.BANKRUPT


def test_bankrupt_producer_does_not_produce() -> None:
    """Банкрот-производитель не расходует сырьё и не выпускает товар."""
    engine = _engine()
    producer = next(c for c in engine.state.companies if c.role == Role.PRODUCER)
    producer.status = CompanyStatus.BANKRUPT
    raw_before = dict(engine.state.raw_inventories.get(producer.id, {}))

    engine.close_day()

    raw_after = engine.state.raw_inventories.get(producer.id, {})
    assert raw_after == raw_before


def _competitor_sold_units(*, bankrupt: bool) -> int:
    """sold_units ритейлера за день при активном/банкротном статусе (в общем регионе)."""
    engine = _engine()
    player = next(c for c in engine.state.companies if c.id == "player")
    competitor = next(c for c in engine.state.companies if c.id == "npc_retailer")
    competitor.region_id = player.region_id  # свести в один регион для конкуренции
    if bankrupt:
        competitor.status = CompanyStatus.BANKRUPT

    engine.close_day()
    report = next(r for r in engine.state.last_reports if r.company_id == competitor.id)
    return report.sold_units


def test_bankrupt_retailer_sells_nothing() -> None:
    """Активный ритейлер продаёт; банкрот выбыл с рынка и не продаёт ничего."""
    assert _competitor_sold_units(bankrupt=False) > 0
    assert _competitor_sold_units(bankrupt=True) == 0
