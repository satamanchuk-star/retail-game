"""Постройка магазинов делает ритейл расширяемой ролью, а не фиксированной точкой."""

import pytest
from app.domain.balance import STORE_FORMATS
from app.domain.engine import STORE_CLOSE_REFUND, GameEngine, build_initial_state
from app.domain.models import AssetType, CompanyCreate, Role, StoreFormat
from app.main import app
from fastapi.testclient import TestClient


def _store_capacity(engine: GameEngine, company_id: str) -> int:
    return sum(
        asset.capacity_units_per_day
        for asset in engine.state.assets
        if asset.company_id == company_id and asset.asset_type == AssetType.STORE
    )


def _company_stores(engine: GameEngine, company_id: str) -> list:
    return [
        asset
        for asset in engine.state.assets
        if asset.company_id == company_id and asset.asset_type == AssetType.STORE
    ]


def _make_retailer(engine: GameEngine, cash: int | None = None):
    company = engine.create_company(
        CompanyCreate(name="Сеть", role=Role.RETAILER, region_id="central")
    )
    if cash is not None:
        company.cash_rub = cash
    return company


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


def test_upgrade_store_raises_capacity_and_charges_difference() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    company = _make_retailer(engine, cash=20_000_000)
    store = _company_stores(engine, company.id)[0]
    cash_before = company.cash_rub
    current_cost = STORE_FORMATS[store.store_format].build_cost_rub
    target = STORE_FORMATS[StoreFormat.SUPERMARKET]

    engine.upgrade_store(company.id, store.id, StoreFormat.SUPERMARKET)

    assert store.store_format == StoreFormat.SUPERMARKET
    assert store.capacity_units_per_day == target.capacity_units_per_day
    assert company.cash_rub == cash_before - (target.build_cost_rub - current_cost)


def test_upgrade_store_rejects_same_or_lower_format() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    company = _make_retailer(engine, cash=20_000_000)
    store = _company_stores(engine, company.id)[0]

    with pytest.raises(ValueError, match="более крупный формат"):
        engine.upgrade_store(company.id, store.id, StoreFormat.KIOSK)


def test_close_store_refunds_and_removes() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    company = _make_retailer(engine)
    kiosk = engine.build_store(company.id, StoreFormat.KIOSK)
    cash_before = company.cash_rub
    expected_refund = int(
        STORE_FORMATS[StoreFormat.KIOSK].build_cost_rub * STORE_CLOSE_REFUND
    )

    engine.close_store(company.id, kiosk.id)

    assert all(asset.id != kiosk.id for asset in engine.state.assets)
    assert company.cash_rub == cash_before + expected_refund


def test_close_last_store_rejected() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    company = _make_retailer(engine)
    store = _company_stores(engine, company.id)[0]

    with pytest.raises(ValueError, match="последний магазин"):
        engine.close_store(company.id, store.id)


def test_supermarket_sells_more_than_kiosk() -> None:
    """Супермаркет (×1.5 спрос) продаёт больше, чем киоск (×0.7) при равных остатках."""
    from app.domain.models import CompanyDecision

    def _make_retailer(engine: GameEngine, name: str, region: str) -> object:
        return engine.create_company(
            CompanyCreate(name=name, role=Role.RETAILER, region_id=region)
        )

    state_kiosk = build_initial_state()
    eng_kiosk = GameEngine(state_kiosk)
    kiosk_co = _make_retailer(eng_kiosk, "Киоск-сеть", "central")
    # replace starter convenience store with kiosk
    starter = next(
        a for a in eng_kiosk.state.assets if a.company_id == kiosk_co.id
    )
    starter.store_format = StoreFormat.KIOSK
    starter.capacity_units_per_day = STORE_FORMATS[StoreFormat.KIOSK].capacity_units_per_day
    eng_kiosk.state.inventories[kiosk_co.id] = {"bread": 10_000}
    eng_kiosk.state.decisions[kiosk_co.id] = CompanyDecision()
    result_kiosk = eng_kiosk.close_day()
    sold_kiosk = next(
        r.sold_units for r in result_kiosk.reports if r.company_id == kiosk_co.id
    )

    state_super = build_initial_state()
    eng_super = GameEngine(state_super)
    super_co = _make_retailer(eng_super, "Супер-сеть", "central")
    starter2 = next(
        a for a in eng_super.state.assets if a.company_id == super_co.id
    )
    starter2.store_format = StoreFormat.SUPERMARKET
    starter2.capacity_units_per_day = STORE_FORMATS[StoreFormat.SUPERMARKET].capacity_units_per_day
    eng_super.state.inventories[super_co.id] = {"bread": 10_000}
    eng_super.state.decisions[super_co.id] = CompanyDecision()
    result_super = eng_super.close_day()
    sold_super = next(
        r.sold_units for r in result_super.reports if r.company_id == super_co.id
    )

    assert sold_super > sold_kiosk, (
        f"Супермаркет должен продавать больше киоска: {sold_super} <= {sold_kiosk}"
    )


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
