"""Рейтинги проверяют, что после расчёта дня видна соревновательная цель."""

from app.domain.engine import GameEngine, build_initial_state
from app.domain.ratings import build_rating_board


def test_rating_board_orders_companies_after_close_day() -> None:
    state = build_initial_state()
    GameEngine(state).close_day()

    board = build_rating_board(state)

    assert board.day == 1
    assert len(board.overall) == len(state.companies)
    assert board.overall[0].rank == 1
    assert board.overall[0].score >= board.overall[-1].score
    assert board.by_role["retailer"]
