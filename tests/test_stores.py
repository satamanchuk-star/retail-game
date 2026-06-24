"""Постройка магазинов делает ритейл расширяемой ролью, а не фиксированной точкой."""

import pytest
from app.domain.balance import STORE_FORMATS
from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import AssetType, CompanyCreate, Role, StoreFormat
from app.main import app
from fastapi.testclient import TestClient


def _store_capacity(engine: GameEngine, company_id: str) -> int:
    return sum(
        asset.capacity_units_per_day
        for asset in engine.state.assets
        if asset.company_id == company_id and asset.asset_type == AssetType.STORE
    )


def test_build_store_adds_capacity_and_spends_cash() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    company = engine.create_company(
        CompanyCreate(name="Сеть у дома", role=Role.RETAILER, region_id="central")
    )
    cash_before = company.cash_rub
    capacity_before = _store_capacity(engine, company.id)
    preset = STORE_FORMATS[StoreFormat.KIOSK]

    asset = engine.build_store(company.id, StoreFormat.KIOSK)

    assert asset.asset_type == AssetType.STORE
    assert asset.store_format == StoreFormat.KIOSK
    assert company.cash_rub == cash_before - preset.build_cost_rub
    assert (
        _store_capacity(engine, company.id)
        == capacity_before + preset.capacity_units_per_day
    )


def test_build_store_rejected_for_non_retailer() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    company = engine.create_company(
        CompanyCreate(name="Завод", role=Role.PRODUCER, region_id="volga")
    )

    with pytest.raises(ValueError, match="ритейлер"):
        engine.build_store(company.id, StoreFormat.KIOSK)


def test_build_store_requires_enough_cash() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    company = engine.create_company(
        CompanyCreate(name="Бедный ритейл", role=Role.RETAILER, region_id="central")
    )
    company.cash_rub = 100_000

    with pytest.raises(ValueError, match="Недостаточно средств"):
        engine.build_store(company.id, StoreFormat.SUPERMARKET)


def test_store_formats_endpoint_lists_presets() -> None:
    client = TestClient(app)

    response = client.get("/api/store-formats")

    assert response.status_code == 200
    formats = {item["store_format"] for item in response.json()}
    assert formats == {"kiosk", "convenience", "supermarket"}


def test_build_store_endpoint_creates_store() -> None:
    client = TestClient(app)
    client.post("/api/reset")
    register = client.post(
        "/api/auth/register",
        json={"username": "retail_owner", "password": "supersecret1"},
    )
    token = register.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    company = client.post(
        "/api/companies",
        json={"name": "Моя сеть", "role": "retailer", "region_id": "central"},
        headers=headers,
    ).json()

    response = client.post(
        f"/api/companies/{company['id']}/stores",
        json={"store_format": "kiosk"},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["asset_type"] == "store"
    assert body["store_format"] == "kiosk"
    assert body["company_id"] == company["id"]
