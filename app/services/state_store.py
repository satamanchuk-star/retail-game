"""Снапшоты мира нужны, чтобы прототип не терял прогресс между перезапусками."""

from pathlib import Path

from app.domain.engine import build_initial_state
from app.domain.models import GameState


class StateStore:
    """Простое файловое хранилище состояния для текущего прототипа.

    Это не замена PostgreSQL для финального мультиплеера, а безопасный
    промежуточный слой: API остаётся прежним, а состояние можно восстановить
    после перезапуска процесса.
    """

    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path).expanduser() if path else None

    @property
    def enabled(self) -> bool:
        """Проверить, включено ли сохранение состояния."""
        return self.path is not None

    def load_or_create(self) -> GameState:
        """Загрузить мир из файла или создать стартовый мир."""
        if self.path is None or not self.path.exists():
            return build_initial_state()
        return GameState.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, state: GameState) -> None:
        """Сохранить мир атомарной заменой файла."""
        if self.path is None:
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        tmp_path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        tmp_path.replace(self.path)

    def reset(self) -> GameState:
        """Создать стартовый мир и сразу сохранить его, если persistence включён."""
        state = build_initial_state()
        self.save(state)
        return state
