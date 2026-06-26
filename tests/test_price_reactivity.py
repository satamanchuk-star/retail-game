"""Тесты реактивности цен ботов (Фаза 3.2b): NPC реагируют на демпинг конкурентов."""

from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import CompanyDecision, NpcStrategy, Role


def _retailers(engine: GameEngine):
    return [c for c in engine.state.companies if c.is_npc and c.role == Role.RETAILER]


def test_aggressive_undercuts_market_price() -> None:
    engine = GameEngine(build_initial_state())
    aggr = next(c for c in _retailers(engine) if c.npc_strategy == NpcStrategy.AGGRESSIVE)
    rival = next(c for c in _retailers(engine) if c.id != aggr.id)
    rival.region_id = aggr.region_id  # свести в один регион
    engine.state.decisions[rival.id] = CompanyDecision(target_price_index=0.90)

    engine._apply_npc_decisions()

    aggr_price = engine.state.decisions[aggr.id].target_price_index
    assert aggr_price <= 0.90 - 0.05 + 1e-9, "агрессивный должен подрезать рынок"


def test_premium_holds_price_despite_cheap_rivals() -> None:
    engine = GameEngine(build_initial_state())
    retailers = _retailers(engine)
    premium = retailers[0]
    premium.npc_strategy = NpcStrategy.PREMIUM
    rival = retailers[1]
    rival.region_id = premium.region_id
    engine.state.decisions[rival.id] = CompanyDecision(target_price_index=0.80)

    engine._apply_npc_decisions()

    premium_price = engine.state.decisions[premium.id].target_price_index
    assert premium_price >= 1.15, "премиум не должен поддаваться демпингу"


def test_balanced_moves_toward_market() -> None:
    engine = GameEngine(build_initial_state())
    retailers = _retailers(engine)
    balanced = retailers[0]
    balanced.npc_strategy = NpcStrategy.BALANCED
    rival = retailers[1]
    rival.region_id = balanced.region_id
    # дешёвый рынок → balanced должен опуститься ниже своей премиальной базы (1.10/0.95)
    engine.state.decisions[rival.id] = CompanyDecision(target_price_index=0.80)

    engine._apply_npc_decisions()

    price = engine.state.decisions[balanced.id].target_price_index
    assert 0.80 < price < 1.10, f"balanced должен тянуться к рынку, получил {price}"
