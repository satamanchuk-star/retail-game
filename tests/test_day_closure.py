"""Тесты закрытия дня защищают рынок от повторного начисления результата."""

import pytest
from app.domain.engine import GameEngine, build_initial_state
from app.main import app
from httpx import ASGITransport, AsyncClient


def test_close_day_with_same_closure_id_is_idempotent() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    before_cash = state.companies[0].cash_rub

    first = engine.close_day(closure_id="daily-close-001")
    after_first_cash = state.companies[0].cash_rub
    second = engine.close_day(closure_id="daily-close-001")

    assert first.day == 1
    assert second.day == 1
    assert second.repeated is True
    assert state.day == 1
    assert state.companies[0].cash_rub == after_first_cash
    assert after_first_cash != before_cash
    assert len(state.day_closures) == 1


def test_close_day_records_audit_operations() -> None:
    state = build_initial_state()
    engine = GameEngine(state)

    result = engine.close_day(closure_id="audit-close-001")

    assert result.operations
    assert {operation.step for operation in result.operations} >= {
        "production",
        "retail_sale",
        "financial_accounting",
    }


@pytest.mark.asyncio
async def test_day_closure_api_returns_saved_result_on_duplicate_key() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/reset")
        first = await client.post(
            "/api/close-day",
            json={"closure_id": "api-close-001"},
        )
        second = await client.post(
            "/api/close-day",
            json={"closure_id": "api-close-001"},
        )
        closures = await client.get("/api/day-closures")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["day"] == 1
    assert second.json()["day"] == 1
    assert second.json()["repeated"] is True
    assert closures.status_code == 200
    assert closures.json()[0]["closure_id"] == "api-close-001"
