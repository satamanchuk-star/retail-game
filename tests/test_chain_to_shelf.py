"""Тесты протекания цепочки до полки (Фаза 1.4): ассортимент расширяется здраво."""

import random

from app.domain.engine import GameEngine, build_initial_state


def test_chain_reaches_shelf_many_products_sell() -> None:
    """За пару недель на полку выходит существенно больше 5 стартовых товаров."""
    random.seed(0)
    engine = GameEngine(build_initial_state())
    for _ in range(15):
        engine.close_day()
    sold = {p.product_id for p in engine.state.price_history}
    assert len(sold) >= 10, f"цепочка не дошла до полки: продаётся всего {len(sold)} товаров"


def _retailer_with_new_listing(cash: int) -> tuple[GameEngine, str]:
    """NPC-ритейлер заданного достатка + лот нового товара (шоколад) на рынке."""
    engine = GameEngine(build_initial_state())
    retailer = next(c for c in engine.state.companies if c.id == "npc_retailer")
    retailer.cash_rub = cash
    seller = next(c for c in engine.state.companies if c.id == "player")  # не-NPC, не конкурент
    engine.state.inventories.setdefault(seller.id, {})["chocolate"] = 5_000
    engine._create_batches_from_inventory(seller.id, {"chocolate": 5_000})
    engine.create_listing(seller.id, "chocolate", 5_000, 130)
    return engine, retailer.id


def test_unhealthy_retailer_does_not_add_new_line() -> None:
    engine, ret_id = _retailer_with_new_listing(cash=1_000_000)  # ниже порога
    engine._apply_market_npc_purchases([])
    assert engine.state.inventories.get(ret_id, {}).get("chocolate", 0) == 0


def test_healthy_retailer_adds_new_line() -> None:
    engine, ret_id = _retailer_with_new_listing(cash=20_000_000)  # выше порога
    engine._apply_market_npc_purchases([])
    assert engine.state.inventories.get(ret_id, {}).get("chocolate", 0) > 0
