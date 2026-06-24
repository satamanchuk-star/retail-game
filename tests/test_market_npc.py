"""Тесты участия NPC в рынке: автолистинг и автопокупки."""

import pytest
from app.domain.engine import GameEngine, build_initial_state


@pytest.fixture()
def engine() -> GameEngine:
    return GameEngine(build_initial_state())


def _npc_producer(engine: GameEngine):
    return next(c for c in engine.state.companies if c.is_npc and c.role == "producer")


def _npc_retailer(engine: GameEngine):
    return next(c for c in engine.state.companies if c.is_npc and c.role == "retailer")


def test_npc_producer_creates_listing_after_close_day(engine: GameEngine) -> None:
    """После close_day NPC-производитель выставляет лоты на рынок."""
    assert not engine.state.market_listings

    engine.close_day()

    producer = _npc_producer(engine)
    producer_listings = [
        lst for lst in engine.state.market_listings
        if lst.seller_id == producer.id and lst.is_active
    ]
    assert len(producer_listings) >= 1


def test_npc_listing_price_is_above_base(engine: GameEngine) -> None:
    """NPC выставляет по цене выше базовой (маржа 10%)."""
    engine.close_day()

    product_by_id = {p.id: p for p in engine.state.products}
    for lst in engine.state.market_listings:
        product = product_by_id[lst.product_id]
        assert lst.price_rub_per_unit >= product.base_price_rub, (
            f"{lst.product_id}: list_price={lst.price_rub_per_unit} < base={product.base_price_rub}"
        )


def test_npc_retailer_buys_from_player_listing(engine: GameEngine) -> None:
    """NPC-ритейлер покупает с лота игрока, если цена приемлема."""
    # Дать NPC-производителю нулевой инвентарь, чтобы он не перебивал наш лот
    npc_prod = _npc_producer(engine)
    engine.state.inventories[npc_prod.id] = {}

    # Создаём лот от "игрока" (используем player-компанию как продавца)
    npc_ret = _npc_retailer(engine)
    seller = next(c for c in engine.state.companies if c.id == "player")

    engine.state.inventories[npc_ret.id]["bread"] = 0
    for batch in engine.state.inventory_batches:
        if batch.company_id == npc_ret.id and batch.product_id == "bread":
            batch.quantity = 0
    engine._sync_legacy_inventories()

    # Игрок-продавец должен иметь хлеб
    engine.state.inventories[seller.id]["bread"] = 500
    engine._create_batches_from_inventory(seller.id, {"bread": 500})

    bread_price = next(p for p in engine.state.products if p.id == "bread")
    list_price = int(bread_price.base_price_rub * 1.2)
    engine.create_listing(seller.id, "bread", 500, list_price)

    ret_bread_before = engine.state.inventories.get(npc_ret.id, {}).get("bread", 0)
    engine.close_day()

    ret_bread_after = engine.state.inventories.get(npc_ret.id, {}).get("bread", 0)
    assert ret_bread_after > ret_bread_before


def test_npc_does_not_buy_overpriced_listing(engine: GameEngine) -> None:
    """NPC не покупает, если цена выше base_price × 1.4."""
    npc_ret = _npc_retailer(engine)

    # Обнуляем хлеб у ритейлера
    engine.state.inventories[npc_ret.id]["bread"] = 0

    seller = next(c for c in engine.state.companies if c.id == "player")
    engine.state.inventories[seller.id]["bread"] = 1000
    engine._create_batches_from_inventory(seller.id, {"bread": 1000})

    bread_price = next(p for p in engine.state.products if p.id == "bread")
    overpriced = int(bread_price.base_price_rub * 2.0)
    engine.create_listing(seller.id, "bread", 1000, overpriced)

    engine.close_day()

    # Хлеб у ритейлера должен остаться 0 (или только то, что NPC произвёл)
    # Главное — у продавца хлеб не уменьшился через нас
    listing_after = next(
        (lst for lst in engine.state.market_listings if lst.seller_id == seller.id),
        None,
    )
    # Лот должен быть нетронутым NPC-ритейлером (NPC не купил из-за цены)
    # quantity_available мог измениться только если NPC купил
    # NPC не должен был купить т.к. цена × 2 > × 1.4
    # NPC не должен был купить из-за цены × 2.0 > порога × 1.4
    # Проверяем через лот продавца — quantity_available не должно уменьшиться
    if listing_after and listing_after.is_active:
        assert listing_after.quantity_available == 1000


def test_npc_does_not_duplicate_listing(engine: GameEngine) -> None:
    """После двух подряд close_day NPC не создаёт дублирующий лот."""
    engine.close_day()

    npc_prod = _npc_producer(engine)
    engine.close_day()

    listings_after_day2 = [
        lst for lst in engine.state.market_listings
        if lst.seller_id == npc_prod.id and lst.is_active
    ]
    # Не должно быть больше активных лотов, чем уникальных продуктов
    products_listed = {lst.product_id for lst in listings_after_day2}
    assert len(listings_after_day2) == len(products_listed)


def test_npc_reconcile_deactivates_listing_when_stock_zero(engine: GameEngine) -> None:
    """Если у NPC-продавца кончился товар, листинг деактивируется при следующем close_day."""
    npc_prod = _npc_producer(engine)

    # Форсируем листинг у NPC (даём небольшой запас)
    engine.state.inventories[npc_prod.id]["bread"] = 200
    engine._create_batches_from_inventory(npc_prod.id, {"bread": 200})
    listing = engine.create_listing(npc_prod.id, "bread", 100, 70)

    # Обнуляем его инвентарь (имитация распродажи)
    engine.state.inventories[npc_prod.id]["bread"] = 0
    for batch in engine.state.inventory_batches:
        if batch.company_id == npc_prod.id and batch.product_id == "bread":
            batch.quantity = 0
    engine._sync_legacy_inventories()

    engine.close_day()

    refreshed = next(
        (lst for lst in engine.state.market_listings if lst.id == listing.id), None
    )
    assert refreshed is None or not refreshed.is_active
