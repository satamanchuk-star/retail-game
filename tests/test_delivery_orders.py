"""Тесты заявок на доставку: создание, принятие, исполнение, отмена."""

import pytest
from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import DeliveryOrderCreate, DeliveryStatus
from app.main import app
from fastapi.testclient import TestClient

# ─── Вспомогательные функции ─────────────────────────────────────────────────


@pytest.fixture()
def engine() -> GameEngine:
    return GameEngine(build_initial_state())


def _npc(engine: GameEngine, role: str):
    return next(c for c in engine.state.companies if c.is_npc and c.role == role)


@pytest.fixture()
def client() -> TestClient:
    c = TestClient(app)
    c.post("/api/reset")
    return c


def _session(client: TestClient) -> str:
    return client.post("/api/sessions", json={"name": "Логист-тест"}).json()["id"]


def _register(client: TestClient, username: str) -> dict:
    resp = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123!"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _company(client: TestClient, sid: str, headers: dict, role: str) -> dict:
    return client.post(
        f"/api/sessions/{sid}/companies",
        json={"name": f"Компания-{role}", "role": role, "region_id": "central"},
        headers=headers,
    ).json()


# ─── Unit-тесты через движок ─────────────────────────────────────────────────


def test_create_delivery_order_requires_distributor(engine: GameEngine) -> None:
    """Нельзя назначить дистрибьютором компанию с ролью producer."""
    npc_prod = _npc(engine, "producer")
    npc_dist = _npc(engine, "distributor")
    with pytest.raises(ValueError, match="дистрибьютор"):
        engine.create_delivery_order(
            npc_prod.id,
            DeliveryOrderCreate(
                distributor_id=npc_prod.id,  # producer != distributor
                receiver_id=npc_dist.id,
                product_id="bread",
                quantity=100,
                fee_rub_per_unit=5,
                due_day=3,
            ),
        )


def test_create_delivery_order_pending(engine: GameEngine) -> None:
    """Созданная заявка имеет статус PENDING."""
    npc_prod = _npc(engine, "producer")
    npc_dist = _npc(engine, "distributor")
    player = next(c for c in engine.state.companies if not c.is_npc)

    order = engine.create_delivery_order(
        npc_prod.id,
        DeliveryOrderCreate(
            distributor_id=npc_dist.id,
            receiver_id=player.id,
            product_id="bread",
            quantity=50,
            fee_rub_per_unit=8,
            due_day=2,
        ),
    )
    assert order.status == DeliveryStatus.PENDING
    assert order in engine.state.delivery_orders


def test_accept_delivery_order(engine: GameEngine) -> None:
    """Дистрибьютор принимает заявку → статус ACCEPTED."""
    npc_prod = _npc(engine, "producer")
    npc_dist = _npc(engine, "distributor")
    player = next(c for c in engine.state.companies if not c.is_npc)

    order = engine.create_delivery_order(
        npc_prod.id,
        DeliveryOrderCreate(
            distributor_id=npc_dist.id,
            receiver_id=player.id,
            product_id="bread",
            quantity=50,
            fee_rub_per_unit=8,
            due_day=2,
        ),
    )
    engine.accept_delivery_order(order.id, npc_dist.id)
    assert order.status == DeliveryStatus.ACCEPTED


def test_wrong_distributor_cannot_accept(engine: GameEngine) -> None:
    """Чужой дистрибьютор не может принять заявку."""
    npc_prod = _npc(engine, "producer")
    npc_dist = _npc(engine, "distributor")
    player = next(c for c in engine.state.companies if not c.is_npc)

    order = engine.create_delivery_order(
        npc_prod.id,
        DeliveryOrderCreate(
            distributor_id=npc_dist.id,
            receiver_id=player.id,
            product_id="bread",
            quantity=50,
            fee_rub_per_unit=8,
            due_day=2,
        ),
    )
    with pytest.raises(ValueError):
        engine.accept_delivery_order(order.id, npc_prod.id)  # не дистрибьютор


def test_cancel_delivery_order(engine: GameEngine) -> None:
    """Грузоотправитель отменяет заявку → статус CANCELLED."""
    npc_prod = _npc(engine, "producer")
    npc_dist = _npc(engine, "distributor")
    player = next(c for c in engine.state.companies if not c.is_npc)

    order = engine.create_delivery_order(
        npc_prod.id,
        DeliveryOrderCreate(
            distributor_id=npc_dist.id,
            receiver_id=player.id,
            product_id="bread",
            quantity=50,
            fee_rub_per_unit=8,
            due_day=2,
        ),
    )
    engine.cancel_delivery_order(order.id, npc_prod.id)
    assert order.status == DeliveryStatus.CANCELLED


