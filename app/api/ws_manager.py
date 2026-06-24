"""Менеджер WebSocket-соединений: broadcast событий по сессиям."""

from __future__ import annotations

import contextlib

from fastapi import WebSocket


class ConnectionManager:
    """Хранит активные WS-соединения и рассылает события всем клиентам сессии."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, session_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.setdefault(session_id, []).append(ws)

    def disconnect(self, session_id: str, ws: WebSocket) -> None:
        connections = self._connections.get(session_id, [])
        with contextlib.suppress(ValueError):
            connections.remove(ws)

    async def broadcast(self, session_id: str, message: dict) -> None:
        connections = list(self._connections.get(session_id, []))
        dead: list[WebSocket] = []
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(session_id, ws)

    def active_count(self, session_id: str) -> int:
        return len(self._connections.get(session_id, []))
