"""Банковские тесты защищают cash-flow и долговую механику прототипа."""

from app.domain.engine import GameEngine, build_initial_state
from app.domain.models import LoanCreate


def test_issue_loan_increases_company_cash_and_records_loan() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    before_cash = state.companies[0].cash_rub

    loan = engine.issue_loan(
        LoanCreate(
            company_id="player",
            bank_id="steady_bank",
            principal_rub=1_000_000,
            term_days=30,
        )
    )

    assert loan.outstanding_rub == 1_000_000
    assert state.companies[0].cash_rub == before_cash + 1_000_000
    assert state.loans[0].id == loan.id


def test_close_day_accrues_loan_interest() -> None:
    state = build_initial_state()
    engine = GameEngine(state)
    engine.issue_loan(
        LoanCreate(
            company_id="player",
            bank_id="steady_bank",
            principal_rub=1_000_000,
            term_days=30,
        )
    )

    result = engine.close_day()
    player_report = next(report for report in result.reports if report.company_id == "player")

    assert state.loans[0].accrued_interest_rub > 0
    assert player_report.costs_rub >= state.loans[0].accrued_interest_rub


def test_loan_defaults_after_term_expires() -> None:
    """Кредит помечается просроченным после истечения срока (term_days=7)."""
    state = build_initial_state()
    engine = GameEngine(state)
    loan = engine.issue_loan(
        LoanCreate(
            company_id="player",
            bank_id="steady_bank",
            principal_rub=500_000,
            term_days=7,
        )
    )
    assert not loan.is_defaulted

    # 8 closes: on day 8 the condition state.day+1 > 0+7 becomes True
    for _ in range(8):
        engine.close_day()

    assert loan.is_defaulted
