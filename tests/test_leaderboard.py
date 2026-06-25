"""Тесты рейтинга лидеров: запись завершённых партий и устойчивость к сбросу."""

import pytest
from app.api import routes
from app.main import app
from httpx import ASGITransport, AsyncClient


async def _finish_game(client: AsyncClient, closure_id: str) -> None:
    """Форсировать победу по кэшу и закрыть день через API."""
    routes._state.companies[0].cash_rub = routes._engine.WIN_CASH_THRESHOLD + 50_000_000
    resp = await client.post("/api/close-day", json={"closure_id": closure_id})
    assert resp.status_code == 200
    assert routes._state.game_over is True


@pytest.mark.asyncio
async def test_leaderboard_empty_before_any_game_finished() -> None:
    routes._leaderboard.clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/reset")
        resp = await client.get("/api/leaderboard")
        assert resp.status_code == 200
        assert resp.json() == []


@pytest.mark.asyncio
async def test_finished_game_recorded_with_winner() -> None:
    routes._leaderboard.clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/reset")
        await _finish_game(client, "win-1")

        board = (await client.get("/api/leaderboard")).json()
        assert len(board) == 1
        entry = board[0]
        assert entry["game_no"] == 1
        assert entry["winner_company_id"] == routes._state.companies[0].id
        assert entry["winner_cash_rub"] >= routes._engine.WIN_CASH_THRESHOLD
        assert entry["total_companies"] == len(routes._state.companies)
        assert entry["recorded_at"]


@pytest.mark.asyncio
async def test_leaderboard_survives_reset_and_accumulates() -> None:
    routes._leaderboard.clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/reset")
        await _finish_game(client, "win-a")
        # сброс = новая партия; рейтинг лидеров должен сохраниться
        await client.post("/api/reset")
        assert routes._state.game_over is False
        board_after_reset = (await client.get("/api/leaderboard")).json()
        assert len(board_after_reset) == 1

        # вторая завершённая партия добавляет запись (новее — сверху)
        await _finish_game(client, "win-b")
        board = (await client.get("/api/leaderboard")).json()
        assert len(board) == 2
        assert board[0]["game_no"] == 2


@pytest.mark.asyncio
async def test_finished_game_recorded_only_once() -> None:
    routes._leaderboard.clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/reset")
        await _finish_game(client, "win-once")
        # повторный запрос дня по завершённой партии → 409, не вторая запись
        again = await client.post("/api/close-day", json={"closure_id": "after"})
        assert again.status_code == 409
        board = (await client.get("/api/leaderboard")).json()
        assert len(board) == 1
