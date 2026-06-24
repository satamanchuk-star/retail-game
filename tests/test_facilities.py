"""Постройка заводов и складов делает производство и логистику расширяемыми ролями."""

import pytest
from app.domain.balance import FACTORY_FORMATS, WAREHOUSE_FORMATS
from app.domain.engine import STORE_CLOSE_REFUND, GameEngine, build_initial_state
from app.domain.models import AssetType, CompanyCreate, Role
from app.main import app
from fastapi.testclient import TestClient


def _capacity(engine: GameEngine, company_id: str, asset_type: AssetType) -> int:
    return sum(
        asset.capacity_units_per_day
        for asset in engine.state.assets
        if asset.company_id == company_id and asset.asset_type == asset_type
    )


def _count(engine: GameEngine, company_id: str, asset_type: AssetType) -> int:
    return len(
        [
            asset
            for asset in engine.state.assets
            if asset.company_id == company_id and asset.asset_type == asset_type
        ]
    )


def test_producer_builds_factory() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    company = engine.create_company(
        CompanyCreate(name="Новый завод", role=Role.PRODUCER, region_id="volga")
    )
    cash_before = company.cash_rub
    cap_before = _capacity(engine, company.id, AssetType.FACTORY)
    preset = FACTORY_FORMATS["workshop"]

    asset = engine.build_facility(company.id, "workshop")

    assert asset.asset_type == AssetType.FACTORY
    assert asset.facility_format == "workshop"
    assert company.cash_rub == cash_before - preset.build_cost_rub
    assert (
        _capacity(engine, company.id, AssetType.FACTORY)
        == cap_before + preset.capacity_units_per_day
    )


def test_distributor_builds_warehouse() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    company = engine.create_company(
        CompanyCreate(name="Новый склад", role=Role.DISTRIBUTOR, region_id="north")
    )
    preset = WAREHOUSE_FORMATS["depot"]
    cap_before = _capacity(engine, company.id, AssetType.WAREHOUSE)

    asset = engine.build_facility(company.id, "depot")

    assert asset.asset_type == AssetType.WAREHOUSE
    assert (
        _capacity(engine, company.id, AssetType.WAREHOUSE)
        == cap_before + preset.capacity_units_per_day
    )


def test_retailer_cannot_build_facility() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    company = engine.create_company(
        CompanyCreate(name="Ритейл", role=Role.RETAILER, region_id="central")
    )

    with pytest.raises(ValueError, match="магазины"):
        engine.build_facility(company.id, "workshop")


def test_upgrade_factory_raises_capacity_and_charges_difference() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    company = engine.create_company(
        CompanyCreate(name="Завод", role=Role.PRODUCER, region_id="volga")
    )
    company.cash_rub = 60_000_000
    factory = engine.build_facility(company.id, "workshop")
    cash_before = company.cash_rub
    target = FACTORY_FORMATS["complex"]

    engine.upgrade_facility(company.id, factory.id, "complex")

    assert factory.facility_format == "complex"
    assert factory.capacity_units_per_day == target.capacity_units_per_day
    assert company.cash_rub == cash_before - (
        target.build_cost_rub - FACTORY_FORMATS["workshop"].build_cost_rub
    )


def test_close_facility_refunds_and_removes() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    company = engine.create_company(
        CompanyCreate(name="Завод", role=Role.PRODUCER, region_id="volga")
    )
    factory = engine.build_facility(company.id, "workshop")
    cash_before = company.cash_rub
    expected_refund = int(FACTORY_FORMATS["workshop"].build_cost_rub * STORE_CLOSE_REFUND)

    engine.close_facility(company.id, factory.id)

    assert all(asset.id != factory.id for asset in engine.state.assets)
    assert company.cash_rub == cash_before + expected_refund


def test_close_last_factory_rejected() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    company = engine.create_company(
        CompanyCreate(name="Завод", role=Role.PRODUCER, region_id="volga")
    )
    starter = next(
        asset
        for asset in engine.state.assets
        if asset.company_id == company.id and asset.asset_type == AssetType.FACTORY
    )

    with pytest.raises(ValueError, match="последний объект"):
        engine.close_facility(company.id, starter.id)


