"""Зал славы переживает рестарт: результаты партий хранятся отдельным JSON-файлом.

Рейтинг лидеров живёт вне GameState (он переживает сброс партии), поэтому к
снапшоту состояния его не привязать — нужен собственный файловый канал.
"""

from pathlib import Path

from pydantic import TypeAdapter

from app.domain.models import LeaderboardEntry

_ADAPTER = TypeAdapter(list[LeaderboardEntry])


class LeaderboardStore:
    """Файловое хранилище зала славы. Без пути работает как in-memory (no-op)."""

    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path).expanduser() if path else None

    @property
    def enabled(self) -> bool:
        return self.path is not None

    def load(self) -> list[LeaderboardEntry]:
        """Загрузить рейтинг из файла или вернуть пустой список."""
        if self.path is None or not self.path.exists():
            return []
        return _ADAPTER.validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, entries: list[LeaderboardEntry]) -> None:
        """Сохранить рейтинг атомарной заменой файла."""
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        tmp_path.write_bytes(_ADAPTER.dump_json(entries, indent=2))
        tmp_path.replace(self.path)
