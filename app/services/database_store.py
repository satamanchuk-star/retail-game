"""DB-снимок нужен как безопасный следующий шаг от JSON к постоянному миру."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.domain.engine import build_initial_state
from app.domain.models import GameState

SNAPSHOT_KEY = "default_world"


class DatabaseSnapshotStore:
    """Минимальное async-хранилище полного снимка мира в SQLAlchemy."""

    def __init__(self, database_url: str | None) -> None:
        self.database_url = database_url
        self.engine: AsyncEngine | None = None

    @property
    def enabled(self) -> bool:
        """Показать, активен ли DB-режим."""
        return self.database_url is not None

    @property
    def dialect(self) -> str | None:
        """Вернуть диалект без раскрытия строки подключения."""
        if self.engine is None:
            return None
        return self.engine.dialect.name

    async def connect(self) -> None:
        """Создать engine и таблицу снимков, если DB включена."""
        if not self.database_url or self.engine is not None:
            return
        self.engine = create_async_engine(self.database_url)
        async with self.engine.begin() as connection:
            await connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS game_snapshots ("
                    "snapshot_key VARCHAR(80) PRIMARY KEY, "
                    "payload TEXT NOT NULL, "
                    "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            )

    async def close(self) -> None:
        """Закрыть пул соединений при остановке приложения."""
        if self.engine is None:
            return
        await self.engine.dispose()
        self.engine = None

    async def load_or_create(self) -> GameState:
        """Загрузить мир из DB или создать стартовый снимок."""
        if self.engine is None:
            return build_initial_state()
        async with self.engine.begin() as connection:
            result = await connection.execute(
                text("SELECT payload FROM game_snapshots WHERE snapshot_key = :key"),
                {"key": SNAPSHOT_KEY},
            )
            payload = result.scalar_one_or_none()
            if payload is not None:
                return GameState.model_validate_json(payload)

            state = build_initial_state()
            await connection.execute(
                text(
                    "INSERT INTO game_snapshots (snapshot_key, payload) "
                    "VALUES (:key, :payload)"
                ),
                {"key": SNAPSHOT_KEY, "payload": state.model_dump_json()},
            )
            return state

    async def save(self, state: GameState) -> None:
        """Сохранить актуальный снимок мира в одной короткой транзакции."""
        if self.engine is None:
            return
        async with self.engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM game_snapshots WHERE snapshot_key = :key"),
                {"key": SNAPSHOT_KEY},
            )
            await connection.execute(
                text(
                    "INSERT INTO game_snapshots (snapshot_key, payload) "
                    "VALUES (:key, :payload)"
                ),
                {"key": SNAPSHOT_KEY, "payload": state.model_dump_json()},
            )

    async def reset(self) -> GameState:
        """Сбросить DB-снимок к стартовому миру."""
        state = build_initial_state()
        await self.save(state)
        return state
