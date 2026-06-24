# API Reference прототипа «Цепочка прибыли»

Документ фиксирует текущие API-контракты для передачи разработки. Контракты описывают раннюю альфу и могут расширяться, но существующие endpoint-ы нельзя ломать без миграционного решения.

## Auth

### `POST /api/auth/register`

Регистрирует игрока и возвращает bearer-токен прототипа.

**Body:**

```json
{
  "username": "player_1",
  "password": "password123"
}
```

**201 Response:** `AuthToken`.

Ошибки:

- `400` — имя занято или данные некорректны.

### `POST /api/auth/login`

Авторизует игрока.

**Body:**

```json
{
  "username": "player_1",
  "password": "password123"
}
```

**200 Response:** `AuthToken`.

Ошибки:

- `401` — неверные данные.

### `GET /api/me`

Возвращает текущего игрока.

**Headers:** `Authorization: Bearer <token>`.

**200 Response:** `PublicUser`.

Ошибки:

- `401` — нет валидного токена.

## World state

### `GET /api/state`

Возвращает публичный снимок игрового мира без секретов.

**200 Response:** `PublicGameState`.

### `POST /api/reset`

Сбрасывает мир к стартовому состоянию. Используется для демо и тестов.

**200 Response:** `PublicGameState`.

## Companies and decisions

### `POST /api/companies`

Создаёт компанию. Если передан bearer-токен, компания закрепляется за пользователем.

**Headers:** `Authorization: Bearer <token>` опционально.

**Body:**

```json
{
  "name": "Новая сеть",
  "role": "retailer",
  "region_id": "central"
}
```

**201 Response:** `Company`.

Ошибки:

- `400` — неизвестный регион или некорректные данные.

### `POST /api/decisions/{company_id}`

Сохраняет дневное решение компании.

**Headers:** `Authorization: Bearer <token>` требуется, если компания имеет владельца.

**Body:**

```json
{
  "target_price_index": 1.05,
  "production_units": 1000,
  "logistics_capacity_units": 1000,
  "marketing_budget_rub": 50000,
  "ready": true
}
```

**200 Response:** `CompanyDecision`.

Ошибки:

- `403` — попытка управлять чужой компанией;
- `404` — компания не найдена.

## Assets

### `GET /api/assets`

Возвращает магазины, заводы и склады.

**200 Response:** `list[BusinessAsset]`.

## Contracts

### `POST /api/contracts`

Создаёт контракт между двумя компаниями.

**Headers:** `Authorization: Bearer <token>` требуется, если одна из сторон имеет владельца и текущий пользователь должен владеть хотя бы одной защищённой стороной.

**Body:**

```json
{
  "contract_type": "supply",
  "seller_id": "npc_producer",
  "buyer_id": "player",
  "product_id": "bread",
  "quantity": 500,
  "unit_price_rub": 42,
  "due_day": 2,
  "penalty_rub": 10000
}
```

**201 Response:** `Contract`.

Ошибки:

- `400` — некорректный контракт или банкротство стороны;
- `403` — нет прав на контракт с protected-компанией.

## Day closure

### `POST /api/close-day`

Закрывает игровой день. При повторном `closure_id` возвращает сохранённый результат без повторного расчёта.

**Body:**

```json
{
  "closure_id": "close-2026-06-24-001"
}
```

**200 Response:** `WorldDayResult`.

### `GET /api/day-closures`

Возвращает последние записи журнала закрытия дня.

**200 Response:** `list[DayClosureRecord]`.

### `POST /api/simulate-day/{company_id}`

Legacy endpoint. Закрывает день и возвращает отчёт только по одной компании.

**200 Response:** `DayResult`.

## Demo

### `POST /api/demo/run`

Запускает недельный демо-сценарий.

**200 Response:** `DemoRunResult`.

## Banks and loans

### `GET /api/banks`

Возвращает NPC-банки и условия.

**200 Response:** `list[Bank]`.

### `POST /api/loans`

Выдаёт кредит компании.

**Headers:** `Authorization: Bearer <token>` требуется, если компания имеет владельца.

**Body:**

```json
{
  "company_id": "player",
  "bank_id": "steady_bank",
  "principal_rub": 1000000,
  "term_days": 30
}
```

**201 Response:** `Loan`.

Ошибки:

- `400` — превышен лимит или банк/компания не найдены;
- `403` — попытка взять кредит на чужую компанию.

## Finances

### `GET /api/finances`

Возвращает финансовые отчёты всех компаний.

**200 Response:** `list[FinancialReport]`.

### `GET /api/finances/{company_id}`

Возвращает финансовый отчёт одной компании.

**200 Response:** `FinancialReport`.

Ошибки:

- `404` — компания не найдена.

## Ratings

### `GET /api/ratings`

Возвращает общий и ролевой рейтинг.

**200 Response:** `RatingBoard`.

## Persistence and database status

### `GET /api/persistence`

Возвращает статус JSON snapshot.

**200 Response:** `PersistenceStatus`.

### `GET /api/database/status`

Возвращает публичный статус DB snapshot без раскрытия URL.

**200 Response:** `DatabaseStatus`.

## Project status

### `GET /api/project/status`

Возвращает текущую стадию разработки и roadmap.

**200 Response:** `ProjectStatus`.
