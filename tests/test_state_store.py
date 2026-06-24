"""Тесты файлового снапшота защищают прогресс прототипа от потери при рестарте."""

from app.domain.engine import GameEngine
from app.domain.models import CompanyCreate, Role
from app.services.state_store import StateStore


def test_state_store_saves_and_loads_world_snapshot(tmp_path) -> None:
    path = tmp_path / "game_state.json"
    store = StateStore(str(path))
    state = store.load_or_create()
    engine = GameEngine(state)

    company = engine.create_company(
        CompanyCreate(name="Сохраняемый магазин", role=Role.RETAILER, region_id="central")
    )
    store.save(state)

    restored_state = StateStore(str(path)).load_or_create()

    assert path.exists()
    assert restored_state.day == state.day
    assert any(item.id == company.id for item in restored_state.companies)
    assert company.id in restored_state.inventories


def test_disabled_state_store_does_not_write_file(tmp_path) -> None:
    store = StateStore()
    state = store.load_or_create()

    store.save(state)

    assert store.enabled is False
    assert list(tmp_path.iterdir()) == []
