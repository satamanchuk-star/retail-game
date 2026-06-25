"""Тесты харнесса баланса: измеритель здоровья экономики стабилен и детерминирован."""

from app.domain.simulation import BalanceReport, run_balance_simulation


def test_balance_run_returns_sane_metrics() -> None:
    report = run_balance_simulation(days=20, seed=1)
    assert isinstance(report, BalanceReport)
    assert report.days <= 20
    assert report.companies == 6
    assert report.catalog_products == 30
    assert 0 < report.producible_products <= report.catalog_products
    assert report.total_units_sold > 0
    assert 0.0 <= report.cash_hhi <= 10_000.0
    assert report.leader_cash_rub >= report.min_cash_rub


def test_balance_run_is_deterministic_with_seed() -> None:
    a = run_balance_simulation(days=15, seed=7)
    b = run_balance_simulation(days=15, seed=7)
    assert a.leader_cash_rub == b.leader_cash_rub
    assert a.total_units_sold == b.total_units_sold
    assert a.price_inflation_pct == b.price_inflation_pct


def test_summary_flags_hollow_chain_in_current_baseline() -> None:
    # Пока в каталоге 30 товаров, а рецептов мало — харнесс обязан это ловить.
    report = run_balance_simulation(days=10, seed=3)
    if report.producible_products * 2 < report.catalog_products:
        assert "полая цепочка" in report.summary()
