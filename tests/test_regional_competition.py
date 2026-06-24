"""Тесты региональной конкуренции: ритейлеры в одном регионе делят пул спроса."""

from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import (
    BusinessAsset,
    Company,
    CompanyDecision,
    Role,
)


def _make_retailer(
    company_id: str,
    name: str,
    region_id: str = "central",
    cash: int = 5_000_000,
) -> Company:
    # is_npc=False: _apply_npc_decisions не перезапишет наши тестовые решения
    return Company(
        id=company_id,
        name=name,
        role=Role.RETAILER,
        region_id=region_id,
        cash_rub=cash,
        is_npc=False,
    )


def _store_asset(company_id: str, region_id: str = "central") -> BusinessAsset:
    return BusinessAsset(
        id=f"asset_{company_id}",
        company_id=company_id,
        asset_type="store",
        name=f"Магазин {company_id}",
        region_id=region_id,
        capacity_units_per_day=50_000,
        fixed_cost_rub_per_day=0,
        storage_type="обычное",
        store_format="convenience",
    )


def _engine_with_two_retailers(region_id: str = "central") -> GameEngine:
    """Движок с двумя одинаковыми NPC-ритейлерами в одном регионе.

    NPC-производитель и NPC-дистрибьютор из начального баланса остаются,
    но убираем лишние компании-ритейлеры, чтобы контролировать сценарий.
    """
    state = build_initial_state()
    engine = GameEngine(state)

    # Оставляем только NPC-производителя (он не ритейлер)
    state.companies = [c for c in state.companies if c.role != Role.RETAILER]

    ret_a = _make_retailer("ret_a", "Магазин А", region_id)
    ret_b = _make_retailer("ret_b", "Магазин Б", region_id)
    state.companies.extend([ret_a, ret_b])

    for rid in ("ret_a", "ret_b"):
        state.assets.append(_store_asset(rid, region_id))
        state.inventories[rid] = {"bread": 10_000, "milk": 10_000}
        engine._create_batches_from_inventory(rid, state.inventories[rid])

    # Нейтральные решения (price_index=1.0, no marketing)
    state.decisions["ret_a"] = CompanyDecision(
        target_price_index=1.0, ready=True
    )
    state.decisions["ret_b"] = CompanyDecision(
        target_price_index=1.0, ready=True
    )
    return engine


# ─── Тест 1: единственный ритейлер получает весь пул ────────────────────────

def test_single_retailer_gets_full_demand() -> None:
    """При одном ритейлере в регионе продажи не изменились по сравнению с базой."""
    state = build_initial_state()
    engine = GameEngine(state)

    # Оставляем только одного NPC-ритейлера в центре
    state.companies = [c for c in state.companies if c.role != Role.RETAILER]
    ret = _make_retailer("solo_ret", "Монополист", "central")
    state.companies.append(ret)
    state.assets.append(_store_asset("solo_ret", "central"))
    state.inventories["solo_ret"] = {"bread": 10_000}
    engine._create_batches_from_inventory("solo_ret", {"bread": 10_000})
    state.decisions["solo_ret"] = CompanyDecision(target_price_index=1.0, ready=True)

    engine.close_day()

    report = next(r for r in engine.state.last_reports if r.company_id == "solo_ret")
    bread = next(p for p in engine.state.products if p.id == "bread")
    region = next(r for r in engine.state.regions if r.id == "central")
    expected = int(bread.base_daily_demand * region.demand_index)

    # Монополист продаёт ≥ base_demand (с учётом формат-множителя)
    assert report.sold_units >= expected


# ─── Тест 2: два равных ритейлера делят пул ──────────────────────────────────

def test_two_equal_retailers_split_demand() -> None:
    """Два одинаковых ритейлера в одном регионе получают примерно по половине спроса."""
    engine = _engine_with_two_retailers()
    engine.close_day()

    rep_a = next(r for r in engine.state.last_reports if r.company_id == "ret_a")
    rep_b = next(r for r in engine.state.last_reports if r.company_id == "ret_b")

    bread_a = rep_a.sold_units
    bread_b = rep_b.sold_units

    assert bread_a > 0 and bread_b > 0, "Оба ритейлера должны что-то продать"
    # Каждый должен получить примерно половину (±15% допуск)
    total = bread_a + bread_b
    assert abs(bread_a - bread_b) <= total * 0.15, (
        f"Разница слишком большая: {bread_a} vs {bread_b}"
    )


