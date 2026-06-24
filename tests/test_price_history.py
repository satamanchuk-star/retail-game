"""Тесты истории цен и рыночных событий."""

from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import (
    BusinessAsset,
    Company,
    CompanyDecision,
    MarketEvent,
    MarketEventType,
    Role,
)


def _engine_with_retailer(
    region_id: str = "central",
    price_index: float = 1.0,
) -> tuple[GameEngine, Company]:
    """Движок с одним контролируемым ритейлером в заданном регионе."""
    state = build_initial_state()
    engine = GameEngine(state)

    state.companies = [c for c in state.companies if c.role != Role.RETAILER]
    ret = Company(
        id="test_ret",
        name="Тест-магазин",
        role=Role.RETAILER,
        region_id=region_id,
        cash_rub=5_000_000,
        is_npc=False,
    )
    state.companies.append(ret)
    state.assets.append(
        BusinessAsset(
            id="asset_test_ret",
            company_id="test_ret",
            asset_type="store",
            name="Тест-точка",
            region_id=region_id,
            capacity_units_per_day=50_000,
            fixed_cost_rub_per_day=0,
            storage_type="обычное",
            store_format="convenience",
        )
    )
    state.inventories["test_ret"] = {"bread": 5_000, "milk": 5_000}
    engine._create_batches_from_inventory("test_ret", state.inventories["test_ret"])
    state.decisions["test_ret"] = CompanyDecision(
        target_price_index=price_index, ready=True
    )
    return engine, ret


# ─── История цен ─────────────────────────────────────────────────────────────


def test_price_point_recorded_after_close_day() -> None:
    """После close_day в price_history появляется хотя бы одна запись."""
    engine, _ = _engine_with_retailer()
    assert not engine.state.price_history

    engine.close_day()

    assert engine.state.price_history, "price_history не должна быть пустой"


def test_price_point_has_correct_region_and_product() -> None:
    """Записанная ценовая точка ссылается на правильный регион и продукт."""
    engine, _ = _engine_with_retailer(region_id="south")
    engine.close_day()

    bread_pts = [
        p for p in engine.state.price_history
        if p.product_id == "bread" and p.region_id == "south"
    ]
    assert bread_pts, "Нет ценовой точки для хлеба в регионе south"
    assert bread_pts[0].avg_price_rub > 0
    assert bread_pts[0].total_units_sold > 0


def test_price_point_avg_price_matches_price_index() -> None:
    """Средняя цена соответствует target_price_index ритейлера."""
    price_index = 1.2
    engine, _ = _engine_with_retailer(price_index=price_index)
    engine.close_day()

    bread = next(p for p in engine.state.products if p.id == "bread")
    expected_price = int(bread.base_price_rub * price_index)

    bread_pts = [p for p in engine.state.price_history if p.product_id == "bread"]
    assert bread_pts, "Нет ценовой точки для хлеба"
    assert bread_pts[0].avg_price_rub == expected_price


def test_price_history_accumulates_over_days() -> None:
    """За несколько дней история цен накапливается (используем молоко, shelf_life=7)."""
    state = build_initial_state()
    engine = GameEngine(state)

    state.companies = [c for c in state.companies if c.role != Role.RETAILER]
    ret = Company(
        id="acc_ret", name="Тест-3дня", role=Role.RETAILER,
        region_id="central", cash_rub=5_000_000, is_npc=False,
    )
    state.companies.append(ret)
    state.assets.append(BusinessAsset(
        id="asset_acc", company_id="acc_ret", asset_type="store",
        name="Тест", region_id="central", capacity_units_per_day=50_000,
        fixed_cost_rub_per_day=0, storage_type="холодильник", store_format="convenience",
    ))
    state.inventories["acc_ret"] = {"milk": 50_000}
    engine._create_batches_from_inventory("acc_ret", {"milk": 50_000})
    state.decisions["acc_ret"] = CompanyDecision(target_price_index=1.0, ready=True)

    engine.close_day()
    engine.close_day()
    engine.close_day()

    milk_pts = [p for p in engine.state.price_history if p.product_id == "milk"]
    days = {p.day for p in milk_pts}
    assert len(days) >= 3, f"Должно быть ≥3 дней в истории, есть: {days}"


# ─── Рыночные события ─────────────────────────────────────────────────────────


