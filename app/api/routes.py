"""HTTP API отделяет интерфейс от симуляции и готовит основу для мультиплеера."""

from typing import Annotated

from app.core.config import settings
from app.domain.auth import AuthService
from app.domain.balance import STORE_FORMATS
from app.domain.demo import run_demo_scenario
from app.domain.engine import GameEngine
from app.domain.models import (
    AuthToken,
    Bank,
    BusinessAsset,
    Company,
    CompanyCreate,
    CompanyDecision,
    Contract,
    ContractCreate,
    DatabaseStatus,
    DayClosureRecord,
    DayClosureRequest,
    DayResult,
    DemoRunResult,
    FinancialReport,
    Loan,
    LoanCreate,
    PersistenceStatus,
    ProjectStatus,
    PublicGameState,
    PublicUser,
    RatingBoard,
    StoreBuildRequest,
    StoreFormatOption,
    User,
    UserLogin,
    UserRegister,
    WorldDayResult,
)
from app.domain.project_status import build_project_status
from app.domain.ratings import build_rating_board
from app.services.database_store import DatabaseSnapshotStore
from app.services.state_store import StateStore
from fastapi import APIRouter, Body, Depends, Header, HTTPException

router = APIRouter(prefix="/api", tags=["game"])

_store = StateStore(settings.state_file_path)
_db_store = DatabaseSnapshotStore(settings.database_url)
_state = _store.load_or_create()
_engine = GameEngine(_state)
_auth = AuthService(_state)


async def initialize_storage() -> None:
    """Подключить DB-снимок в lifespan, не раскрывая URL наружу."""
    global _auth, _engine, _state
    await _db_store.connect()
    if _db_store.engine is None:
        return
    _state = await _db_store.load_or_create()
    _engine = GameEngine(_state)
    _auth = AuthService(_state)


async def shutdown_storage() -> None:
    """Корректно закрыть DB-пул при остановке приложения."""
    await _db_store.close()


async def _save_state() -> None:
    """Сохранить состояние после мутаций рынка, если persistence включён."""
    if _db_store.engine is not None:
        await _db_store.save(_state)
        return
    _store.save(_state)


def _extract_bearer_token(authorization: str | None) -> str | None:
    """Достать bearer-токен без логирования секрета."""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not token:
        return None
    return token


def get_optional_user(authorization: str | None = Header(default=None)) -> User | None:
    """Вернуть пользователя по bearer-токену, если он передан."""
    token = _extract_bearer_token(authorization)
    if token is None:
        return None
    return _auth.get_user_by_token(token)


OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def get_required_user(user: OptionalUser) -> User:
    """Потребовать авторизованного пользователя для личных операций."""
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется вход игрока")
    return user


def _ensure_can_manage_company(company_id: str, user: User | None) -> None:
    """Запретить управление чужой компанией, не ломая старые unowned-компании."""
    company = next((item for item in _state.companies if item.id == company_id), None)
    if company is None:
        raise HTTPException(status_code=404, detail="Компания не найдена")
    if company.owner_user_id is not None and (
        user is None or company.owner_user_id != user.id
    ):
        raise HTTPException(status_code=403, detail="Нельзя управлять чужой компанией")


def _ensure_can_create_contract(
    seller_id: str, buyer_id: str, user: User | None
) -> None:
    """Разрешить контракт, если игрок владеет хотя бы одной защищённой стороной."""
    parties = [item for item in _state.companies if item.id in {seller_id, buyer_id}]
    owned_parties = [item for item in parties if item.owner_user_id is not None]
    if not owned_parties:
        return
    if user is not None and any(
        item.owner_user_id == user.id for item in owned_parties
    ):
        return
    raise HTTPException(
        status_code=403, detail="Нельзя создать контракт без участия своей компании"
    )


@router.get("/state", response_model=PublicGameState)
async def get_state() -> PublicGameState:
    """Вернуть публичный снимок игрового мира без секретов."""
    return _state.to_public()


@router.post("/auth/register", response_model=AuthToken, status_code=201)
async def register_user(payload: UserRegister) -> AuthToken:
    """Зарегистрировать игрока и выдать bearer-токен прототипа."""
    try:
        token = _auth.register(payload)
        await _save_state()
        return token
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/auth/login", response_model=AuthToken)
async def login_user(payload: UserLogin) -> AuthToken:
    """Авторизовать игрока и выдать новый bearer-токен."""
    try:
        token = _auth.login(payload)
        await _save_state()
        return token
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/me", response_model=PublicUser)
async def get_me(user: Annotated[User, Depends(get_required_user)]) -> PublicUser:
    """Вернуть текущего игрока по bearer-токену."""
    return PublicUser(id=user.id, username=user.username)


@router.post("/companies", response_model=Company, status_code=201)
async def create_company(payload: CompanyCreate, user: OptionalUser) -> Company:
    """Создать компанию игрока в выбранной роли и регионе."""
    try:
        company = _engine.create_company(
            payload, owner_user_id=user.id if user else None
        )
        await _save_state()
        return company
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/decisions/{company_id}", response_model=CompanyDecision)
async def set_decision(
    company_id: str,
    payload: CompanyDecision,
    user: OptionalUser,
) -> CompanyDecision:
    """Сохранить решения компании на ближайшее закрытие дня."""
    _ensure_can_manage_company(company_id, user)
    try:
        decision = _engine.set_decision(company_id, payload)
        await _save_state()
        return decision
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/assets", response_model=list[BusinessAsset])
async def get_assets() -> list[BusinessAsset]:
    """Вернуть магазины, заводы и склады компаний."""
    return _state.assets


