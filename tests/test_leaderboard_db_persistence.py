"""Тесты DB-персиста зала славы: результаты переживают переподключение к БД."""

import pytest
from app.domain.models import LeaderboardEntry, Role
from app.services.database_store import DatabaseSnapshotStore


def _entry(game_no: int, source: str = "Основная партия") -> LeaderboardEntry:
    return LeaderboardEntry(
        game_no=game_no,
        source=source,
        recorded_at="2026-06-25T12:00:00",
        days_played=42,
        winner_company_id="player",
        winner_name="Игрок",
        winner_role=Role.RETAILER,
        winner_cash_rub=150_000_000,
        total_companies=6,
    )


@pytest.mark.asyncio
async def test_leaderboard_empty_before_any_save(tmp_path) -> None:
    store = DatabaseSnapshotStore(f"sqlite+aiosqlite:///{tmp_path / 'lb.db'}")
    await store.connect()
    try:
        assert await store.load_leaderboard() == []
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_leaderboard_persists_between_db_connections(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'lb.db'}"
    store = DatabaseSnapshotStore(db_url)
    await store.connect()
    await store.save_leaderboard([_entry(2, "Турнир"), _entry(1)])
    await store.close()

    # «рестарт»: свежее подключение читает ту же запись
    restored = DatabaseSnapshotStore(db_url)
    await restored.connect()
    try:
        loaded = await restored.load_leaderboard()
    finally:
        await restored.close()

    assert [e.game_no for e in loaded] == [2, 1]
    assert loaded[0].source == "Турнир"
    assert loaded[0].winner_name == "Игрок"


@pytest.mark.asyncio
async def test_leaderboard_save_overwrites_single_snapshot_row(tmp_path) -> None:
    store = DatabaseSnapshotStore(f"sqlite+aiosqlite:///{tmp_path / 'lb.db'}")
    await store.connect()
    try:
        await store.save_leaderboard([_entry(1)])
        await store.save_leaderboard([_entry(2), _entry(1)])
        loaded = await store.load_leaderboard()
        assert [e.game_no for e in loaded] == [2, 1]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_disabled_store_leaderboard_is_noop() -> None:
    store = DatabaseSnapshotStore(None)
    assert await store.load_leaderboard() == []
    await store.save_leaderboard([_entry(1)])  # без БД — тихий no-op
    assert await store.load_leaderboard() == []
