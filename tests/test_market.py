"""Тесты рыночных лотов: создание, покупка, отзыв, граничные случаи."""

import pytest
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture()
def client() -> TestClient:
    c = TestClient(app)
    c.post("/api/reset")
    return c


def _session(client: TestClient) -> str:
    return client.post("/api/sessions", json={"name": "Рынок-тест"}).json()["id"]


def _register(client: TestClient, username: str) -> dict:
    resp = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123!"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _company(client: TestClient, sid: str, headers: dict, role: str, name: str) -> dict:
    return client.post(
        f"/api/sessions/{sid}/companies",
        json={"name": name, "role": role, "region_id": "central"},
        headers=headers,
    ).json()


def test_producer_creates_listing(client: TestClient) -> None:
    """Производитель выставляет товар — лот появляется на рынке."""
    sid = _session(client)
    h = _register(client, "prod1")
    co = _company(client, sid, h, "producer", "Завод Альфа")

    # Дать производителю товар через закрытие дня
    client.post(f"/api/sessions/{sid}/decisions/{co['id']}",
                json={"production_units": 200}, headers=h)
    client.post(f"/api/sessions/{sid}/close-day")

    r = client.post(
        f"/api/sessions/{sid}/companies/{co['id']}/listings",
        json={"product_id": "bread", "quantity": 50, "price_rub_per_unit": 80},
        headers=h,
    )
    assert r.status_code == 201
    listing = r.json()
    assert listing["seller_id"] == co["id"]
    assert listing["product_id"] == "bread"
    assert listing["quantity_available"] == 50
    assert listing["is_active"] is True


def test_market_shows_active_listings(client: TestClient) -> None:
    """GET /market возвращает только активные лоты."""
    sid = _session(client)
    h = _register(client, "prod2")
    co = _company(client, sid, h, "producer", "Завод Бета")

    client.post(f"/api/sessions/{sid}/decisions/{co['id']}",
                json={"production_units": 200}, headers=h)
    # sole player → auto-close fires; do NOT call close-day manually again
    client.post(
        f"/api/sessions/{sid}/companies/{co['id']}/listings",
        json={"product_id": "bread", "quantity": 30, "price_rub_per_unit": 75},
        headers=h,
    )

    r = client.get(f"/api/sessions/{sid}/market")
    assert r.status_code == 200
    listings = r.json()
    my_listings = [lst for lst in listings if lst["seller_id"] == co["id"]]
    assert len(my_listings) == 1
    assert my_listings[0]["is_active"] is True


def test_buyer_purchases_listing(client: TestClient) -> None:
    """Покупатель берёт товар — деньги и инвентарь переходят."""
    sid = _session(client)
    h_prod = _register(client, "prod3")
    h_ret = _register(client, "ret3")
    producer = _company(client, sid, h_prod, "producer", "Завод Гамма")
    retailer = _company(client, sid, h_ret, "retailer", "Магазин Гамма")

    client.post(f"/api/sessions/{sid}/decisions/{producer['id']}",
                json={"production_units": 300}, headers=h_prod)
    client.post(f"/api/sessions/{sid}/close-day")

    listing = client.post(
        f"/api/sessions/{sid}/companies/{producer['id']}/listings",
        json={"product_id": "bread", "quantity": 100, "price_rub_per_unit": 80},
        headers=h_prod,
    ).json()

    cash_before = client.get(f"/api/sessions/{sid}/state").json()["companies"]
    retailer_cash_before = next(
        c["cash_rub"] for c in cash_before if c["id"] == retailer["id"]
    )
    producer_cash_before = next(
        c["cash_rub"] for c in cash_before if c["id"] == producer["id"]
    )

    r = client.post(
        f"/api/sessions/{sid}/listings/{listing['id']}/purchase",
        json={"buyer_company_id": retailer["id"], "quantity": 40},
        headers=h_ret,
    )
    assert r.status_code == 200
    updated = r.json()
    assert updated["quantity_available"] == 60
    assert updated["is_active"] is True

    state = client.get(f"/api/sessions/{sid}/state").json()
    retailer_cash = next(c["cash_rub"] for c in state["companies"] if c["id"] == retailer["id"])
    producer_cash = next(c["cash_rub"] for c in state["companies"] if c["id"] == producer["id"])
    assert retailer_cash == retailer_cash_before - 40 * 80
    assert producer_cash == producer_cash_before + 40 * 80
    assert state["inventories"][retailer["id"]]["bread"] == 40