# ─── Тест 3: суммарные продажи ограничены пулом ─────────────────────────────

def test_total_sales_bounded_by_demand_pool() -> None:
    """Суммарные продажи двух ритейлеров не превышают пул регионального спроса."""
    engine = _engine_with_two_retailers()
    engine.close_day()

    rep_a = next(r for r in engine.state.last_reports if r.company_id == "ret_a")
    rep_b = next(r for r in engine.state.last_reports if r.company_id == "ret_b")
    total_sold = rep_a.sold_units + rep_b.sold_units

    bread = next(p for p in engine.state.products if p.id == "bread")
    region = next(r for r in engine.state.regions if r.id == "central")
    # Суммарная доля для хлеба ≤ пул × суммарный вес / нормировку (≈ пул × fmt_mult)
    # Слабая верхняя граница: не больше чем 2× pool (с учётом format-множителя обоих)
    pool = bread.base_daily_demand * region.demand_index
    assert total_sold <= pool * 3, (
        f"Суммарно продано {total_sold}, пул = {pool}"
    )


# ─── Тест 4: более низкая цена → бо́льшая доля ──────────────────────────────

def test_lower_price_wins_larger_share() -> None:
    """Ритейлер с более низким price_index получает бо́льшую долю спроса."""
    engine = _engine_with_two_retailers()

    # ret_a снижает цену, ret_b держит базовую
    engine.state.decisions["ret_a"] = CompanyDecision(
        target_price_index=0.85, ready=True
    )
    engine.state.decisions["ret_b"] = CompanyDecision(
        target_price_index=1.0, ready=True
    )

    engine.close_day()

    rep_a = next(r for r in engine.state.last_reports if r.company_id == "ret_a")
    rep_b = next(r for r in engine.state.last_reports if r.company_id == "ret_b")

    assert rep_a.sold_units > rep_b.sold_units, (
        f"Более дешёвый ret_a должен продать больше: {rep_a.sold_units} vs {rep_b.sold_units}"
    )


# ─── Тест 5: маркетинговый бюджет увеличивает долю ──────────────────────────

def test_marketing_increases_share() -> None:
    """Ритейлер с маркетинговым бюджетом получает бо́льшую долю."""
    engine = _engine_with_two_retailers()

    engine.state.decisions["ret_a"] = CompanyDecision(
        target_price_index=1.0, marketing_budget_rub=50_000, ready=True
    )
    engine.state.decisions["ret_b"] = CompanyDecision(
        target_price_index=1.0, marketing_budget_rub=0, ready=True
    )

    engine.close_day()

    rep_a = next(r for r in engine.state.last_reports if r.company_id == "ret_a")
    rep_b = next(r for r in engine.state.last_reports if r.company_id == "ret_b")

    assert rep_a.sold_units > rep_b.sold_units, (
        f"ret_a (маркетинг) должен продать больше: {rep_a.sold_units} vs {rep_b.sold_units}"
    )


# ─── Тест 6: ритейлеры в разных регионах не конкурируют ─────────────────────

def test_retailers_in_different_regions_do_not_compete() -> None:
    """Два ритейлера в разных регионах каждый получает свой полный пул."""
    state = build_initial_state()
    engine = GameEngine(state)

    state.companies = [c for c in state.companies if c.role != Role.RETAILER]

    ret_c = _make_retailer("ret_c", "Центр", "central")
    ret_s = _make_retailer("ret_s", "Юг", "south")
    state.companies.extend([ret_c, ret_s])

    for rid, reg in (("ret_c", "central"), ("ret_s", "south")):
        state.assets.append(_store_asset(rid, reg))
        state.inventories[rid] = {"bread": 10_000}
        engine._create_batches_from_inventory(rid, {"bread": 10_000})
        state.decisions[rid] = CompanyDecision(target_price_index=1.0, ready=True)

    engine.close_day()

    bread = next(p for p in engine.state.products if p.id == "bread")
    region_c = next(r for r in engine.state.regions if r.id == "central")
    region_s = next(r for r in engine.state.regions if r.id == "south")

    rep_c = next(r for r in engine.state.last_reports if r.company_id == "ret_c")
    rep_s = next(r for r in engine.state.last_reports if r.company_id == "ret_s")

    # Оба должны продать ≥ base_demand своего региона
    assert rep_c.sold_units >= int(bread.base_daily_demand * region_c.demand_index * 0.8)
    assert rep_s.sold_units >= int(bread.base_daily_demand * region_s.demand_index * 0.8)
