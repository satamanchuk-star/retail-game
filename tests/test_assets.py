"""Операционные объекты защищают роли от магических мощностей в расчёте дня."""

from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import AssetType, CompanyCreate, CompanyDecision, Role
from app.main import app
from fastapi.testclient import TestClient


def test_initial_state_has_role_assets() -> None:
    state = build_initial_state()
    engine = GameEngine(state)

    asset_types = {asset.asset_type for asset in state.assets}

    assert AssetType.STORE in asset_types
    assert AssetType.FACTORY in asset_types
    assert AssetType.WAREHOUSE in asset_types
    assert engine.state.assets


def test_new_company_gets_starting_asset() -> None:
    state = build_initial_state()
    engine = GameEngine(state)

    company = engine.create_company(
        CompanyCreate(name="Новый завод", role=Role.PRODUCER, region_id="volga")
    )

    assets = [asset for asset in state.assets if asset.company_id == company.id]
    assert len(assets) == 1
    assert assets[0].asset_type == AssetType.FACTORY


def test_factory_capacity_limits_production() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    factory = next(
        asset for asset in state.assets if asset.company_id == "npc_producer"
    )
    factory.capacity_units_per_day = 120
    engine.set_decision("npc_producer", CompanyDecision(production_units=1_000))

    result = engine.close_day("asset-capacity")

    producer_report = next(
        report for report in result.reports if report.company_id == "npc_producer"
    )
    assert producer_report.produced_units == 120


def test_assets_api_exposes_operational_objects() -> None:
    client = TestClient(app)

    response = client.get("/api/assets")

    assert response.status_code == 200
    payload = response.json()
    assert payload
    assert {item["asset_type"] for item in payload} >= {"store", "factory", "warehouse"}
