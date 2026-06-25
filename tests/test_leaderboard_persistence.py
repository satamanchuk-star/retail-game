"""Тесты персиста зала славы: результаты партий переживают рестарт процесса."""

from pathlib import Path

import pytest
from app.api import routes
from app.domain.models import LeaderboardEntry, Role
from app.main import app
from app.services.leaderboard_store import LeaderboardStore
from httpx import ASGITransport, AsyncClient


def _entry(game_no: int = 1) -> LeaderboardEntry:
    return LeaderboardEntry(
        game_no=game_no,
        source="Основная партия",
        recorded_at="2026-06-25T12:00:00",
        days_played=30,
        winner_company_id="player",
        winner_name="Игрок",
        winner_role=Role.RETAILER,
        winner_cash_rub=120_000_000,
        total_companies=6,
    )


def test_store_roundtrip_survives_new_instance(tmp_path: Path) -> None:
    path = str(tmp_path / "leaderboard.json")
    LeaderboardStore(path).save([_entry(2), _entry(1)])

    # «рестарт»: новый экземпляр стора читает тот же файл
    loaded = LeaderboardStore(path).load()
    assert [e.game_no for e in loaded] == [2, 1]
    assert loaded[0].winner_name == "Игрок"


def test_store_without_path_is_noop_in_memory() -> None:
    store = LeaderboardStore(None)
    assert store.enabled is False
    assert store.load() == []
    store.save([_entry()])  # не должно падать
    assert store.load() == []


def test_missing_file_loads_empty(tmp_path: Path) -> None:
    assert LeaderboardStore(str(tmp_path / "nope.json")).load() == []


@pytest.mark.asyncio
async def test_finished_game_is_persisted_and_reloadable(tmp_path: Path) -> None:
    path = str(tmp_path / "hall.json")
    saved_store = routes._leaderboard_store
    routes._leaderboard_store = LeaderboardStore(path)
    routes._leaderboard.clear()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/api/reset")
            routes._state.companies[0].cash_rub = routes._engine.WIN_CASH_THRESHOLD + 50_000_000
            await client.post("/api/close-day", json={"closure_id": "persist-win"})

        # файл записан
        assert Path(path).exists()
        # «рестарт»: свежий стор читает запись
        reloaded = LeaderboardStore(path).load()
        assert len(reloaded) == 1
        assert reloaded[0].winner_company_id == routes._state.companies[0].id
    finally:
        routes._leaderboard_store = saved_store
        routes._leaderboard.clear()