def test_complex_produces_more_than_workshop_from_same_raw_materials() -> None:
    """Комбинат (×1.15) выдаёт больше продукции, чем цех (×0.85) при равном сырье."""
    from app.domain.models import CompanyDecision

    def _make_producer(engine: GameEngine, name: str) -> object:
        company = engine.create_company(
            CompanyCreate(name=name, role=Role.PRODUCER, region_id="volga")
        )
        company.cash_rub = 100_000_000
        return company

    state_w = build_initial_state()
    eng_w = GameEngine(state_w)
    co_w = _make_producer(eng_w, "Цех")
    # replace starter plant with workshop
    starter_w = next(a for a in eng_w.state.assets if a.company_id == co_w.id)
    starter_w.facility_format = "workshop"
    starter_w.capacity_units_per_day = FACTORY_FORMATS["workshop"].capacity_units_per_day
    eng_w.state.decisions[co_w.id] = CompanyDecision(production_units=1_000)
    result_w = eng_w.close_day()
    produced_w = next(r.produced_units for r in result_w.reports if r.company_id == co_w.id)

    state_c = build_initial_state()
    eng_c = GameEngine(state_c)
    co_c = _make_producer(eng_c, "Комбинат")
    starter_c = next(a for a in eng_c.state.assets if a.company_id == co_c.id)
    starter_c.facility_format = "complex"
    starter_c.capacity_units_per_day = FACTORY_FORMATS["complex"].capacity_units_per_day
    eng_c.state.decisions[co_c.id] = CompanyDecision(production_units=1_000)
    result_c = eng_c.close_day()
    produced_c = next(r.produced_units for r in result_c.reports if r.company_id == co_c.id)

    assert produced_c > produced_w, (
        f"Комбинат должен производить больше цеха: {produced_c} <= {produced_w}"
    )


def test_distributor_earns_only_from_delivery_orders() -> None:
    """Дистрибьютор без заявок не получает дохода; с принятой заявкой — получает."""
    from app.domain.models import DeliveryOrderCreate

    FEE = 20
    QTY = 500

    # Движок A: дистрибьютор, которому не создали заявок
    eng_a = GameEngine(build_initial_state())
    npc_dist_a = next(c for c in eng_a.state.companies if c.is_npc and c.role == "distributor")
    result_a = eng_a.close_day()
    rev_no_order = next(r.revenue_rub for r in result_a.reports if r.company_id == npc_dist_a.id)

    # Движок B: дистрибьютор с принятой заявкой
    eng_b = GameEngine(build_initial_state())
    npc_prod_b = next(c for c in eng_b.state.companies if c.is_npc and c.role == "producer")
    npc_dist_b = next(c for c in eng_b.state.companies if c.is_npc and c.role == "distributor")
    player_b = next(c for c in eng_b.state.companies if not c.is_npc)
    eng_b.create_delivery_order(
        npc_prod_b.id,
        DeliveryOrderCreate(
            distributor_id=npc_dist_b.id,
            receiver_id=player_b.id,
            product_id="bread",
            quantity=QTY,
            fee_rub_per_unit=FEE,
            due_day=1,
        ),
    )
    # NPC-дистрибьютор принимает заявку в _apply_npc_decisions
    result_b = eng_b.close_day()
    rev_with_order = next(r.revenue_rub for r in result_b.reports if r.company_id == npc_dist_b.id)

    assert rev_no_order == 0, "Без заявок дистрибьютор не получает дохода"
    assert rev_with_order >= QTY * FEE, (
        f"С заявкой дистрибьютор должен получить ≥{QTY * FEE} руб., получил {rev_with_order}"
    )


def test_facility_formats_endpoint_lists_tiers() -> None:
    client = TestClient(app)

    response = client.get("/api/facility-formats")

    assert response.status_code == 200
    tiers = {item["tier"] for item in response.json()}
    assert {"workshop", "plant", "complex", "depot", "center", "hub"} <= tiers


def test_build_facility_endpoint_creates_warehouse() -> None:
    client = TestClient(app)
    client.post("/api/reset")
    register = client.post(
        "/api/auth/register",
        json={"username": "logistics_owner", "password": "supersecret1"},
    )
    headers = {"Authorization": f"Bearer {register.json()['access_token']}"}
    company = client.post(
        "/api/companies",
        json={"name": "Логистика", "role": "distributor", "region_id": "north"},
        headers=headers,
    ).json()

    response = client.post(
        f"/api/companies/{company['id']}/facilities",
        json={"tier": "depot"},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["asset_type"] == "warehouse"
    assert body["facility_format"] == "depot"
