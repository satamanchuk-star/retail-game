"""Тесты доступа защищают следующий шаг к реальному мультиплееру."""

import pytest
from app.main import app
from httpx import ASGITransport, AsyncClient


async def _register(client: AsyncClient, username: str) -> str:
    response = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "password123"},
    )
    assert response.status_code == 201
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_register_login_and_me_flow() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/reset")
        token = await _register(client, "owner_one")

        me_response = await client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        assert me_response.status_code == 200
        assert me_response.json()["username"] == "owner_one"

        login_response = await client.post(
            "/api/auth/login",
            json={"username": "owner_one", "password": "password123"},
        )
        assert login_response.status_code == 200
        assert login_response.json()["access_token"]


@pytest.mark.asyncio
async def test_public_state_does_not_expose_auth_secrets() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/reset")
        await _register(client, "secret_owner")
        response = await client.get("/api/state")

    assert response.status_code == 200
    payload = response.json()
    assert "users" not in payload
    assert "sessions" not in payload
    assert "password_hash" not in str(payload)


@pytest.mark.asyncio
async def test_owner_can_manage_own_company_and_other_user_cannot() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/reset")
        owner_token = await _register(client, "owner_two")
        intruder_token = await _register(client, "intruder_two")

        create_response = await client.post(
            "/api/companies",
            json={"name": "Защищённая сеть", "role": "retailer", "region_id": "central"},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert create_response.status_code == 201
        company = create_response.json()
        assert company["owner_user_id"] is not None

        own_decision = await client.post(
            f"/api/decisions/{company['id']}",
            json={"target_price_index": 1.0, "ready": True},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert own_decision.status_code == 200

        intruder_decision = await client.post(
            f"/api/decisions/{company['id']}",
            json={"target_price_index": 1.0, "ready": True},
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_decision.status_code == 403


@pytest.mark.asyncio
async def test_contract_requires_participation_of_owned_company() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/reset")
        owner_token = await _register(client, "contract_owner")
        outsider_token = await _register(client, "contract_outsider")
        company_response = await client.post(
            "/api/companies",
            json={"name": "Контрактный завод", "role": "producer", "region_id": "volga"},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        seller_id = company_response.json()["id"]
        payload = {
            "contract_type": "supply",
            "seller_id": seller_id,
            "buyer_id": "player",
            "product_id": "bread",
            "quantity": 100,
            "unit_price_rub": 50,
            "due_day": 1,
            "penalty_rub": 1000,
        }

        forbidden_response = await client.post(
            "/api/contracts",
            json=payload,
            headers={"Authorization": f"Bearer {outsider_token}"},
        )
        assert forbidden_response.status_code == 403

        allowed_response = await client.post(
            "/api/contracts",
            json=payload,
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert allowed_response.status_code == 201
