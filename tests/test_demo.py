"""Демо-сценарий проверяет, что пользователь сразу видит результат симуляции."""

from app.domain.demo import run_demo_scenario
from app.domain.engine import build_initial_state


def test_demo_scenario_returns_visible_week_result() -> None:
    state = build_initial_state()

    result = run_demo_scenario(state, days=7)

    assert len(result.days) == 7
    assert state.day == 7
    assert result.days[-1].day == 7
    assert any(day.sold_units > 0 for day in result.days)
    assert any(day.fulfilled_contracts > 0 for day in result.days)
