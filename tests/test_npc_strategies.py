"""Тесты NPC-стратегий, банкротства, победы и сезонности."""

from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import (
    BusinessAsset,
    Company,
    CompanyDecision,
    CompanyStatus,
    NpcStrategy,
    Role,
)


def _fresh_engine() -> GameEngine:
    return GameEngine(build_initial_state())


# ─── NPC-стратегии ────────────────────────────────────────────────────────────


def test_npc_aggressive_sets_low_price() -> None:
    """Агрессивный NPC устанавливает цену ниже 1.0."""
    engine = _fresh_engine()
    engine._apply_npc_decisions()
    aggr = next(c for c in engine.state.companies if c.id == "npc_retailer_aggr")
    decision = engine.state.decisions.get(aggr.id)
    assert decision is not None
    assert decision.target_price_index < 1.0


def test_npc_premium_sets_high_price() -> None:
    """Премиум-производитель NPC: при добавлении ритейлера со стратегией PREMIUM
    цена устанавливается выше 1.0."""
    state = build_initial_state()
    engine = GameEngine(state)
    # Добавляем NPC-ритейлера с PREMIUM-стратегией для проверки ценовой логики
    prem_ret = Company(
        id="prem_test",
        name="Тест-премиум",
        role=Role.RETAILER,
        region_id="north",
        cash_rub=5_000_000,
        is_npc=True,
        npc_strategy=NpcStrategy.PREMIUM,
    )
    state.companies.append(prem_ret)
    state.assets.append(BusinessAsset(
        id="asset_prem_test",
        company_id="prem_test",
        asset_type="store",
        name="Премиум",
        region_id="north",
        capacity_units_per_day=1_800,
        fixed_cost_rub_per_day=75_000,
        storage_type="смешанное",
        store_format="convenience",
    ))
    state.inventories["prem_test"] = {"bread": 200}
    engine._create_batches_from_inventory("prem_test", {"bread": 200})
    engine._apply_npc_decisions()
    decision = engine.state.decisions.get("prem_test")
    assert decision is not None
    assert decision.target_price_index > 1.0


def test_npc_balanced_default_price() -> None:
    """Balanced NPC ставит цену ~1.0 при нормальном запасе."""
    engine = _fresh_engine()
    engine._apply_npc_decisions()
    balanced = next(c for c in engine.state.companies if c.id == "npc_retailer")
    decision = engine.state.decisions.get(balanced.id)
    assert decision is not None
    assert 0.9 <= decision.target_price_index <= 1.15


def test_bankrupt_npc_skipped_in_decisions() -> None:
    """Банкрот не получает решений и не участвует в торгах."""
    engine = _fresh_engine()
    npc = next(c for c in engine.state.companies if c.id == "npc_retailer_aggr")
    npc.status = CompanyStatus.BANKRUPT
    engine._apply_npc_decisions()
    assert engine.state.decisions.get(npc.id) is None


# ─── Банкротство и победа ─────────────────────────────────────────────────────


def test_bankruptcy_triggered_at_negative_cash() -> None:
    """Компания с кэшем ниже порога банкротится при проверке."""
    engine = _fresh_engine()
    victim = engine.state.companies[0]
    victim.cash_rub = -15_000_000
    news: list[str] = []
    ops: list = []
    engine._check_bankruptcy_and_victory(news, ops)
    assert victim.status == CompanyStatus.BANKRUPT
    assert any("банкрот" in n.lower() for n in news)


def test_win_by_cash_threshold() -> None:
    """Компания с кэшем ≥ порога становится победителем."""
    engine = _fresh_engine()
    winner = engine.state.companies[0]
    winner.cash_rub = 100_000_000
    news: list[str] = []
    engine._check_bankruptcy_and_victory(news, [])
    assert engine.state.game_over is True
    assert engine.state.winner_company_id == winner.id
    assert any("выиграла" in n for n in news)


def test_win_by_last_survivor() -> None:
    """Если остался один активный — он победитель."""
    engine = _fresh_engine()
    survivor = engine.state.companies[0]
    for c in engine.state.companies[1:]:
        c.status = CompanyStatus.BANKRUPT
    news: list[str] = []
    engine._check_bankruptcy_and_victory(news, [])
    assert engine.state.game_over is True
    assert engine.state.winner_company_id == survivor.id


def test_no_win_if_already_game_over() -> None:
    """После game_over повторный вызов не меняет победителя."""
    engine = _fresh_engine()
    engine.state.game_over = True
    engine.state.winner_company_id = "old_winner"
    engine.state.companies[1].cash_rub = 200_000_000
    engine._check_bankruptcy_and_victory([], [])
    assert engine.state.winner_company_id == "old_winner"


# ─── Сезонность ───────────────────────────────────────────────────────────────


def test_season_advances_after_close_day() -> None:
    """Сезон обновляется после закрытия дня."""
    engine = _fresh_engine()
    assert engine.state.season == 1
    # 7 дней = переход к сезону 2
    for _ in range(7):
        engine.close_day()
    assert engine.state.season == 2


def test_seasonal_multiplier_increases_summer_water_demand() -> None:
    """Летом (сезон 2) продажи воды выше зимних (сезон 4)."""
    def _make_water_engine() -> GameEngine:
        state = build_initial_state()
        engine = GameEngine(state)
        state.companies = [c for c in state.companies if c.role != Role.RETAILER]
        ret = Company(
            id="seasonal_ret", name="Сезон-тест", role=Role.RETAILER,
            region_id="central", cash_rub=5_000_000, is_npc=False,
        )
        state.companies.append(ret)
        state.assets.append(BusinessAsset(
            id="asset_seasonal", company_id="seasonal_ret", asset_type="store",
            name="Сезон", region_id="central", capacity_units_per_day=50_000,
            fixed_cost_rub_per_day=0, storage_type="обычное", store_format="convenience",
        ))
        state.inventories["seasonal_ret"] = {"water": 50_000}
        engine._create_batches_from_inventory("seasonal_ret", {"water": 50_000})
        state.decisions["seasonal_ret"] = CompanyDecision(target_price_index=1.0, ready=True)
        return engine

    engine_summer = _make_water_engine()
    engine_summer.state.season = 2
    engine_summer.close_day()
    summer_sold = sum(p.total_units_sold for p in engine_summer.state.price_history if p.product_id == "water")

    engine_winter = _make_water_engine()
    engine_winter.state.season = 4
    engine_winter.close_day()
    winter_sold = sum(p.total_units_sold for p in engine_winter.state.price_history if p.product_id == "water")

    assert summer_sold > winter_sold, (
        f"Летом воды должно продаваться больше: {summer_sold} vs {winter_sold}"
    )