def test_listing_deactivates_when_fully_sold(client: TestClient) -> None:
    """Лот деактивируется, когда весь товар продан."""
    sid = _session(client)
    h_prod = _register(client, "prod4")
    h_ret = _register(client, "ret4")
    producer = _company(client, sid, h_prod, "producer", "Завод Дельта")
    retailer = _company(client, sid, h_ret, "retailer", "Магазин Дельта")

    client.post(f"/api/sessions/{sid}/decisions/{producer['id']}",
                json={"production_units": 300}, headers=h_prod)
    client.post(f"/api/sessions/{sid}/close-day")

    listing = client.post(
        f"/api/sessions/{sid}/companies/{producer['id']}/listings",
        json={"product_id": "bread", "quantity": 20, "price_rub_per_unit": 90},
        headers=h_prod,
    ).json()

    r = client.post(
        f"/api/sessions/{sid}/listings/{listing['id']}/purchase",
        json={"buyer_company_id": retailer["id"], "quantity": 20},
        headers=h_ret,
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is False
    assert r.json()["quantity_available"] == 0

    market = client.get(f"/api/sessions/{sid}/market").json()
    assert all(lst["id"] != listing["id"] for lst in market)


def test_cannot_list_more_than_available(client: TestClient) -> None:
    """Нельзя разместить больше товара, чем есть на складе."""
    sid = _session(client)
    h = _register(client, "prod5")
    co = _company(client, sid, h, "producer", "Завод Эпсилон")

    # Производитель стартует с 2000 хлеба — запрашиваем 5000 (больше запаса)
    r = client.post(
        f"/api/sessions/{sid}/companies/{co['id']}/listings",
        json={"product_id": "bread", "quantity": 5_000, "price_rub_per_unit": 80},
        headers=h,
    )
    assert r.status_code == 400


def test_cannot_buy_more_than_listed(client: TestClient) -> None:
    """Нельзя купить больше, чем указано в лоте."""
    sid = _session(client)
    h_prod = _register(client, "prod6")
    h_ret = _register(client, "ret6")
    producer = _company(client, sid, h_prod, "producer", "Завод Зета")
    retailer = _company(client, sid, h_ret, "retailer", "Магазин Зета")

    client.post(f"/api/sessions/{sid}/decisions/{producer['id']}",
                json={"production_units": 300}, headers=h_prod)
    client.post(f"/api/sessions/{sid}/close-day")

    listing = client.post(
        f"/api/sessions/{sid}/companies/{producer['id']}/listings",
        json={"product_id": "bread", "quantity": 10, "price_rub_per_unit": 80},
        headers=h_prod,
    ).json()

    r = client.post(
        f"/api/sessions/{sid}/listings/{listing['id']}/purchase",
        json={"buyer_company_id": retailer["id"], "quantity": 999},
        headers=h_ret,
    )
    assert r.status_code == 400


def test_cannot_buy_own_listing(client: TestClient) -> None:
    """Продавец не может купить собственный лот."""
    sid = _session(client)
    h = _register(client, "prod7")
    co = _company(client, sid, h, "producer", "Завод Эта")

    client.post(f"/api/sessions/{sid}/decisions/{co['id']}",
                json={"production_units": 300}, headers=h)
    client.post(f"/api/sessions/{sid}/close-day")

    listing = client.post(
        f"/api/sessions/{sid}/companies/{co['id']}/listings",
        json={"product_id": "bread", "quantity": 10, "price_rub_per_unit": 80},
        headers=h,
    ).json()

    r = client.post(
        f"/api/sessions/{sid}/listings/{listing['id']}/purchase",
        json={"buyer_company_id": co["id"], "quantity": 5},
        headers=h,
    )
    assert r.status_code == 400


def test_cancel_listing(client: TestClient) -> None:
    """Продавец отзывает лот — лот становится неактивным."""
    sid = _session(client)
    h = _register(client, "prod8")
    co = _company(client, sid, h, "producer", "Завод Тета")

    client.post(f"/api/sessions/{sid}/decisions/{co['id']}",
                json={"production_units": 300}, headers=h)
    client.post(f"/api/sessions/{sid}/close-day")

    listing = client.post(
        f"/api/sessions/{sid}/companies/{co['id']}/listings",
        json={"product_id": "bread", "quantity": 50, "price_rub_per_unit": 80},
        headers=h,
    ).json()

    r = client.delete(
        f"/api/sessions/{sid}/listings/{listing['id']}",
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is False

    market = client.get(f"/api/sessions/{sid}/market").json()
    assert not any(lst["id"] == listing["id"] for lst in market)
