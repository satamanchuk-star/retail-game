"""Рейтинги делают цель игры видимой: игрок понимает, кто выигрывает рынок."""

from app.domain.models import GameState, RatingBoard, RatingEntry, Role


def build_rating_board(state: GameState) -> RatingBoard:
    """Построить общий и ролевой рейтинг на основе денег, прибыли и репутации."""
    profit_by_company = {report.company_id: report.profit_rub for report in state.last_reports}
    entries = [
        RatingEntry(
            company_id=company.id,
            company_name=company.name,
            role=company.role,
            score=_score_company(company.cash_rub, company.reputation, profit_by_company.get(company.id, 0)),
            cash_rub=company.cash_rub,
            reputation=company.reputation,
            last_profit_rub=profit_by_company.get(company.id, 0),
            rank=0,
        )
        for company in state.companies
    ]
    overall = _rank(entries)
    by_role = {
        role: _rank([entry for entry in entries if entry.role == role])
        for role in Role
    }
    return RatingBoard(day=state.day, overall=overall, by_role=by_role)


def _score_company(cash_rub: int, reputation: float, last_profit_rub: int) -> float:
    """Сбалансировать капитал, текущую эффективность и доверие рынка."""
    return round(cash_rub / 1_000_000 + reputation + last_profit_rub / 50_000, 2)


def _rank(entries: list[RatingEntry]) -> list[RatingEntry]:
    ranked = sorted(entries, key=lambda item: item.score, reverse=True)
    return [entry.model_copy(update={"rank": index + 1}) for index, entry in enumerate(ranked)]
