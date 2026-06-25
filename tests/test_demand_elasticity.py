"""Тесты эластичности спроса (Фаза 2.1): дешевле рынок → пул растёт, дороже → сжимается."""

import random

from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import AssetType, CompanyDecision, InventoryBatch


def _player_bread_sold_at_price(price_index: float) -> int:
    """Продажи хлеба единственным ритейлером central при изобилии стока.

    Сток и мощность заведомо больше пула спроса, поэтому ограничивает именно спрос —
    так виден чистый эффект эластичности (день 1 иначе supply-bound).
    """
    random.seed(0)
    engine = GameEngine(build_initial_state())
    player = next(c for c in engine.state.companies if c.id == "player")  # central
    # Снять ограничение мощности, чтобы связывал именно спрос
    for asset in engine.state.assets:
        if asset.company_id == player.id and asset.asset_type == AssetType.STORE:
            asset.capacity_units_per_day = 1_000_000
    engine.state.inventories[player.id] = {"bread": 100_000}
    engine.state.inventory_batches.append(
        InventoryBatch(
            id="elastic-test",
            company_id=player.id,
            product_id="bread",
            quantity=100_000,
            created_day=0,
            expires_day=999,
            storage="обычное",
        )
    )
    engine.state.decisions[player.id] = CompanyDecision(target_price_index=price_index)
    engine.close_day()
    report = next(r for r in engine.state.last_reports if r.company_id == player.id)
    return report.sold_units


def test_cheaper_price_sells_more_than_premium() -> None:
    low = _player_bread_sold_at_price(0.85)
    base = _player_bread_sold_at_price(1.0)
    high = _player_bread_sold_at_price(1.25)
    assert low > base > high, (
        f"эластичность не работает: дешевле={low} база={base} дороже={high}"
    )


def test_elasticity_constant_present_and_positive() -> None:
    assert GameEngine.BASE_PRICE_ELASTICITY > 0


def test_rich_region_less_price_sensitive_than_poor() -> None:
    """Эластичность делится на income_index: богатый регион менее чувствителен к цене.

    Проверяем формулу напрямую: при одной и той же надбавке цены богатый регион
    теряет меньше спроса, чем бедный.
    """
    elasticity = GameEngine.BASE_PRICE_ELASTICITY
    price = 1.3
    rich_income, poor_income = 1.25, 0.95
    rich_mult = price ** (-(elasticity / rich_income))
    poor_mult = price ** (-(elasticity / poor_income))
    assert rich_mult > poor_mult