@router.get("/store-formats", response_model=list[StoreFormatOption])
async def get_store_formats() -> list[StoreFormatOption]:
    """Вернуть доступные форматы магазинов с мощностью и стоимостью постройки."""
    return list(STORE_FORMATS.values())


@router.post(
    "/companies/{company_id}/stores",
    response_model=BusinessAsset,
    status_code=201,
)
async def build_store(
    company_id: str,
    payload: StoreBuildRequest,
    user: OptionalUser,
) -> BusinessAsset:
    """Построить ритейлеру новый магазин выбранного формата за счёт его наличных."""
    _ensure_can_manage_company(company_id, user)
    try:
        asset = _engine.build_store(company_id, payload.store_format, payload.name)
        await _save_state()
        return asset
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/banks", response_model=list[Bank])
async def get_banks() -> list[Bank]:
    """Вернуть NPC-банки и условия кредитования."""
    return _state.banks


@router.post("/loans", response_model=Loan, status_code=201)
async def issue_loan(
    payload: LoanCreate,
    user: OptionalUser,
) -> Loan:
    """Выдать компании кредит от выбранного NPC-банка."""
    _ensure_can_manage_company(payload.company_id, user)
    try:
        loan = _engine.issue_loan(payload)
        await _save_state()
        return loan
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/contracts", response_model=Contract, status_code=201)
async def create_contract(
    payload: ContractCreate,
    user: OptionalUser,
) -> Contract:
    """Создать формальный контракт между двумя компаниями."""
    _ensure_can_create_contract(payload.seller_id, payload.buyer_id, user)
    try:
        contract = _engine.create_contract(payload)
        await _save_state()
        return contract
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/close-day", response_model=WorldDayResult)
async def close_day(
    payload: Annotated[DayClosureRequest | None, Body()] = None,
) -> WorldDayResult:
    """Закрыть день рынка с опциональной защитой от повторного запуска."""
    result = _engine.close_day(payload.closure_id if payload else None)
    await _save_state()
    return result


@router.get("/day-closures", response_model=list[DayClosureRecord])
async def get_day_closures() -> list[DayClosureRecord]:
    """Вернуть журнал закрытий дня для проверки расчётов и дублей."""
    return list(reversed(_state.day_closures[-20:]))


@router.post("/simulate-day/{company_id}", response_model=DayResult)
async def simulate_day(company_id: str) -> DayResult:
    """Закрыть день и вернуть совместимый отчёт по одной компании."""
    if not any(company.id == company_id for company in _state.companies):
        raise HTTPException(status_code=400, detail="Компания не найдена")

    result = _engine.close_day()
    await _save_state()
    report = next(item for item in result.reports if item.company_id == company_id)
    return DayResult(
        day=result.day,
        revenue_rub=report.revenue_rub,
        costs_rub=report.costs_rub,
        profit_rub=report.profit_rub,
        sold_units=report.sold_units,
        news=result.news,
    )


@router.post("/reset", response_model=PublicGameState)
async def reset_state() -> PublicGameState:
    """Сбросить in-memory мир к стартовому состоянию для демо и тестов."""
    global _auth, _engine, _state
    if _db_store.engine is not None:
        _state = await _db_store.reset()
    else:
        _state = _store.reset()
    _engine = GameEngine(_state)
    _auth = AuthService(_state)
    return _state.to_public()


@router.post("/demo/run", response_model=DemoRunResult)
async def run_demo() -> DemoRunResult:
    """Запустить недельный демо-сценарий, чтобы увидеть результат симуляции."""
    result = run_demo_scenario(_state, days=7)
    await _save_state()
    return result


@router.get("/finances", response_model=list[FinancialReport])
async def get_finances() -> list[FinancialReport]:
    """Вернуть финансовые отчёты по всем компаниям рынка."""
    return [_engine.build_financial_report(company.id) for company in _state.companies]


@router.get("/finances/{company_id}", response_model=FinancialReport)
async def get_company_finance(company_id: str) -> FinancialReport:
    """Вернуть P&L, cash-flow и налоговый срез одной компании."""
    try:
        return _engine.build_financial_report(company_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/ratings", response_model=RatingBoard)
async def get_ratings() -> RatingBoard:
    """Вернуть общий и ролевой рейтинг рынка."""
    return build_rating_board(_state)


@router.get("/persistence", response_model=PersistenceStatus)
async def get_persistence_status() -> PersistenceStatus:
    """Показать, включено ли файловое сохранение прототипа."""
    return PersistenceStatus(
        enabled=_store.enabled,
        path=str(_store.path) if _store.path else None,
        day=_state.day,
        companies=len(_state.companies),
        contracts=len(_state.contracts),
        loans=len(_state.loans),
    )


@router.get("/database/status", response_model=DatabaseStatus)
async def get_database_status() -> DatabaseStatus:
    """Показать DB-режим без раскрытия строки подключения."""
    return DatabaseStatus(
        enabled=_db_store.enabled,
        active=_db_store.engine is not None,
        dialect=_db_store.dialect,
        day=_state.day,
        companies=len(_state.companies),
        contracts=len(_state.contracts),
        loans=len(_state.loans),
    )


@router.get("/project/status", response_model=ProjectStatus)
async def get_project_status() -> ProjectStatus:
    """Показать текущую стадию разработки и оставшиеся крупные этапы."""
    return build_project_status()
