"""Финансовые тесты защищают P&L, НДС и журнал проводок рынка."""

import pytest
from app.domain.engine import GameEngine, build_initial_state
from app.main import app
from httpx import ASGITransport, AsyncClient


def test_close_day_creates_financial_report_and_ledger_entries() -> None:
    state = build_initial_state()
    engine = GameEngine(state)

    result = engine.close_day(closure_id="finance-close-001")
    report = engine.build_financial_report("player")

    assert result.day == 1
    assert report.company_id == "player"
    assert report.revenue_rub > 0
    assert report.vat_output_rub > 0
    assert report.vat_payable_rub >= 0
    assert report.ledger_entries
    assert {entry.entry_type for entry in report.ledger_entries} >= {"revenue", "cost"}


def test_repeated_day_closure_does_not_duplicate_ledger_entries() -> None:
    state = build_initial_state()
    engine = GameEngine(state)

    engine.close_day(closure_id="finance-idempotent-001")
    ledger_count = len(state.ledger_entries)
    repeated = engine.close_day(closure_id="finance-idempotent-001")

    assert repeated.repeated is True
    assert len(state.ledger_entries) == ledger_count


@pytest.mark.asyncio
async def test_finances_api_returns_reports_without_auth() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/reset")
        await client.post(
            "/api/close-day",
            json={"closure_id": "finance-api-close-001"},
        )
        response = await client.get("/api/finances")
        company_response = await client.get("/api/finances/player")

    assert response.status_code == 200
    assert company_response.status_code == 200
    assert response.json()[0]["ledger_entries"]
    assert company_response.json()["company_id"] == "player"
