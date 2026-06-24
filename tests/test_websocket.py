"""WebSocket-тесты: подключение, ping-pong, авто-закрытие дня."""

import pytest
from app.main import app
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


@pytest.fixture()
def client() -> TestClient:
    c = TestClient(app)
    c.post("/api/reset")
    return c


def _new_session(client: TestClient, name: str = "WS-тест") -> str:
    return client.post("/api/sessions", json={"name": name}).json()["id"]


def _register(client: TestClient, username: str = "ws_user") -> dict:
    resp = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123!"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_ws_connect_sends_connected_event(client: TestClient) -> None:
    session_id = _new_session(client)

    with client.websocket_connect(f"/api/ws/sessions/{session_id}") as ws:
        msg = ws.receive_json()

    assert msg["event"] == "connected"
    assert msg["session_id"] == session_id
    assert msg["day"] == 0


def test_ws_ping_pong(client: TestClient) -> None:
    session_id = _new_session(client)

    with client.websocket_connect(f"/api/ws/sessions/{session_id}") as ws:
        ws.receive_json()  # connected
        ws.send_json({"action": "ping"})
        msg = ws.receive_json()

    assert msg["event"] == "pong"


def test_ws_unknown_session_is_rejected(client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/api/ws/sessions/ghost") as ws,
    ):
        ws.receive_json()


def test_manual_close_day_broadcasts_event(client: TestClient) -> None:
    session_id = _new_session(client)

    with client.websocket_connect(f"/api/ws/sessions/{session_id}") as ws:
        ws.receive_json()  # connected
        client.post(f"/api/sessions/{session_id}/close-day")
        msg = ws.receive_json()

    assert msg["event"] == "day_closed"
    assert msg["day"] == 1


def test_auto_close_when_sole_player_submits(client: TestClient) -> None:
    """Единственный человек-игрок сдаёт решение → день закрывается автоматически."""
    session_id = _new_session(client)
    headers = _register(client, "sole_player")
    company = client.post(
        f"/api/sessions/{session_id}/companies",
        json={"name": "Моя сеть", "role": "retailer", "region_id": "central"},
        headers=headers,
    ).json()

    with client.websocket_connect(f"/api/ws/sessions/{session_id}") as ws:
        ws.receive_json()  # connected
        client.post(
            f"/api/sessions/{session_id}/decisions/{company['id']}",
            json={},
            headers=headers,
        )
        submitted_msg = ws.receive_json()
        closed_msg = ws.receive_json()

    assert submitted_msg["event"] == "player_submitted"
    assert submitted_msg["ready"] == 1
    assert submitted_msg["total"] == 1
    assert closed_msg["event"] == "day_closed"
    assert closed_msg["day"] == 1


def test_no_auto_close_until_all_submit(client: TestClient) -> None:
    """Два игрока: день закрывается только после сдачи обоих решений."""
    session_id = _new_session(client)
    h1 = _register(client, "player_one")
    h2 = _register(client, "player_two")
    co1 = client.post(
        f"/api/sessions/{session_id}/companies",
        json={"name": "Завод", "role": "producer", "region_id": "volga"},
        headers=h1,
    ).json()
    co2 = client.post(
        f"/api/sessions/{session_id}/companies",
        json={"name": "Склад", "role": "distributor", "region_id": "north"},
        headers=h2,
    ).json()

    with client.websocket_connect(f"/api/ws/sessions/{session_id}") as ws:
        ws.receive_json()  # connected

        # первый игрок сдаёт — день ещё не закрывается
        client.post(
            f"/api/sessions/{session_id}/decisions/{co1['id']}",
            json={},
            headers=h1,
        )
        msg1 = ws.receive_json()
        assert msg1["event"] == "player_submitted"
        assert msg1["ready"] == 1
        assert msg1["total"] == 2

        # второй игрок сдаёт — теперь день закрывается
        client.post(
            f"/api/sessions/{session_id}/decisions/{co2['id']}",
            json={},
            headers=h2,
        )
        msg2 = ws.receive_json()
        msg3 = ws.receive_json()

    assert msg2["event"] == "player_submitted"
    assert msg2["ready"] == 2
    assert msg3["event"] == "day_closed"
