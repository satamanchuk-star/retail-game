"""Тесты Alembic-миграций и ORM-хранилища."""

import asyncio
import os
import tempfile

import pytest
from app.domain.engine import build_initial_state
from app.services.database_store import DatabaseSnapshotStore


def _sqlite_url(path: str) -> str:
    return f"sqlite+aiosqlite:///{path}"


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def db_store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        url = _sqlite_url(f.name)
    store = DatabaseSnapshotStore(url)
    _run(store.connect())
    yield store
    _run(store.close())
    os.unlink(f.name)


def test_load_or_create_returns_initial_state(db_store):
    """Пустая БД возвращает стартовый мир."""
    state = _run(db_store.load_or_create())
    assert state.day == 0
    assert len(state.companies) > 0


def test_save_and_reload_preserves_day(db_store):
    """Сохранённый день сохраняется после перезагрузки."""
    state = _run(db_store.load_or_create())
    state.day = 7
    _run(db_store.save(state))

    state2 = _run(db_store.load_or_create())
    assert state2.day == 7


def test_reset_returns_day_zero(db_store):
    """reset() сбрасывает мир к стартовому состоянию."""
    state = _run(db_store.load_or_create())
    state.day = 5
    _run(db_store.save(state))

    fresh = _run(db_store.reset())
    assert fresh.day == 0

    reloaded = _run(db_store.load_or_create())
    assert reloaded.day == 0


def test_save_session_and_load(db_store):
    """Сессия сохраняется и загружается по id."""
    state = build_initial_state()
    state.day = 3
    _run(db_store.save_session("sess_abc", "Тест-сессия", state))

    loaded = _run(db_store.load_session("sess_abc"))
    assert loaded is not None
    assert loaded.day == 3


def test_load_session_missing_returns_none(db_store):
    """Несуществующая сессия возвращает None."""
    result = _run(db_store.load_session("no_such_session"))
    assert result is None


def test_list_sessions(db_store):
    """list_sessions возвращает все сохранённые сессии."""
    state = build_initial_state()
    _run(db_store.save_session("s1", "Партия 1", state))
    _run(db_store.save_session("s2", "Партия 2", state))

    sessions = _run(db_store.list_sessions())
    ids = {s[0] for s in sessions}
    assert {"s1", "s2"} <= ids


def test_delete_session(db_store):
    """Удалённая сессия больше не возвращается."""
    state = build_initial_state()
    _run(db_store.save_session("s_del", "Удалить", state))
    _run(db_store.delete_session("s_del"))

    assert _run(db_store.load_session("s_del")) is None


def test_overwrite_session_updates_state(db_store):
    """Повторный save_session обновляет, а не дублирует."""
    state = build_initial_state()
    _run(db_store.save_session("s_upd", "Партия", state))
    state.day = 10
    _run(db_store.save_session("s_upd", "Партия", state))

    loaded = _run(db_store.load_session("s_upd"))
    assert loaded is not None
    assert loaded.day == 10
    sessions = _run(db_store.list_sessions())
    assert sum(1 for s in sessions if s[0] == "s_upd") == 1


def test_alembic_migrations_apply_cleanly():
    """Alembic upgrade head выполняется без ошибок на чистой SQLite."""
    import subprocess
    import sys
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    env = {**os.environ, "PROFIT_CHAIN_DATABASE_URL": _sqlite_url(db_path)}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True, text=True, env=env,
        cwd=os.path.dirname(os.path.dirname(__file__)),
    )
    os.unlink(db_path)
    assert result.returncode == 0, result.stderr
    assert "Running upgrade" in result.stderr
