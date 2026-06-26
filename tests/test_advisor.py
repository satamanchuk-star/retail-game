"""Тесты советника (Фаза 5): читаемые подсказки по состоянию компании."""

import pytest
from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import AssetType, CompanyStatus, Role
from app.main import app
from httpx import ASGITransport, AsyncClient


def _engine() -> GameEngine:
    return GameEngine(build_initial_state())


def test_negative_cash_yields_danger_tip() -> None:
    engine = _engine()
    player = next(c for c in engine.state.companies if c.id == "player")
    player.cash_rub = -500_000
    tips = engine.build_advice(player.id)
    assert any(t.severity == "danger" for t in tips)


def test_overstocked_retailer_gets_warning() -> None:
    engine = _engine()
    player = next(c for c in engine.state.companies if c.id == "player")
    cap = engine._daily_capacity(player.id, AssetType.STORE, 1_000)
    engine.state.inventories[player.id] = {"bread": cap * 10}
    tips = engine.build_advice(player.id)
    assert any("Затоваривание" in t.message for t in tips)


def test_producer_raw_shortage_warning() -> None:
    engine = _engine()
    producer = next(c for c in engine.state.companies if c.role == Role.PRODUCER)
    engine.state.raw_inventories[producer.id] = {"grain": 10.0}
    tips = engine.build_advice(producer.id)
    assert any("Дефицит сырья" in t.message for t in tips)


def test_bankrupt_company_gets_single_danger_tip() -> None:
    engine = _engine()
    player = next(c for c in engine.state.companies if c.id == "player")
    player.status = CompanyStatus.BANKRUPT
    tips = engine.build_advice(player.id)
    assert len(tips) == 1
    assert tips[0].severity == "danger"


def test_unknown_company_is_graceful() -> None:
    tips = _engine().build_advice("no-such-company")
    assert tips and tips[0].severity == "info"


def test_idle_capital_tip_for_cash_rich_company() -> None:
    engine = _engine()
    player = next(c for c in engine.state.companies if c.id == "player")
    player.cash_rub = 30_000_000
    tips = engine.build_advice(player.id)
    assert any("Свободный капитал" in t.message for t in tips)


def test_expiring_stock_warning() -> None:
    from app.domain.models import InventoryBatch

    engine = _engine()
    player = next(c for c in engine.state.companies if c.id == "player")
    engine.state.inventory_batches.append(
        InventoryBatch(
            id="exp",
            company_id=player.id,
            product_id="milk",
            quantity=400,
            created_day=engine.state.day,
            expires_day=engine.state.day + 1,  # просрочится завтра
            storage="холодильник",
        )
    )
    tips = engine.build_advice(player.id)
    assert any("Скоро просрочка" in t.message for t in tips)


def test_tips_sorted_by_severity() -> None:
    engine = _engine()
    player = next(c for c in engine.state.companies if c.id == "player")
    player.cash_rub = -500_000  # danger
    tips = engine.build_advice(player.id)
    order = {"danger": 0, "warning": 1, "info": 2, "ok": 3}
    ranks = [order[t.severity] for t in tips]
    assert ranks == sorted(ranks), "подсказки должны идти по убыванию важности"
    assert tips[0].severity == "danger"


@pytest.mark.asyncio
async def test_advisor_endpoint_returns_tips() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/reset")
        resp = await client.get("/api/advisor?company_id=player")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list) and body
        assert {"severity", "message"} <= set(body[0])
