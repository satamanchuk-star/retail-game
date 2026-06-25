"""Тесты завершения партии: блокировка дня, итоговый рейтинг, флоу новой игры."""

import pytest
from app.domain.engine import GameEngine, GameOverError, build_initial_state
from app.domain.models import CompanyStatus
from app.main import app
from httpx import ASGITransport, AsyncClient


def _engine() -> GameEngine:
    return GameEngine(build_initial_state())


# ─── Блокировка завершённой партии ──────────────────────────────────────────


def test_close_day_blocked_when_game_over() -> None:
    engine = _engine()
    engine.state.game_over = True
    with pytest.raises(GameOverError):
        engine.close_day()
    # день не сдвинулся
    assert engine.state.day == 0


def test_replay_of_closure_id_works_even_after_game_over() -> None:
    engine = _engine()
    first = engine.close_day(closure_id="final-day")
    engine.state.game_over = True
    # повтор того же closure_id возвращает кэш, а не падает
    replayed = engine.close_day(closure_id="final-day")
    assert replayed.day == first.day
    assert replayed.repeated is True


# ─── Итоговый рейтинг ───────────────────────────────────────────────────────


def test_compute_standings_orders_by_cash_and_pushes_bankrupts_last() -> None:
    engine = _engine()
    companies = engine.state.companies
    companies[0].cash_rub = 50_000_000
    companies[1].cash_rub = 90_000_000
    companies[2].cash_rub = -20_000_000
    companies[2].status = CompanyStatus.BANKRUPT
    engine.state.winner_company_id = companies[1].id

    standings = engine.compute_standings()

    assert [s.rank for s in standings] == list(range(1, len(companies) + 1))
    # первый — самый богатый активный и он же победитель
    assert standings[0].company_id == companies[1].id
    assert standings[0].is_winner is True
    # банкрот всегда в самом конце, несмотря на возможный кэш
    assert standings[-1].status == CompanyStatus.BANKRUPT
    assert standings[-1].company_id == companies[2].id


def test_winner_flag_only_on_winner() -> None:
    engine = _engine()
    engine.state.winner_company_id = engine.state.companies[0].id
    standings = engine.compute_standings()
    winners = [s for s in standings if s.is_winner]
    assert len(winners) == 1
    assert winners[0].company_id == engine.state.companies[0].id


# ─── API ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_close_day_returns_409_when_game_over() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/reset")
        # принудительно завершаем партию через win-порог по кэшу
        from app.api import routes

        routes._state.companies[0].cash_rub = routes._engine.WIN_CASH_THRESHOLD
        routes._engine.close_day(closure_id="win-day")
        assert routes._state.game_over is True

        resp = await client.post("/api/close-day", json={"closure_id": "next"})
        assert resp.status_code == 409


@pytest.mark.asyncio
async def test_api_game_status_exposes_final_standings_after_game_over() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/reset")
        from app.api import routes

        # до завершения — рейтинг пуст
        before = await client.get("/api/game-status")
        assert before.json()["final_standings"] == []

        routes._state.companies[0].cash_rub = routes._engine.WIN_CASH_THRESHOLD
        routes._engine.close_day(closure_id="win-day")

        after = await client.get("/api/game-status")
        body = after.json()
        assert body["game_over"] is True
        assert len(body["final_standings"]) == len(routes._state.companies)
        assert body["final_standings"][0]["rank"] == 1


# ─── Регрессии: завершённая партия не должна давать 500 на других эндпоинтах ──


@pytest.mark.asyncio
async def test_simulate_day_returns_409_not_500_when_game_over() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/reset")
        from app.api import routes

        routes._state.companies[0].cash_rub = routes._engine.WIN_CASH_THRESHOLD
        routes._engine.close_day(closure_id="win-day")
        assert routes._state.game_over is True

        cid = routes._state.companies[0].id
        resp = await client.post(f"/api/simulate-day/{cid}")
        assert resp.status_code == 409


@pytest.mark.asyncio
async def test_demo_run_returns_409_not_500_when_game_over() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/reset")
        from app.api import routes

        routes._state.companies[0].cash_rub = routes._engine.WIN_CASH_THRESHOLD
        routes._engine.close_day(closure_id="win-day")
        assert routes._state.game_over is True

        resp = await client.post("/api/demo/run")
        assert resp.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/sessions/no-such-session/game-status",
        "/api/sessions/no-such-session/market-events",
        "/api/sessions/no-such-session/prices",
        "/api/sessions/no-such-session/delivery-orders",
    ],
)
async def test_session_endpoints_return_404_not_500_for_missing_session(path: str) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(path)
        assert resp.status_code == 404
