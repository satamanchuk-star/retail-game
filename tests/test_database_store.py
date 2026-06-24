"""Тесты DB-снапшота защищают переход от файла к durable-хранилищу."""

import pytest
from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import CompanyCreate, Role
from app.services.database_store import DatabaseSnapshotStore


@pytest.mark.asyncio
async def test_database_snapshot_store_persists_world_between_connections(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'world.db'}"
    store = DatabaseSnapshotStore(db_url)
    await store.connect()
    state = await store.load_or_create()
    engine = GameEngine(state)
    company = engine.create_company(
        CompanyCreate(name="DB магазин", role=Role.RETAILER, region_id="central")
    )
    await store.save(state)
    await store.close()

    restored_store = DatabaseSnapshotStore(db_url)
    await restored_store.connect()
    restored = await restored_store.load_or_create()
    await restored_store.close()

    assert any(item.id == company.id for item in restored.companies)
    assert company.id in restored.inventories


@pytest.mark.asyncio
async def test_database_snapshot_store_reset_recreates_initial_world(tmp_path) -> None:
    store = DatabaseSnapshotStore(f"sqlite+aiosqlite:///{tmp_path / 'world.db'}")
    await store.connect()
    state = await store.load_or_create()
    state.day = 5
    await store.save(state)

    reset_state = await store.reset()
    restored = await store.load_or_create()
    await store.close()

    assert reset_state.day == 0
    assert restored.day == 0
    assert len(restored.companies) == len(build_initial_state().companies)
