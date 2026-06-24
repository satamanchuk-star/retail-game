"""Трекер готовности компаний к закрытию дня в рамках одной сессии."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReadinessTracker:
    """Отслеживает, кто из людей-игроков уже отправил решение на текущий день."""

    _human: set[str] = field(default_factory=set)
    _submitted: set[str] = field(default_factory=set)

    def register(self, company_id: str) -> None:
        self._human.add(company_id)

    def unregister(self, company_id: str) -> None:
        self._human.discard(company_id)
        self._submitted.discard(company_id)

    def submit(self, company_id: str) -> None:
        if company_id in self._human:
            self._submitted.add(company_id)

    def reset(self) -> None:
        self._submitted.clear()

    @property
    def all_ready(self) -> bool:
        return bool(self._human) and self._submitted >= self._human

    @property
    def ready_count(self) -> int:
        return len(self._submitted & self._human)

    @property
    def total_count(self) -> int:
        return len(self._human)
