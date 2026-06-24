"""Сырьевые тесты защищают производителя от выпуска товара без ресурсов."""

from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import CompanyDecision


def test_initial_state_exposes_raw_materials_and_recipes() -> None:
    state = build_initial_state()

    assert state.raw_materials
    assert state.production_recipes
    assert state.raw_inventories["npc_producer"]["grain"] > 0


def test_production_consumes_raw_materials() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    grain_before = state.raw_inventories["npc_producer"]["grain"]
    engine.set_decision("npc_producer", CompanyDecision(production_units=100))

    result = engine.close_day("raw-consume")

    producer_report = next(
        report for report in result.reports if report.company_id == "npc_producer"
    )
    assert producer_report.produced_units == 100
    assert state.raw_inventories["npc_producer"]["grain"] < grain_before
    assert any(operation.step == "production" for operation in result.operations)


def test_raw_shortage_limits_production_and_writes_operation() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    state.raw_inventories["npc_producer"] = {
        "grain": 1.0,
        "raw_milk": 0.0,
        "packaging": 1.0,
    }
    engine.set_decision("npc_producer", CompanyDecision(production_units=100))

    result = engine.close_day("raw-shortage")

    producer_report = next(
        report for report in result.reports if report.company_id == "npc_producer"
    )
    assert producer_report.produced_units < 100
    assert any(
        operation.step == "raw_material_shortage"
        and operation.company_id == "npc_producer"
        for operation in result.operations
    )
