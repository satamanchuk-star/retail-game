"""Тесты логистики (Фаза 4.1): logistics_risk региона влияет на экономику доставки."""

from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import (
    CompanyDayReport,
    DeliveryOrder,
    DeliveryStatus,
    Role,
)


def test_route_risk_averages_shipper_and_receiver_regions() -> None:
    engine = GameEngine(build_initial_state())
    companies = engine.state.companies
    a, b = companies[0], companies[1]
    a.region_id = "volga"   # logistics_risk 0.10
    b.region_id = "north"   # logistics_risk 0.35
    risk = engine._route_risk(a.id, b.id)
    assert abs(risk - (0.10 + 0.35) / 2) < 1e-6


def _distributor_profit_for_route(shipper_region: str, receiver_region: str) -> int:
    engine = GameEngine(build_initial_state())
    shipper = next(c for c in engine.state.companies if c.role == Role.PRODUCER)
    distributor = next(c for c in engine.state.companies if c.role == Role.DISTRIBUTOR)
    receiver = next(c for c in engine.state.companies if c.role == Role.RETAILER)
    shipper.region_id = shipper_region
    receiver.region_id = receiver_region

    engine.state.inventories[shipper.id] = {"bread": 1_000}
    engine._create_batches_from_inventory(shipper.id, {"bread": 1_000})

    engine.state.delivery_orders.append(
        DeliveryOrder(
            id="route-test",
            status=DeliveryStatus.ACCEPTED,
            shipper_id=shipper.id,
            distributor_id=distributor.id,
            receiver_id=receiver.id,
            product_id="bread",
            quantity=500,
            fee_rub_per_unit=40,
            due_day=engine.state.day + 1,
        )
    )
    reports = {c.id: CompanyDayReport(company_id=c.id) for c in engine.state.companies}
    engine._apply_due_delivery_orders(reports, [])
    return reports[distributor.id].profit_rub


def test_risky_route_costs_distributor_more_than_safe_route() -> None:
    safe = _distributor_profit_for_route("volga", "volga")     # риск ~0.10
    risky = _distributor_profit_for_route("north", "east_port")  # риск ~0.32
    assert safe > risky, "logistics_risk не влияет: рискованный маршрут должен быть дороже"
