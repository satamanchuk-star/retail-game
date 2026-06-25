"""Тесты записи результатов сессионных партий в общий зал славы."""

import pytest
from app.api import routes
from app.main import app
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_finished_session_game_recorded_with_session_name() -> None:
    routes._leaderboard.clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/sessions", json={"name": "Турнир Альфа"})
        assert created.status_code == 201
        sid = created.json()["id"]

        session = routes._registry.get(sid)
        session.state.companies[0].cash_rub = session.engine.WIN_CASH_THRESHOLD + 50_000_000

        resp = await client.post(f"/api/sessions/{sid}/close-day", json={"closure_id": "s-win"})
        assert resp.status_code == 200
        assert session.state.game_over is True

        board = (await client.get("/api/leaderboard")).json()
        assert len(board) == 1
        assert board[0]["source"] == "Турнир Альфа"
        assert board[0]["winner_company_id"] == session.state.companies[0].id


@pytest.mark.asyncio
async def test_main_game_keeps_default_source_label() -> None:
    routes._leaderboard.clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/reset")
        routes._state.companies[0].cash_rub = routes._engine.WIN_CASH_THRESHOLD + 50_000_000
        await client.post("/api/close-day", json={"closure_id": "main-win"})

        board = (await client.get("/api/leaderboard")).json()
        assert board[0]["source"] == "Основная партия"


@pytest.mark.asyncio
async def test_session_close_day_returns_409_when_session_game_over() -> None:
    routes._leaderboard.clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/sessions", json={"name": "Турнир Бета"})
        sid = created.json()["id"]
        session = routes._registry.get(sid)
        session.state.companies[0].cash_rub = session.engine.WIN_CASH_THRESHOLD + 50_000_000
        await client.post(f"/api/sessions/{sid}/close-day", json={"closure_id": "b-win"})
        assert session.state.game_over is True

        again = await client.post(f"/api/sessions/{sid}/close-day", json={"closure_id": "b-next"})
        assert again.status_code == 409
        # повторная попытка не добавила вторую запись
        board = (await client.get("/api/leaderboard")).json()
        assert len(board) == 1
