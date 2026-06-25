"""Тесты умных ботов (Фаза 3.1): NPC распределяют мощность по марже/спросу и стратегии."""

from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import NpcStrategy, Role


def _plan_units(strategy: NpcStrategy) -> dict[str, int]:
    engine = GameEngine(build_initial_state())
    producer = next(c for c in engine.state.companies if c.role == Role.PRODUCER)
    producer.npc_strategy = strategy
    return {r.product_id: u for r, u in engine._npc_production_plan(producer)}


def test_plan_uses_most_of_capacity() -> None:
    engine = GameEngine(build_initial_state())
    producer = next(c for c in engine.state.companies if c.role == Role.PRODUCER)
    from app.domain.models import AssetType

    capacity = engine._daily_capacity(producer.id, AssetType.FACTORY, 0)
    total = sum(u for _, u in engine._npc_production_plan(producer))
    assert capacity > 0
    assert 0.7 * capacity <= total <= capacity  # ~90% бюджет минус округления


def test_plan_favors_high_margin_over_low_margin() -> None:
    units = _plan_units(NpcStrategy.BALANCED)
    # мясо (цена 560) маржинальнее сахара (цена 90) → выпускается больше
    assert units.get("meat", 0) > units.get("sugar", 0)


def test_premium_tilts_to_expensive_aggressive_to_volume() -> None:
    premium = _plan_units(NpcStrategy.PREMIUM)
    aggressive = _plan_units(NpcStrategy.AGGRESSIVE)
    # премиум сильнее льёт в дорогое мясо, чем агрессивный
    assert premium.get("meat", 0) > aggressive.get("meat", 0)
    # агрессивный сильнее льёт в объёмный хлеб, чем премиум
    assert aggressive.get("bread", 0) > premium.get("bread", 0)
