"""Аутентификация нужна прототипу, чтобы игрок не управлял чужой компанией."""

from hashlib import pbkdf2_hmac
from hmac import compare_digest
from secrets import token_hex
from uuid import uuid4

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
    digest = pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _HASH_ITERATIONS)
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


class AuthService:
    """Минимальный сервис пользователей поверх текущего GameState."""

    def __init__(self, state: GameState) -> None:
        self.state = state

    def register(self, payload: UserRegister) -> AuthToken:
        """Создать пользователя и сразу выдать bearer-токен."""
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
        """Выдать bearer-токен существующему пользователю."""
        user = self._find_by_username(payload.username)
        if user is None or not _verify_password(payload.password, user.password_hash):
            raise ValueError("Неверное имя пользователя или пароль")
        return self._create_token(user)

    def get_user_by_token(self, token: str) -> User | None:
        """Найти пользователя по bearer-токену прототипа."""
        user_id = self.state.sessions.get(token)
        if user_id is None:
            return None
        return next((user for user in self.state.users if user.id == user_id), None)

    def _create_token(self, user: User) -> AuthToken:
        token = token_hex(32)
        self.state.sessions[token] = user.id
        return AuthToken(access_token=token, user=PublicUser(id=user.id, username=user.username))

    def _find_by_username(self, username: str) -> User | None:
        normalized = username.casefold()
        return next((user for user in self.state.users if user.username.casefold() == normalized), None)
