"""DB-снимок нужен как безопасный следующий шаг от JSON к постоянному миру."""

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.domain.engine import build_initial_state
from app.domain.models import GameState, LeaderboardEntry
from app.services.orm import (
    Base,
    GameSessionRow,
    GameSnapshotRow,
    LeaderboardSnapshotRow,
)

SNAPSHOT_KEY = "default_world"
LEADERBOARD_KEY = "default_leaderboard"
_LEADERBOARD_ADAPTER = TypeAdapter(list[LeaderboardEntry])


class DatabaseSnapshotStore:
    """Async-хранилище через SQLAlchemy ORM (SQLite dev / PostgreSQL prod)."""

    def __init__(self, database_url: str | None) -> None:
        self.database_url = database_url
        self.engine: AsyncEngine | None = None
        self._session_factory: sessionmaker | None = None  # type: ignore[type-arg]

    @property
    def enabled(self) -> bool:
        return self.database_url is not None

    @property
    def dialect(self) -> str | None:
        if self.engine is None:
            return None
        return self.engine.dialect.name

    async def connect(self) -> None:
        """Создать engine и таблицы (если ещё не существуют)."""
        if not self.database_url or self.engine is not None:
            return
        self.engine = create_async_engine(self.database_url)
        self._session_factory = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        if self.engine is None:
            return
        await self.engine.dispose()
        self.engine = None
        self._session_factory = None

    def _session(self) -> AsyncSession:
        if self._session_factory is None:
            raise RuntimeError("DB not connected")
        return self._session_factory()

    # ── Глобальный снимок мира ────────────────────────────────────────────────

    async def load_or_create(self) -> GameState:
        if self.engine is None:
            return build_initial_state()
        async with self._session() as session:
            row = await session.get(GameSnapshotRow, SNAPSHOT_KEY)
            if row is not None:
                return GameState.model_validate_json(row.payload)
            state = build_initial_state()
            session.add(GameSnapshotRow(
                snapshot_key=SNAPSHOT_KEY,
                payload=state.model_dump_json(),
            ))
            await session.commit()
            return state

    async def save(self, state: GameState) -> None:
        if self.engine is None:
            return
        async with self._session() as session:
            row = await session.get(GameSnapshotRow, SNAPSHOT_KEY)
            if row is None:
                session.add(GameSnapshotRow(
                    snapshot_key=SNAPSHOT_KEY,
                    payload=state.model_dump_json(),
                ))
            else:
                row.payload = state.model_dump_json()
            await session.commit()

    async def reset(self) -> GameState:
        state = build_initial_state()
        await self.save(state)
        return state

    # ── Сессии мультиплеера ───────────────────────────────────────────────────

    async def save_session(self, session_id: str, name: str, state: GameState) -> None:
        """Сохранить состояние сессии в БД."""
        if self.engine is None:
            return
        async with self._session() as db_session:
            row = await db_session.get(GameSessionRow, session_id)
            if row is None:
                db_session.add(GameSessionRow(
                    session_id=session_id,
                    name=name,
                    state_json=state.model_dump_json(),
                ))
            else:
                row.state_json = state.model_dump_json()
            await db_session.commit()

    async def load_session(self, session_id: str) -> GameState | None:
        """Загрузить состояние сессии из БД. None — если не найдено."""
        if self.engine is None:
            return None
        async with self._session() as db_session:
            row = await db_session.get(GameSessionRow, session_id)
            if row is None:
                return None
            return GameState.model_validate_json(row.state_json)

    async def list_sessions(self) -> list[tuple[str, str]]:
        """Вернуть [(session_id, name)] всех сохранённых сессий."""
        if self.engine is None:
            return []
        async with self._session() as db_session:
            result = await db_session.execute(
                select(GameSessionRow.session_id, GameSessionRow.name)
            )
            return list(result.all())

    async def delete_session(self, session_id: str) -> None:
        """Удалить сессию из БД."""
        if self.engine is None:
            return
        async with self._session() as db_session:
            row = await db_session.get(GameSessionRow, session_id)
            if row is not None:
                await db_session.delete(row)
                await db_session.commit()

    # ── Зал славы ─────────────────────────────────────────────────────────────

    async def load_leaderboard(self) -> list[LeaderboardEntry]:
        """Загрузить зал славы из БД (пусто, если ещё не сохранялся)."""
        if self.engine is None:
            return []
        async with self._session() as db_session:
            row = await db_session.get(LeaderboardSnapshotRow, LEADERBOARD_KEY)
            if row is None:
                return []
            return _LEADERBOARD_ADAPTER.validate_json(row.payload)

    async def save_leaderboard(self, entries: list[LeaderboardEntry]) -> None:
        """Сохранить весь зал славы одной строкой-снимком."""
        if self.engine is None:
            return
        payload = _LEADERBOARD_ADAPTER.dump_json(entries).decode("utf-8")
        async with self._session() as db_session:
            row = await db_session.get(LeaderboardSnapshotRow, LEADERBOARD_KEY)
            if row is None:
                db_session.add(
                    LeaderboardSnapshotRow(snapshot_key=LEADERBOARD_KEY, payload=payload)
                )
            else:
                row.payload = payload
            await db_session.commit()
