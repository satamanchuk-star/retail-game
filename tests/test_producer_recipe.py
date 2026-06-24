"""Тесты выбора рецепта производителем: хлеб / молоко / кефир."""

import pytest
from app.domain.engine import GameEngine, build_initial_state
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture()
def client() -> TestClient:
    c = TestClient(app)
    c.post("/api/reset")
    return c


def _session(client: TestClient) -> str:
    return client.post("/api/sessions", json={"name": "Рецепт-тест"}).json()["id"]


def _register(client: TestClient, username: str) -> dict:
    resp = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123!"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _company(client: TestClient, sid: str, headers: dict) -> dict:
    return client.post(
        f"/api/sessions/{sid}/companies",
        json={"name": "Завод", "role": "producer", "region_id": "central"},
        headers=headers,
    ).json()


# --- Unit tests (прямо через engine, без HTTP) ---

def test_resolve_recipe_none_defaults_to_bread() -> None:
    """_resolve_recipe(None) → дефолтный рецепт хлеба."""
    engine = GameEngine(build_initial_state())
    assert engine._resolve_recipe(None).product_id == "bread"


def test_resolve_recipe_milk() -> None:
    """recipe_id='milk' возвращает молочный рецепт."""
    engine = GameEngine(build_initial_state())
    recipe = engine._resolve_recipe("milk")
    assert recipe.product_id == "milk"


def test_resolve_recipe_yogurt() -> None:
    """recipe_id='yogurt' возвращает новый рецепт кефира."""
    engine = GameEngine(build_initial_state())
    recipe = engine._resolve_recipe("yogurt")
    assert recipe.product_id == "yogurt"


def test_resolve_unknown_recipe_falls_back_to_default() -> None:
    """Неизвестный recipe_id → дефолтный рецепт (хлеб)."""
    engine = GameEngine(build_initial_state())
    recipe = engine._resolve_recipe("nonexistent_product")
    assert recipe.product_id == "bread"


def test_three_recipes_available() -> None:
    """После добавления кефира в балансе три рецепта."""
    engine = GameEngine(build_initial_state())
    ids = {r.product_id for r in engine.state.production_recipes}
    assert "bread" in ids
    assert "milk" in ids
    assert "yogurt" in ids


# --- Интеграционные тесты через API ---

def test_player_produces_milk_when_recipe_set(client: TestClient) -> None:
    """Игрок выбирает молоко — авто-close после сдачи решения, молоко растёт, хлеб нет."""
    sid = _session(client)
    h = _register(client, "prod_milk")
    co = _company(client, sid, h)

    inv_before = client.get(f"/api/sessions/{sid}/state").json()["inventories"]
    bread_before = inv_before[co["id"]].get("bread", 0)
    milk_before = inv_before[co["id"]].get("milk", 0)

    # Единственный игрок → submit вызывает авто-close
    client.post(
        f"/api/sessions/{sid}/decisions/{co['id']}",
        json={"production_units": 200, "recipe_id": "milk"},
        headers=h,
    )

    inv_after = client.get(f"/api/sessions/{sid}/state").json()["inventories"]
    assert inv_after[co["id"]].get("milk", 0) > milk_before
    assert inv_after[co["id"]].get("bread", 0) == bread_before  # хлеб не производился


def test_player_produces_yogurt_when_recipe_set(client: TestClient) -> None:
    """Игрок выбирает кефир — авто-close, yogurt появляется на складе."""
    sid = _session(client)
    h = _register(client, "prod_yogurt")
    co = _company(client, sid, h)

    inv_before = client.get(f"/api/sessions/{sid}/state").json()["inventories"]
    yogurt_before = inv_before[co["id"]].get("yogurt", 0)

    client.post(
        f"/api/sessions/{sid}/decisions/{co['id']}",
        json={"production_units": 150, "recipe_id": "yogurt"},
        headers=h,
    )

    inv_after = client.get(f"/api/sessions/{sid}/state").json()["inventories"]
    assert inv_after[co["id"]].get("yogurt", 0) > yogurt_before


def test_player_defaults_to_bread_without_recipe_id(client: TestClient) -> None:
    """Без recipe_id производитель делает хлеб (авто-close)."""
    sid = _session(client)
    h = _register(client, "prod_default")
    co = _company(client, sid, h)

    inv_before = client.get(f"/api/sessions/{sid}/state").json()["inventories"]
    bread_before = inv_before[co["id"]].get("bread", 0)

    client.post(
        f"/api/sessions/{sid}/decisions/{co['id']}",
        json={"production_units": 200},
        headers=h,
    )

    inv_after = client.get(f"/api/sessions/{sid}/state").json()["inventories"]
    assert inv_after[co["id"]].get("bread", 0) > bread_before
