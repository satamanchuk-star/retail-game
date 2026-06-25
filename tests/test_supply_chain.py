"""Тесты наполнения цепочки (Фаза 1.1): значимый набор товаров реально производим."""

from app.domain.balance import PRODUCTION_RECIPES, PRODUCTS, RAW_MATERIALS
from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import Role


def test_catalog_has_meaningful_producible_depth() -> None:
    producible = {r.product_id for r in PRODUCTION_RECIPES}
    assert len(producible) >= 14, "цепочка должна покрывать значимую часть каталога"
    # ключевые категории имеют производственный путь
    for pid in ["cheese", "meat", "chicken", "juice", "chocolate", "oil", "pasta"]:
        assert pid in producible, f"{pid} должен быть производим"


def test_every_recipe_references_known_raw_and_product() -> None:
    raw_ids = {m.id for m in RAW_MATERIALS}
    product_ids = {p.id for p in PRODUCTS}
    for recipe in PRODUCTION_RECIPES:
        assert recipe.product_id in product_ids
        assert recipe.inputs, f"рецепт {recipe.product_id} без сырья"
        for item in recipe.inputs:
            assert item.raw_material_id in raw_ids, (
                f"рецепт {recipe.product_id} ссылается на неизвестное сырьё {item.raw_material_id}"
            )


def test_new_chain_actually_flows_producers_make_new_goods() -> None:
    """За несколько дней NPC-производители реально выпускают новые товары (не только хлеб/молоко)."""
    engine = GameEngine(build_initial_state())
    producers = [c.id for c in engine.state.companies if c.role == Role.PRODUCER]
    assert producers

    for _ in range(4):
        engine.close_day()

    legacy = {"bread", "milk", "yogurt"}
    made_new: set[str] = set()
    for pid in producers:
        for product_id, qty in engine.state.inventories.get(pid, {}).items():
            if qty > 0 and product_id not in legacy:
                made_new.add(product_id)
    assert made_new, "новая цепочка не потекла: производители не выпустили новых товаров"
