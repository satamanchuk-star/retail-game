"""Аутентификация нужна прототипу, чтобы игрок не управлял чужой компанией."""

from datetime import UTC, datetime, timedelta
from hashlib import pbkdf2_hmac
from hmac import compare_digest
from secrets import token_hex
from uuid import uuid4

import jwt
from app.core.config import settings
from app.domain.models import (
    AuthToken,
    GameState,
    PublicUser,
    User,
    UserLogin,
    UserRegister,
)

_HASH_ITERATIONS = 200_000


def _hash_password(password: str, salt: str | None = None) -> str:
    """Сформировать salted PBKDF2-хеш без внешних зависимостей."""
    salt = salt or token_hex(16)
    digest = pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _HASH_ITERATIONS
    )
    return f"pbkdf2_sha256${_HASH_ITERATIONS}${salt}${digest.hex()}"


def _verify_password(password: str, password_hash: str) -> bool:
    """Проверить пароль через constant-time сравнение."""
    try:
        algorithm, iterations, salt, _digest = password_hash.split("$", maxsplit=3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256" or int(iterations) != _HASH_ITERATIONS:
        return False
    return compare_digest(_hash_password(password, salt), password_hash)


def _encode_jwt(user_id: str, session_id: str | None = None) -> str:
    """Создать подписанный JWT с exp и опциональным session_id."""
    now = datetime.now(tz=UTC)
    payload: dict = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_expire_hours),
    }
    if session_id is not None:
        payload["session_id"] = session_id
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_jwt(token: str) -> dict | None:
    """Декодировать и проверить JWT. Возвращает payload или None при ошибке."""
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError:
        return None


class AuthService:
    """Минимальный сервис пользователей поверх текущего GameState."""

    def __init__(self, state: GameState) -> None:
        self.state = state

    def register(self, payload: UserRegister) -> AuthToken:
        """Создать пользователя и сразу выдать JWT."""
        if self._find_by_username(payload.username) is not None:
            raise ValueError("Пользователь с таким именем уже существует")
        user = User(
            id=f"user_{uuid4().hex[:10]}",
            username=payload.username,
            password_hash=_hash_password(payload.password),
        )
        self.state.users.append(user)
        return self._create_token(user)

    def login(self, payload: UserLogin) -> AuthToken:
        """Выдать JWT существующему пользователю."""
        user = self._find_by_username(payload.username)
        if user is None or not _verify_password(payload.password, user.password_hash):
            raise ValueError("Неверное имя пользователя или пароль")
        return self._create_token(user)

    def get_user_by_token(self, token: str) -> User | None:
        """Найти пользователя по JWT (проверяет подпись и срок действия)."""
        payload = decode_jwt(token)
        if payload is None:
            return None
        user_id = payload.get("sub")
        if not user_id:
            return None
        # Поддержка legacy random-токенов (ещё хранятся в state.sessions)
        if user_id not in {u.id for u in self.state.users}:
            legacy_id = self.state.sessions.get(token)
            if legacy_id is None:
                return None
            user_id = legacy_id
        return next((u for u in self.state.users if u.id == user_id), None)

    def _create_token(self, user: User) -> AuthToken:
        token = _encode_jwt(user.id)
        return AuthToken(access_token=token, user=PublicUser(id=user.id, username=user.username))

    def _find_by_username(self, username: str) -> User | None:
        normalized = username.casefold()
        return next(
            (u for u in self.state.users if u.username.casefold() == normalized), None
        )
