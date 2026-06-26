"""Тесты экспансии ботов (Фаза 3.2): расширяются только когда прибыльны."""

from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import CompanyDayReport, Role


def _assets(engine: GameEngine, company_id: str) -> int:
    return sum(1 for a in engine.state.assets if a.company_id == company_id)


def test_thriving_bot_expands_with_new_object() -> None:
    engine = GameEngine(build_initial_state())
    producer = next(c for c in engine.state.companies if c.role == Role.PRODUCER)
    producer.cash_rub = 60_000_000
    reports = {producer.id: CompanyDayReport(company_id=producer.id, profit_rub=1_500_000)}
    before = _assets(engine, producer.id)

    news = engine._npc_try_expand(producer, reports)

    assert news is not None
    assert _assets(engine, producer.id) == before + 1


def test_unprofitable_bot_does_not_expand_even_if_cash_rich() -> None:
    engine = GameEngine(build_initial_state())
    producer = next(c for c in engine.state.companies if c.role == Role.PRODUCER)
    producer.cash_rub = 60_000_000  # денег полно…
    reports = {producer.id: CompanyDayReport(company_id=producer.id, profit_rub=0)}  # …но не прибылен
    before = _assets(engine, producer.id)

    assert engine._npc_try_expand(producer, reports) is None
    assert _assets(engine, producer.id) == before


def test_expansion_respects_object_cap() -> None:
    engine = GameEngine(build_initial_state())
    retailer = next(c for c in engine.state.companies if c.is_npc and c.role == Role.RETAILER)
    retailer.cash_rub = 100_000_000
    report = {retailer.id: CompanyDayReport(company_id=retailer.id, profit_rub=2_000_000)}
    # строим до потолка (3 магазина), дальше — None
    for _ in range(5):
        engine._npc_try_expand(retailer, report)
    assert _assets(engine, retailer.id) <= 3
