# CLAUDE.md — «Цепочка прибыли» (retail-game)

Браузерная мультиплеерная экономическая стратегия про FMCG-рынок: три роли — ритейлер,
производитель, дистрибьютор/логист. Ранняя альфа / вертикальный срез.

## Стек
- Python **3.12+** (локально venv на 3.13: `/opt/homebrew/bin/python3.13`). Системный 3.9 НЕ подходит (нужны `StrEnum`, `X | Y`).
- FastAPI + Pydantic v2, статический фронт `app/static/` (vanilla JS).
- Хранилище: in-memory по умолчанию; опционально JSON-snapshot (`PROFIT_CHAIN_STATE_FILE`) или SQLAlchemy DB-snapshot (`PROFIT_CHAIN_DATABASE_URL`).

## Команды
```bash
source .venv/bin/activate
ruff check .          # линтер (должен быть чистым)
pytest -q             # тесты (должны быть зелёными)
uvicorn app.main:app --reload   # локальный запуск
```
Если venv нет: `/opt/homebrew/bin/python3.13 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`.

## Архитектура
- `app/domain/models.py` — Pydantic-модели (вход/выход API + доменное ядро).
- `app/domain/balance.py` — стартовый баланс мира (регионы, товары, сырьё, рецепты, объекты, форматы магазинов).
- `app/domain/engine.py` — `GameEngine`: вся игровая логика и `close_day()`.
- `app/api/routes.py` — HTTP-эндпоинты (префикс `/api`). Глобальные `_state/_engine/_auth`.
- `tests/` — pytest, по файлу на подсистему.
- `docs/` — `HANDOFF.md` (полный план на 12 этапов), `DEVELOPMENT_STATUS.md` (актуальный статус), `TECHNICAL_SPEC.md`, `ROLE.md`.

## Правила работы (из ROLE.md / ITERATION_PROTOCOL.md)
- Один вертикальный слой за итерацию: модель → баланс → движок → API → тест. Не тащить весь scope сразу.
- Не ломать публичные API без миграционного плана; не удалять эндпоинты просто так.
- Любая фича — с тестом или smoke-проверкой.
- Никаких секретов/паролей/токенов/PII в коде и публичных ответах. `.env`, `.data/` — не коммитить.
- После итерации обновлять `docs/DEVELOPMENT_STATUS.md`.
- Роли управляются объектами `BusinessAsset` (мощность/расходы), а не «магическими» лимитами; движок суммирует мощность и расходы по объектам одного типа.

## Git
Репозиторий: `satamanchuk-star/retail-game`, дефолтная ветка `main`. Коммитить/пушить — только по явной просьбе; на дефолтной ветке сначала создавать ветку.
