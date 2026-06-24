"""Реестр игровых сессий: изоляция состояния мира для мультиплеера."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import GameState, SessionInfo
from app.domain.readiness_tracker import ReadinessTracker


@dataclass
class GameSession:
    id: str
    name: str
    engine: GameEngine
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    readiness: ReadinessTracker = field(default_factory=ReadinessTracker)

    @property
    def state(self) -> GameState:
        return self.engine.state

    def to_info(self) -> SessionInfo:
        return SessionInfo(
            id=self.id,
            name=self.name,
            day=self.state.day,
            companies=len(self.state.companies),
            created_at=self.created_at,
        )


class SessionRegistry:
    DEFAULT_ID = "default"

    def __init__(self) -> None:
        self._sessions: dict[str, GameSession] = {}

    def init_default(self, engine: GameEngine) -> GameSession:
        """Установить движок дефолтной сессии (вызывается при старте/сбросе)."""
        existing = self._sessions.get(self.DEFAULT_ID)
        session = GameSession(
            id=self.DEFAULT_ID,
            name="Основная игра",
            engine=engine,
            created_at=existing.created_at if existing else datetime.now(UTC),
        )
        self._sessions[self.DEFAULT_ID] = session
        return session

    def get(self, session_id: str) -> GameSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def get_default(self) -> GameSession:
        return self._sessions[self.DEFAULT_ID]

    def create(self, name: str) -> GameSession:
        session_id = uuid4().hex[:8]
        session = GameSession(
            id=session_id,
            name=name,
            engine=GameEngine(build_initial_state()),
        )
        self._sessions[session_id] = session
        return session

    def reset_session(self, session_id: str) -> GameSession:
        session = self.get(session_id)
        session.engine = GameEngine(build_initial_state())
        session.readiness = ReadinessTracker()
        return session

    def delete(self, session_id: str) -> None:
        if session_id == self.DEFAULT_ID:
            raise ValueError("Нельзя удалить основную сессию")
        self._sessions.pop(session_id, None)

    def list_all(self) -> list[GameSession]:
        return list(self._sessions.values())
