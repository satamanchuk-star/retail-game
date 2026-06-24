"""Тесты защищают ключевой игровой цикл первого прототипа."""

import pytest
from app.domain.balance import PRODUCTS, REGIONS, STARTER_COMPANIES
from app.domain.models import GameState
from app.domain.simulation import simulate_retail_day
from app.main import app
from httpx import ASGITransport, AsyncClient


def test_simulate_retail_day_returns_positive_sales() -> None:
    state = GameState(day=0, regions=REGIONS, products=PRODUCTS, companies=STARTER_COMPANIES, news=[])

    result = simulate_retail_day(state, "player")

    assert result.day == 1
    assert result.sold_units > 0
    assert result.revenue_rub > result.costs_rub
    assert result.profit_rub > 0


@pytest.mark.asyncio
async def test_state_api_contains_full_product_matrix() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["day"] >= 0
    assert len(payload["regions"]) == 5
    assert len(payload["products"]) == 30


@pytest.mark.asyncio
async def test_company_decision_and_close_day_api_flow() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_response = await client.post(
            "/api/companies",
            json={"name": "Тестовый дистрибьютор", "role": "distributor", "region_id": "north"},
        )
        assert create_response.status_code == 201
        company_id = create_response.json()["id"]

        decision_response = await client.post(
            f"/api/decisions/{company_id}",
            json={"logistics_capacity_units": 2_000, "ready": True},
        )
        assert decision_response.status_code == 200

        close_response = await client.post("/api/close-day")
        assert close_response.status_code == 200
        payload = close_response.json()
        assert any(report["company_id"] == company_id for report in payload["reports"])


@pytest.mark.asyncio
async def test_demo_and_reset_api_flow() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        reset_response = await client.post("/api/reset")
        assert reset_response.status_code == 200

        demo_response = await client.post("/api/demo/run")
        assert demo_response.status_code == 200
        demo_payload = demo_response.json()
        assert len(demo_payload["days"]) == 7
        assert demo_payload["days"][-1]["day"] == 7

        state_response = await client.get("/api/state")
        assert state_response.json()["day"] == 7


@pytest.mark.asyncio
async def test_ratings_api_flow() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/reset")
        await client.post("/api/close-day")
        response = await client.get("/api/ratings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall"][0]["rank"] == 1
    assert payload["by_role"]["retailer"]


@pytest.mark.asyncio
async def test_banks_and_loans_api_flow() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/reset")
        banks_response = await client.get("/api/banks")
        assert banks_response.status_code == 200
        assert len(banks_response.json()) == 3

        loan_response = await client.post(
            "/api/loans",
            json={
                "company_id": "player",
                "bank_id": "steady_bank",
                "principal_rub": 1_000_000,
                "term_days": 30,
            },
        )
        assert loan_response.status_code == 201

        close_response = await client.post("/api/close-day")
        assert close_response.status_code == 200
        state_response = await client.get("/api/state")
        assert state_response.json()["loans"][0]["accrued_interest_rub"] > 0


@pytest.mark.asyncio
async def test_persistence_status_api_flow() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/reset")
        response = await client.get("/api/persistence")

    assert response.status_code == 200
    payload = response.json()
    assert payload["day"] == 0
    assert payload["companies"] >= 3
    assert payload["enabled"] is False


@pytest.mark.asyncio
async def test_database_status_api_flow() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/database/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["active"] is False
    assert "database_url" not in payload
    assert "companies" in payload
