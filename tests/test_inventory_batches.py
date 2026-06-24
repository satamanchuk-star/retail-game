"""Партии товара защищают FMCG-логику: FIFO, сроки годности и перенос партий."""

from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import ContractCreate, ContractType, InventoryBatch


def test_initial_state_creates_inventory_batches() -> None:
    state = build_initial_state()
    GameEngine(state)

    assert state.inventory_batches
    assert sum(
        batch.quantity
        for batch in state.inventory_batches
        if batch.company_id == "player"
    ) == sum(state.inventories["player"].values())


def test_retail_sales_consume_oldest_batch_first() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    state.inventory_batches = [
        InventoryBatch(
            id="old",
            company_id="player",
            product_id="water",
            quantity=10,
            quality=0.9,
            created_day=0,
            expires_day=10,
            storage="обычное",
        ),
        InventoryBatch(
            id="new",
            company_id="player",
            product_id="water",
            quantity=1_000,
            quality=1.0,
            created_day=1,
            expires_day=20,
            storage="обычное",
        ),
    ]
    engine._sync_legacy_inventories()

    engine.close_day("fifo-sale")

    assert all(batch.id != "old" for batch in state.inventory_batches)
    assert state.inventories["player"]["water"] < 1_000


def test_expired_batches_are_written_off_before_sales() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    state.inventory_batches = [
        InventoryBatch(
            id="expired",
            company_id="player",
            product_id="milk",
            quantity=50,
            quality=0.8,
            created_day=0,
            expires_day=1,
            storage="холодильник",
        )
    ]
    engine._sync_legacy_inventories()

    result = engine.close_day("expiry")

    player_report = next(
        report for report in result.reports if report.company_id == "player"
    )
    assert player_report.expired_units == 50
    assert any(operation.step == "inventory_expired" for operation in result.operations)
    assert state.inventories["player"]["milk"] == 0


def test_contract_preserves_batch_expiration_for_buyer() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    state.inventory_batches = [
        InventoryBatch(
            id="seller-bread",
            company_id="npc_producer",
            product_id="bread",
            quantity=100,
            quality=0.95,
            created_day=0,
            expires_day=2,
            storage="обычное",
        )
    ]
    engine._sync_legacy_inventories()
    engine.create_contract(
        ContractCreate(
            contract_type=ContractType.SUPPLY,
            seller_id="npc_producer",
            buyer_id="npc_distributor",
            product_id="bread",
            quantity=40,
            unit_price_rub=50,
            due_day=1,
            penalty_rub=1_000,
        )
    )

    engine.close_day("batch-transfer")

    buyer_batch = next(
        batch
        for batch in state.inventory_batches
        if batch.company_id == "npc_distributor" and batch.product_id == "bread"
    )
    assert buyer_batch.quantity == 40
    assert buyer_batch.expires_day == 2
    assert buyer_batch.quality == 0.95