def test_close_day_fulfills_accepted_order(engine: GameEngine) -> None:
    """Принятая заявка исполняется в close_day: дистрибьютор фиксирует доставку."""
    npc_prod = _npc(engine, "producer")
    npc_dist = _npc(engine, "distributor")
    player = next(c for c in engine.state.companies if not c.is_npc)

    order = engine.create_delivery_order(
        npc_prod.id,
        DeliveryOrderCreate(
            distributor_id=npc_dist.id,
            receiver_id=player.id,
            product_id="bread",
            quantity=200,
            fee_rub_per_unit=10,
            due_day=1,
        ),
    )
    engine.accept_delivery_order(order.id, npc_dist.id)
    engine.close_day()

    assert order.status == DeliveryStatus.FULFILLED
    # Проверяем через отчёт дистрибьютора (player — ритейлер, продаёт хлеб в тот же день)
    dist_report = next(r for r in engine.state.last_reports if r.company_id == npc_dist.id)
    assert dist_report.delivered_units >= 200


def test_close_day_distributor_earns_fee(engine: GameEngine) -> None:
    """Дистрибьютор получает вознаграждение за исполненную заявку."""
    npc_prod = _npc(engine, "producer")
    npc_dist = _npc(engine, "distributor")
    player = next(c for c in engine.state.companies if not c.is_npc)

    order = engine.create_delivery_order(
        npc_prod.id,
        DeliveryOrderCreate(
            distributor_id=npc_dist.id,
            receiver_id=player.id,
            product_id="bread",
            quantity=300,
            fee_rub_per_unit=15,
            due_day=1,
        ),
    )
    engine.accept_delivery_order(order.id, npc_dist.id)
    engine.close_day()

    report = next(r for r in engine.state.last_reports if r.company_id == npc_dist.id)
    assert report.delivered_units >= 300
    assert report.revenue_rub >= 300 * 15


def test_npc_distributor_auto_accepts_pending_orders(engine: GameEngine) -> None:
    """NPC-дистрибьютор автоматически принимает PENDING-заявки при close_day."""
    npc_prod = _npc(engine, "producer")
    npc_dist = _npc(engine, "distributor")
    player = next(c for c in engine.state.companies if not c.is_npc)

    order = engine.create_delivery_order(
        npc_prod.id,
        DeliveryOrderCreate(
            distributor_id=npc_dist.id,
            receiver_id=player.id,
            product_id="bread",
            quantity=100,
            fee_rub_per_unit=5,
            due_day=2,
        ),
    )
    assert order.status == DeliveryStatus.PENDING

    engine.close_day()  # _apply_npc_decisions → auto-accept

    assert order.status in (DeliveryStatus.ACCEPTED, DeliveryStatus.FULFILLED)


def test_cancelled_order_not_fulfilled(engine: GameEngine) -> None:
    """Отменённая заявка не исполняется при close_day."""
    npc_prod = _npc(engine, "producer")
    npc_dist = _npc(engine, "distributor")
    player = next(c for c in engine.state.companies if not c.is_npc)

    order = engine.create_delivery_order(
        npc_prod.id,
        DeliveryOrderCreate(
            distributor_id=npc_dist.id,
            receiver_id=player.id,
            product_id="bread",
            quantity=500,
            fee_rub_per_unit=10,
            due_day=1,
        ),
    )
    engine.cancel_delivery_order(order.id, npc_prod.id)
    engine.close_day()

    assert order.status == DeliveryStatus.CANCELLED
    # Дистрибьютор ничего не доставил (отменённая заявка не исполняется)
    dist_report = next(r for r in engine.state.last_reports if r.company_id == npc_dist.id)
    assert dist_report.delivered_units == 0


# ─── Интеграционный тест через API ───────────────────────────────────────────


def test_api_delivery_order_lifecycle(client: TestClient) -> None:
    """Создание → принятие → исполнение через HTTP."""
    sid = _session(client)
    h_prod = _register(client, "shipper1")
    h_dist = _register(client, "dist1")
    producer = _company(client, sid, h_prod, "producer")
    distributor = _company(client, sid, h_dist, "distributor")
    # Дать производителю хлеб
    state = client.get(f"/api/sessions/{sid}/state").json()
    inv = state["inventories"].get(producer["id"], {})
    bread_qty = inv.get("bread", 0)
    assert bread_qty > 0, "Производитель должен иметь стартовый инвентарь хлеба"

    # Создать заявку на доставку
    r = client.post(
        f"/api/sessions/{sid}/companies/{producer['id']}/delivery-orders",
        json={
            "distributor_id": distributor["id"],
            "receiver_id": "player",
            "product_id": "bread",
            "quantity": 50,
            "fee_rub_per_unit": 10,
            "due_day": 2,
        },
        headers=h_prod,
    )
    assert r.status_code == 201
    order = r.json()
    assert order["status"] == "pending"

    # Дистрибьютор принимает
    r2 = client.post(
        f"/api/sessions/{sid}/delivery-orders/{order['id']}/accept"
        f"?distributor_company_id={distributor['id']}",
        headers=h_dist,
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "accepted"

    # Список заявок виден всем
    orders = client.get(f"/api/sessions/{sid}/delivery-orders").json()
    assert any(o["id"] == order["id"] for o in orders)
