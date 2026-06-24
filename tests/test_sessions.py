"""Тесты мультиплеерного реестра сессий: изоляция, жизненный цикл, API."""

import pytest
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture()
def client() -> TestClient:
    c = TestClient(app)
    c.post("/api/reset")
    return c


def test_list_sessions_includes_default(client: TestClient) -> None:
    response = client.get("/api/sessions")

    assert response.status_code == 200
    ids = [s["id"] for s in response.json()]
    assert "default" in ids


def test_create_session_returns_fresh_state(client: TestClient) -> None:
    response = client.post("/api/sessions", json={"name": "Тест-мир"})

    assert response.status_code == 201
    info = response.json()
    assert info["name"] == "Тест-мир"
    assert info["id"] != "default"
    assert info["day"] == 0
    assert info["companies"] > 0


def test_sessions_are_isolated(client: TestClient) -> None:
    """Закрытие дня в новой сессии не меняет день дефолтной сессии."""
    session_id = client.post("/api/sessions", json={"name": "Изолят"}).json()["id"]

    client.post(f"/api/sessions/{session_id}/close-day")

    default_day = client.get("/api/state").json()["day"]
    new_day = client.get(f"/api/sessions/{session_id}/state").json()["day"]

    assert default_day == 0
    assert new_day == 1


def test_get_session_info(client: TestClient) -> None:
    session_id = client.post("/api/sessions", json={"name": "Инфо-тест"}).json()["id"]

    response = client.get(f"/api/sessions/{session_id}")

    assert response.status_code == 200
    assert response.json()["id"] == session_id


def test_get_unknown_session_returns_404(client: TestClient) -> None:
    response = client.get("/api/sessions/nonexistent/state")

    assert response.status_code == 404


def test_delete_session_removes_it(client: TestClient) -> None:
    session_id = client.post("/api/sessions", json={"name": "Временная"}).json()["id"]

    delete_response = client.delete(f"/api/sessions/{session_id}")
    assert delete_response.status_code == 200

    get_response = client.get(f"/api/sessions/{session_id}/state")
    assert get_response.status_code == 404


def test_delete_default_session_rejected(client: TestClient) -> None:
    response = client.delete("/api/sessions/default")

    assert response.status_code == 400


def test_reset_session_resets_to_day_zero(client: TestClient) -> None:
    session_id = client.post("/api/sessions", json={"name": "Обнуляемая"}).json()["id"]
    client.post(f"/api/sessions/{session_id}/close-day")
    assert client.get(f"/api/sessions/{session_id}/state").json()["day"] == 1

    client.post(f"/api/sessions/{session_id}/reset")

    assert client.get(f"/api/sessions/{session_id}/state").json()["day"] == 0


def test_multiple_sessions_run_independently(client: TestClient) -> None:
    """Три сессии закрывают разное количество дней — состояния не смешиваются."""
    s1 = client.post("/api/sessions", json={"name": "А"}).json()["id"]
    s2 = client.post("/api/sessions", json={"name": "Б"}).json()["id"]

    for _ in range(3):
        client.post(f"/api/sessions/{s1}/close-day")
    client.post(f"/api/sessions/{s2}/close-day")

    assert client.get(f"/api/sessions/{s1}/state").json()["day"] == 3
    assert client.get(f"/api/sessions/{s2}/state").json()["day"] == 1
    assert client.get("/api/state").json()["day"] == 0
