"""Unit-тесты трекера готовности: изоляция логики от HTTP и WebSocket."""

from app.domain.readiness_tracker import ReadinessTracker


def test_empty_tracker_is_not_ready() -> None:
    t = ReadinessTracker()
    assert not t.all_ready
    assert t.ready_count == 0
    assert t.total_count == 0


def test_all_ready_when_all_humans_submit() -> None:
    t = ReadinessTracker()
    t.register("a")
    t.register("b")
    t.submit("a")
    assert not t.all_ready
    t.submit("b")
    assert t.all_ready
    assert t.ready_count == 2
    assert t.total_count == 2


def test_npc_submit_ignored() -> None:
    t = ReadinessTracker()
    t.register("human")
    t.submit("npc_producer")  # не зарегистрирован как человек
    assert not t.all_ready
    assert t.ready_count == 0


def test_reset_clears_submitted_but_keeps_registered() -> None:
    t = ReadinessTracker()
    t.register("a")
    t.submit("a")
    assert t.all_ready
    t.reset()
    assert not t.all_ready
    assert t.total_count == 1  # "a" всё ещё зарегистрирован


def test_unregister_removes_player_from_required() -> None:
    t = ReadinessTracker()
    t.register("a")
    t.register("b")
    t.submit("a")
    assert not t.all_ready
    t.unregister("b")
    assert t.all_ready  # теперь только "a" нужен


def test_submit_idempotent() -> None:
    t = ReadinessTracker()
    t.register("a")
    t.submit("a")
    t.submit("a")
    assert t.ready_count == 1