def _add_event(
    engine: GameEngine,
    magnitude: float,
    region_id: str = "central",
    product_id: str = "bread",
    expires_in: int = 3,
) -> MarketEvent:
    closing_day = engine.state.day + 1
    event = MarketEvent(
        day=closing_day,
        event_type=MarketEventType.DEMAND_SHOCK,
        region_id=region_id,
        product_id=product_id,
        magnitude=magnitude,
        description="Тест-событие",
        expires_day=closing_day + expires_in,
    )
    engine.state.market_events.append(event)
    return event


def test_demand_event_increases_sales() -> None:
    """Событие magnitude=1.5 увеличивает продажи хлеба по сравнению с базой."""
    engine_base, _ = _engine_with_retailer()
    engine_base.close_day()
    base_sold = sum(
        p.total_units_sold for p in engine_base.state.price_history
        if p.product_id == "bread"
    )

    engine_boost, _ = _engine_with_retailer()
    _add_event(engine_boost, magnitude=1.5)
    engine_boost.close_day()
    boost_sold = sum(
        p.total_units_sold for p in engine_boost.state.price_history
        if p.product_id == "bread"
    )

    assert boost_sold > base_sold, (
        f"Событие +50% должно увеличить продажи: {boost_sold} vs {base_sold}"
    )


def test_demand_event_decreases_sales() -> None:
    """Событие magnitude=0.5 уменьшает продажи хлеба по сравнению с базой."""
    engine_base, _ = _engine_with_retailer()
    engine_base.close_day()
    base_sold = sum(
        p.total_units_sold for p in engine_base.state.price_history
        if p.product_id == "bread"
    )

    engine_drop, _ = _engine_with_retailer()
    _add_event(engine_drop, magnitude=0.5)
    engine_drop.close_day()
    drop_sold = sum(
        p.total_units_sold for p in engine_drop.state.price_history
        if p.product_id == "bread"
    )

    assert drop_sold < base_sold, (
        f"Событие -50% должно уменьшить продажи: {drop_sold} vs {base_sold}"
    )


def test_expired_event_has_no_effect() -> None:
    """Истёкшее событие (expires_day < closing_day) не влияет на продажи."""
    engine_base, _ = _engine_with_retailer()
    engine_base.close_day()
    base_sold = sum(
        p.total_units_sold for p in engine_base.state.price_history
        if p.product_id == "bread"
    )

    engine_exp, _ = _engine_with_retailer()
    # Событие уже истекло: expires_day = 0 < closing_day = 1
    event = MarketEvent(
        day=0,
        event_type=MarketEventType.DEMAND_SHOCK,
        region_id="central",
        product_id="bread",
        magnitude=2.0,
        description="Устаревшее событие",
        expires_day=0,
    )
    engine_exp.state.market_events.append(event)
    engine_exp.close_day()
    exp_sold = sum(
        p.total_units_sold for p in engine_exp.state.price_history
        if p.product_id == "bread"
    )

    assert exp_sold == base_sold, (
        f"Истёкшее событие не должно влиять: {exp_sold} vs {base_sold}"
    )


def test_event_scoped_to_region_does_not_affect_other_region() -> None:
    """Событие для south не влияет на продажи central."""
    engine_c1, _ = _engine_with_retailer(region_id="central")
    engine_c1.close_day()
    base_sold = sum(
        p.total_units_sold for p in engine_c1.state.price_history
        if p.product_id == "bread" and p.region_id == "central"
    )

    engine_c2, _ = _engine_with_retailer(region_id="central")
    _add_event(engine_c2, magnitude=2.0, region_id="south", product_id="bread")
    engine_c2.close_day()
    other_sold = sum(
        p.total_units_sold for p in engine_c2.state.price_history
        if p.product_id == "bread" and p.region_id == "central"
    )

    assert other_sold == base_sold, (
        f"Событие в south не должно влиять на central: {other_sold} vs {base_sold}"
    )


def test_event_scoped_to_product_does_not_affect_other_product() -> None:
    """Событие для хлеба не влияет на продажи молока."""
    engine_base, _ = _engine_with_retailer()
    engine_base.close_day()
    base_milk = sum(
        p.total_units_sold for p in engine_base.state.price_history
        if p.product_id == "milk"
    )

    engine_evt, _ = _engine_with_retailer()
    _add_event(engine_evt, magnitude=0.1, product_id="bread", region_id="central")
    engine_evt.close_day()
    evt_milk = sum(
        p.total_units_sold for p in engine_evt.state.price_history
        if p.product_id == "milk"
    )

    assert evt_milk == base_milk, (
        f"Событие для хлеба не должно влиять на молоко: {evt_milk} vs {base_milk}"
    )
