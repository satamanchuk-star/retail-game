"""Статус разработки защищает проект от потери контекста между итерациями."""

from app.domain.project_status import build_project_status
from app.main import app
from fastapi.testclient import TestClient


def test_project_status_has_next_step() -> None:
    status = build_project_status()

    assert status.name == "Цепочка прибыли"
    assert status.progress_percent > 0
    assert any(item.status == "next" for item in status.milestones)
    assert any("PostgreSQL" in item.title for item in status.milestones)


def test_project_status_api() -> None:
    client = TestClient(app)

    response = client.get("/api/project/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Цепочка прибыли"
    assert payload["milestones"]
    assert "current_focus" in payload
