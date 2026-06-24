"""Тесты JWT-авторизации."""

import time
from datetime import UTC

import jwt
from app.core.config import settings
from app.domain.auth import AuthService, _encode_jwt, decode_jwt
from app.domain.engine import build_initial_state
from app.domain.models import UserLogin, UserRegister
from app.main import app
from fastapi.testclient import TestClient


def _auth_service() -> AuthService:
    return AuthService(build_initial_state())


# ── Базовый JWT ──────────────────────────────────────────────────────────────

def test_register_returns_jwt():
    """register() возвращает корректный JWT вместо random-токена."""
    svc = _auth_service()
    token_resp = svc.register(UserRegister(username="alice", password="password123"))
    payload = decode_jwt(token_resp.access_token)
    assert payload is not None
    assert payload["sub"].startswith("user_")


def test_jwt_contains_exp_claim():
    """JWT содержит claim exp (время истечения)."""
    svc = _auth_service()
    resp = svc.register(UserRegister(username="bob", password="password123"))
    payload = decode_jwt(resp.access_token)
    assert "exp" in payload
    assert payload["exp"] > time.time()


def test_jwt_expires_after_configured_hours():
    """exp отличается от iat на jwt_expire_hours часов."""
    svc = _auth_service()
    resp = svc.register(UserRegister(username="carol", password="password123"))
    payload = decode_jwt(resp.access_token)
    delta = payload["exp"] - payload["iat"]
    assert abs(delta - settings.jwt_expire_hours * 3600) < 5


def test_get_user_by_valid_token():
    """get_user_by_token возвращает пользователя по валидному JWT."""
    svc = _auth_service()
    resp = svc.register(UserRegister(username="dave", password="password123"))
    user = svc.get_user_by_token(resp.access_token)
    assert user is not None
    assert user.username == "dave"


def test_get_user_by_invalid_token_returns_none():
    """Мусорный токен возвращает None."""
    svc = _auth_service()
    assert svc.get_user_by_token("not.a.jwt") is None


def test_get_user_by_expired_token_returns_none():
    """Истёкший JWT возвращает None (PyJWT проверяет exp)."""
    svc = _auth_service()
    svc.register(UserRegister(username="eve", password="password123"))
    user_id = svc.state.users[-1].id

    # Создаём уже истёкший токен (exp в прошлом)
    from datetime import datetime, timedelta
    expired_payload = {
        "sub": user_id,
        "iat": datetime.now(tz=UTC) - timedelta(hours=2),
        "exp": datetime.now(tz=UTC) - timedelta(hours=1),
    }
    expired_token = jwt.encode(
        expired_payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )
    assert svc.get_user_by_token(expired_token) is None


def test_get_user_by_wrong_signature_returns_none():
    """JWT подписанный другим ключом отклоняется."""
    svc = _auth_service()
    token = jwt.encode({"sub": "user_fake"}, "wrong_secret", algorithm="HS256")
    assert svc.get_user_by_token(token) is None


def test_login_returns_jwt():
    """login() тоже выдаёт JWT."""
    svc = _auth_service()
    svc.register(UserRegister(username="frank", password="password123"))
    resp = svc.login(UserLogin(username="frank", password="password123"))
    assert decode_jwt(resp.access_token) is not None


def test_jwt_with_session_id_claim():
    """JWT может содержать session_id claim."""
    token = _encode_jwt("user_123", session_id="sess_abc")
    payload = decode_jwt(token)
    assert payload is not None
    assert payload["session_id"] == "sess_abc"
    assert payload["sub"] == "user_123"


# ── Интеграция с HTTP ────────────────────────────────────────────────────────

def test_protected_endpoint_rejects_missing_token():
    """/api/me без токена возвращает 401/403."""
    client = TestClient(app)
    resp = client.get("/api/me")
    assert resp.status_code in (401, 403)


def test_protected_endpoint_accepts_jwt():
    """/api/me с JWT возвращает данные пользователя."""
    client = TestClient(app)
    client.post("/api/reset")
    reg = client.post(
        "/api/auth/register",
        json={"username": "grace", "password": "password123"},
    )
    token = reg.json()["access_token"]

    me = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "grace"


def test_protected_endpoint_rejects_expired_jwt():
    """/api/me с истёкшим JWT возвращает 401/403."""
    from datetime import datetime, timedelta
    expired_token = jwt.encode(
        {
            "sub": "user_fake",
            "exp": datetime.now(tz=UTC) - timedelta(hours=1),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    client = TestClient(app)
    resp = client.get("/api/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code in (401, 403)
