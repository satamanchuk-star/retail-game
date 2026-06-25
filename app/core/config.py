"""Конфигурация вынесена из кода, чтобы баланс и окружение менялись безопасно."""

from secrets import token_hex

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime-настройки приложения."""

    app_name: str = "Цепочка прибыли"
    debug: bool = False
    game_day_minutes: int = Field(default=5, ge=3, le=5)
    state_file_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices("PROFIT_CHAIN_STATE_FILE", "PROFIT_CHAIN_STATE_FILE_PATH"),
    )
    database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("PROFIT_CHAIN_DATABASE_URL", "DATABASE_URL"),
    )
    leaderboard_file_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices("PROFIT_CHAIN_LEADERBOARD_FILE"),
    )

    # JWT-авторизация
    jwt_secret_key: str = Field(default_factory=lambda: token_hex(32))
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = Field(default=72, ge=1, le=8760)

    model_config = SettingsConfigDict(env_prefix="PROFIT_CHAIN_", env_file=".env")


settings = Settings()
