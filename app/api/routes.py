"""HTTP API отделяет интерфейс от симуляции и готовит основу для мультиплеера."""

from datetime import UTC, datetime
from typing import Annotated

from app.api.ws_manager import ConnectionManager
from app.core.config import settings
from app.domain.auth import AuthService
from app.domain.balance import FACILITY_FORMATS, STORE_FORMATS
from app.domain.demo import run_demo_scenario
from app.domain.engine import GameEngine, GameOverError
from app.domain.models import (
    AuthToken,
    Bank,
    BusinessAsset,
    Company,
    CompanyCreate,
    CompanyDecision,
    CompanyStatus,
    Contract,
    ContractCreate,
    DatabaseStatus,
    DayClosureRecord,
    DayClosureRequest,
    DayResult,
    DeliveryOrder,
    DeliveryOrderCreate,
    DemoRunResult,
    FacilityBuildRequest,
    FacilityOption,
    FacilityUpgradeRequest,
    FinancialReport,
    GameState,
    GameStatus,
    LeaderboardEntry,
    Loan,
    LoanCreate,
    MarketEvent,
    MarketListing,
    MarketListingCreate,
    MarketPurchaseCreate,
    PersistenceStatus,
    PricePoint,
    ProjectStatus,
    PublicGameState,
    PublicUser,
    RatingBoard,
    SessionCreate,
    SessionInfo,
    StoreBuildRequest,
    StoreFormatOption,
    StoreUpgradeRequest,
    User,
    UserLogin,
    UserRegister,
    WorldDayResult,
)
from app.domain.project_status import build_project_status
from app.domain.ratings import build_rating_board
from app.domain.session_registry import GameSession, SessionRegistry
from app.services.database_store import DatabaseSnapshotStore
from app.services.state_store import StateStore
from fastapi import (
    APIRouter,
    Body,
    Depends,
    Header,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)

router = APIRouter(prefix="/api", tags=["game"])

_store = StateStore(settings.state_file_path)
_db_store = DatabaseSnapshotStore(settings.database_url)
_registry = SessionRegistry()
_ws = ConnectionManager()
_state = _store.load_or_create()
_engine = GameEngine(_state)
_auth = AuthService(_state)
_registry.init_default(_engine)

# Рейтинг лидеров живёт вне игрового состояния и переживает сброс/новую партию.
_leaderboard: list[LeaderboardEntry] = []


def _record_finished_game() -> None:
    """Сохранить результат основной партии в рейтинг лидеров (один раз)."""
    if not _state.game_over:
        return
    standings = _engine.compute_standings()
    winner = next((s for s in standings if s.is_winner), standings[0] if standings else None)
    _leaderboard.insert(
        0,
        LeaderboardEntry(
            game_no=len(_leaderboard) + 1,
            recorded_at=datetime.now(tz=UTC).isoformat(timespec="seconds"),
            days_played=_state.day,
            winner_company_id=winner.company_id if winner else None,
            winner_name=winner.name if winner else None,
            winner_role=winner.role if winner else None,
            winner_cash_rub=winner.cash_rub if winner else 0,
            total_companies=len(_state.companies),
        ),
    )


def _close_global_day(closure_id: str | None) -> WorldDayResult:
    """Закрыть день основной партии: 409 на завершённой игре + запись в зал славы."""
    was_over = _state.game_over
    try:
        result = _engine.close_day(closure_id)
    except GameOverError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if _state.game_over and not was_over:
        _record_finished_game()
    return result


_SEASON_NAMES = {1: "Весна", 2: "Лето", 3: "Осень", 4: "Зима"}


def _build_game_status(state: GameState, engine: GameEngine) -> GameStatus:
    """Собрать публичный статус партии из состояния и движка."""
    winner = next((c for c in state.companies if c.id == state.winner_company_id), None)
    bankrupt_ids = [c.id for c in state.companies if c.status == CompanyStatus.BANKRUPT]
    return GameStatus(
        game_over=state.game_over,
        winner_company_id=state.winner_company_id,
        winner_name=winner.name if winner else None,
        bankrupt_companies=bankrupt_ids,
        season=state.season,
        season_name=_SEASON_NAMES.get(state.season, "Весна"),
        final_standings=engine.compute_standings() if state.game_over else [],
    )


async def initialize_storage() -> None:
    """Подключить DB-снимок в lifespan, не раскрывая URL наружу."""
    global _auth, _engine, _state
    await _db_store.connect()
    if _db_store.engine is None:
        return
    _state = await _db_store.load_or_create()
    _engine = GameEngine(_state)
    _auth = AuthService(_state)
    _registry.init_default(_engine)


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


def _ensure_can_manage_company(
    company_id: str, user: User | None, state: GameState | None = None
) -> None:
    """Запретить управление чужой компанией, не ломая старые unowned-компании."""
    s = state if state is not None else _state
    company = next((item for item in s.companies if item.id == company_id), None)
    if company is None:
        raise HTTPException(status_code=404, detail="Компания не найдена")
    if company.owner_user_id is not None and (
        user is None or company.owner_user_id != user.id
    ):
        raise HTTPException(status_code=403, detail="Нельзя управлять чужой компанией")


def _ensure_can_create_contract(
    seller_id: str, buyer_id: str, user: User | None, state: GameState | None = None
) -> None:
    """Разрешить контракт, если игрок владеет хотя бы одной защищённой стороной."""
    s = state if state is not None else _state
    parties = [item for item in s.companies if item.id in {seller_id, buyer_id}]
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


@router.post(
    "/companies/{company_id}/stores/{asset_id}/upgrade",
    response_model=BusinessAsset,
)
async def upgrade_store(
    company_id: str,
    asset_id: str,
    payload: StoreUpgradeRequest,
    user: OptionalUser,
) -> BusinessAsset:
    """Повысить формат магазина ритейлера, доплатив разницу постройки."""
    _ensure_can_manage_company(company_id, user)
    try:
        asset = _engine.upgrade_store(company_id, asset_id, payload.new_format)
        await _save_state()
        return asset
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/companies/{company_id}/stores/{asset_id}",
    response_model=BusinessAsset,
)
async def close_store(
    company_id: str,
    asset_id: str,
    user: OptionalUser,
) -> BusinessAsset:
    """Закрыть магазин ритейлера с частичным возвратом вложений."""
    _ensure_can_manage_company(company_id, user)
    try:
        asset = _engine.close_store(company_id, asset_id)
        await _save_state()
        return asset
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/facility-formats", response_model=list[FacilityOption])
async def get_facility_formats() -> list[FacilityOption]:
    """Вернуть форматы заводов и складов с мощностью и стоимостью постройки."""
    options: list[FacilityOption] = []
    for presets in FACILITY_FORMATS.values():
        options.extend(presets.values())
    return options


@router.post(
    "/companies/{company_id}/facilities",
    response_model=BusinessAsset,
    status_code=201,
)
async def build_facility(
    company_id: str,
    payload: FacilityBuildRequest,
    user: OptionalUser,
) -> BusinessAsset:
    """Построить производителю завод или дистрибьютору склад за его наличные."""
    _ensure_can_manage_company(company_id, user)
    try:
        asset = _engine.build_facility(company_id, payload.tier, payload.name)
        await _save_state()
        return asset
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/companies/{company_id}/facilities/{asset_id}/upgrade",
    response_model=BusinessAsset,
)
async def upgrade_facility(
    company_id: str,
    asset_id: str,
    payload: FacilityUpgradeRequest,
    user: OptionalUser,
) -> BusinessAsset:
    """Повысить формат завода или склада с доплатой разницы постройки."""
    _ensure_can_manage_company(company_id, user)
    try:
        asset = _engine.upgrade_facility(company_id, asset_id, payload.new_tier)
        await _save_state()
        return asset
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/companies/{company_id}/facilities/{asset_id}",
    response_model=BusinessAsset,
)
async def close_facility(
    company_id: str,
    asset_id: str,
    user: OptionalUser,
) -> BusinessAsset:
    """Закрыть завод или склад с частичным возвратом вложений."""
    _ensure_can_manage_company(company_id, user)
    try:
        asset = _engine.close_facility(company_id, asset_id)
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
    result = _close_global_day(payload.closure_id if payload else None)
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

    result = _close_global_day(None)
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
    _registry.init_default(_engine)
    return _state.to_public()


@router.post("/demo/run", response_model=DemoRunResult)
async def run_demo() -> DemoRunResult:
    """Запустить недельный демо-сценарий, чтобы увидеть результат симуляции."""
    if _state.game_over:
        raise HTTPException(
            status_code=409,
            detail="Партия завершена — сбросьте мир перед запуском демо.",
        )
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


@router.get("/delivery-orders", response_model=list[DeliveryOrder])
async def list_delivery_orders() -> list[DeliveryOrder]:
    """Вернуть все заявки на доставку в глобальном состоянии."""
    return _state.delivery_orders


@router.post("/companies/{company_id}/delivery-orders", response_model=DeliveryOrder, status_code=201)
async def create_delivery_order(
    company_id: str,
    payload: DeliveryOrderCreate,
    user: Annotated[User, Depends(get_required_user)],
) -> DeliveryOrder:
    """Грузоотправитель создаёт заявку на доставку."""
    _ensure_can_manage_company(company_id, user, _state)
    try:
        order = _engine.create_delivery_order(company_id, payload)
        await _save_state()
        return order
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/delivery-orders/{order_id}/accept", response_model=DeliveryOrder)
async def accept_delivery_order(
    order_id: str,
    distributor_company_id: str,
    user: Annotated[User, Depends(get_required_user)],
) -> DeliveryOrder:
    """Дистрибьютор принимает pending-заявку на себя."""
    _ensure_can_manage_company(distributor_company_id, user, _state)
    try:
        order = _engine.accept_delivery_order(order_id, distributor_company_id)
        await _save_state()
        return order
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/delivery-orders/{order_id}", response_model=DeliveryOrder)
async def cancel_delivery_order(
    order_id: str,
    shipper_company_id: str,
    user: Annotated[User, Depends(get_required_user)],
) -> DeliveryOrder:
    """Грузоотправитель отменяет ещё не принятую заявку."""
    _ensure_can_manage_company(shipper_company_id, user, _state)
    try:
        order = _engine.cancel_delivery_order(order_id, shipper_company_id)
        await _save_state()
        return order
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/prices", response_model=list[PricePoint])
async def get_price_history(
    product_id: str | None = None,
    region_id: str | None = None,
) -> list[PricePoint]:
    """Вернуть историю цен с опциональной фильтрацией по товару и региону."""
    pts = _state.price_history
    if product_id:
        pts = [p for p in pts if p.product_id == product_id]
    if region_id:
        pts = [p for p in pts if p.region_id == region_id]
    return pts


@router.get("/market-events", response_model=list[MarketEvent])
async def get_market_events() -> list[MarketEvent]:
    """Вернуть все рыночные события (включая истёкшие)."""
    return _state.market_events


@router.get("/game-status", response_model=GameStatus)
async def get_game_status() -> GameStatus:
    """Текущий статус игры: победитель, банкроты, сезон."""
    return _build_game_status(_state, _engine)


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
async def get_leaderboard() -> list[LeaderboardEntry]:
    """Рейтинг лидеров: результаты завершённых партий (новые сверху)."""
    return _leaderboard


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


# ---------------------------------------------------------------------------
# Session management — мультиплеер: несколько изолированных игровых миров
# ---------------------------------------------------------------------------

def _get_session_or_404(session_id: str) -> GameSession:
    try:
        return _registry.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Сессия '{session_id}' не найдена") from None


@router.get("/sessions", response_model=list[SessionInfo])
async def list_sessions() -> list[SessionInfo]:
    """Вернуть все активные игровые сессии."""
    return [s.to_info() for s in _registry.list_all()]


@router.post("/sessions", response_model=SessionInfo, status_code=201)
async def create_session(payload: SessionCreate) -> SessionInfo:
    """Создать новую изолированную игровую сессию с чистым состоянием мира."""
    session = _registry.create(payload.name)
    return session.to_info()


@router.get("/sessions/{session_id}", response_model=SessionInfo)
async def get_session_info(session_id: str) -> SessionInfo:
    """Вернуть сводку по конкретной сессии."""
    return _get_session_or_404(session_id).to_info()


@router.get("/sessions/{session_id}/state", response_model=PublicGameState)
async def get_session_state(session_id: str) -> PublicGameState:
    """Вернуть публичный снимок игрового мира выбранной сессии."""
    return _get_session_or_404(session_id).state.to_public()


@router.post("/sessions/{session_id}/close-day", response_model=WorldDayResult)
async def session_close_day(
    session_id: str,
    payload: Annotated[DayClosureRequest | None, Body()] = None,
) -> WorldDayResult:
    """Закрыть день в выбранной сессии и оповестить подключённых игроков."""
    session = _get_session_or_404(session_id)
    try:
        result = session.engine.close_day(payload.closure_id if payload else None)
    except GameOverError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.readiness.reset()
    await _ws.broadcast(session_id, {
        "event": "day_closed",
        "day": result.day,
        "news": result.news,
    })
    return result


@router.post("/sessions/{session_id}/reset", response_model=SessionInfo)
async def reset_session(session_id: str) -> SessionInfo:
    """Сбросить выбранную сессию к начальному состоянию."""
    if session_id == SessionRegistry.DEFAULT_ID:
        raise HTTPException(
            status_code=400, detail="Используйте /api/reset для основной сессии"
        )
    session = _get_session_or_404(session_id)
    return _registry.reset_session(session.id).to_info()


@router.delete("/sessions/{session_id}", response_model=SessionInfo)
async def delete_session(session_id: str) -> SessionInfo:
    """Удалить сессию. Основную сессию удалить нельзя."""
    session = _get_session_or_404(session_id)
    info = session.to_info()
    try:
        _registry.delete(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return info


@router.post(
    "/sessions/{session_id}/companies",
    response_model=Company,
    status_code=201,
)
async def session_create_company(
    session_id: str,
    payload: CompanyCreate,
    user: OptionalUser,
) -> Company:
    """Создать компанию в выбранной сессии и зарегистрировать её в трекере."""
    session = _get_session_or_404(session_id)
    try:
        company = session.engine.create_company(
            payload, owner_user_id=user.id if user else None
        )
        if company.owner_user_id:
            session.readiness.register(company.id)
        return company
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/decisions/{company_id}",
    response_model=CompanyDecision,
)
async def session_set_decision(
    session_id: str,
    company_id: str,
    payload: CompanyDecision,
    user: OptionalUser,
) -> CompanyDecision:
    """Отправить решение; если все игроки готовы — день закрывается автоматически."""
    session = _get_session_or_404(session_id)
    _ensure_can_manage_company(company_id, user, session.state)
    try:
        decision = session.engine.set_decision(company_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    session.readiness.submit(company_id)
    ready = session.readiness.ready_count
    total = session.readiness.total_count
    await _ws.broadcast(session_id, {
        "event": "player_submitted",
        "company_id": company_id,
        "ready": ready,
        "total": total,
    })

    if session.readiness.all_ready:
        try:
            result = session.engine.close_day()
        except GameOverError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        session.readiness.reset()
        await _ws.broadcast(session_id, {
            "event": "day_closed",
            "day": result.day,
            "news": result.news,
        })

    return decision


@router.get(
    "/sessions/{session_id}/market",
    response_model=list[MarketListing],
)
async def session_list_market(session_id: str) -> list[MarketListing]:
    """Вернуть все активные лоты на рынке этой сессии."""
    session = _get_session_or_404(session_id)
    return [lst for lst in session.state.market_listings if lst.is_active]


@router.post(
    "/sessions/{session_id}/companies/{company_id}/listings",
    response_model=MarketListing,
    status_code=201,
)
async def session_create_listing(
    session_id: str,
    company_id: str,
    payload: MarketListingCreate,
    user: OptionalUser,
) -> MarketListing:
    """Разместить лот: продавец выставляет товар по заданной цене."""
    session = _get_session_or_404(session_id)
    _ensure_can_manage_company(company_id, user, session.state)
    try:
        return session.engine.create_listing(
            company_id,
            payload.product_id,
            payload.quantity,
            payload.price_rub_per_unit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/sessions/{session_id}/listings/{listing_id}",
    response_model=MarketListing,
)
async def session_cancel_listing(
    session_id: str,
    listing_id: str,
    user: OptionalUser,
) -> MarketListing:
    """Отозвать лот с рынка (только продавец этого лота)."""
    session = _get_session_or_404(session_id)
    try:
        listing = session.engine._require_listing(listing_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _ensure_can_manage_company(listing.seller_id, user, session.state)
    try:
        return session.engine.cancel_listing(listing_id, listing.seller_id)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/listings/{listing_id}/purchase",
    response_model=MarketListing,
)
async def session_purchase_listing(
    session_id: str,
    listing_id: str,
    payload: MarketPurchaseCreate,
    user: OptionalUser,
) -> MarketListing:
    """Купить товар из лота: деньги и товар переходят мгновенно."""
    session = _get_session_or_404(session_id)
    _ensure_can_manage_company(payload.buyer_company_id, user, session.state)
    try:
        _cost, listing = session.engine.purchase_listing(
            listing_id, payload.buyer_company_id, payload.quantity
        )
        return listing
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/prices", response_model=list[PricePoint])
async def session_price_history(
    session_id: str,
    product_id: str | None = None,
    region_id: str | None = None,
) -> list[PricePoint]:
    """История средневзвешенных цен продажи. Фильтры: product_id, region_id."""
    session = _get_session_or_404(session_id)
    pts = session.state.price_history
    if product_id:
        pts = [p for p in pts if p.product_id == product_id]
    if region_id:
        pts = [p for p in pts if p.region_id == region_id]
    return pts


@router.get("/sessions/{session_id}/market-events", response_model=list[MarketEvent])
async def session_market_events(session_id: str) -> list[MarketEvent]:
    """Все рыночные события сессии (активные и истёкшие)."""
    session = _get_session_or_404(session_id)
    return session.state.market_events


@router.get("/sessions/{session_id}/game-status", response_model=GameStatus)
async def session_game_status(session_id: str) -> GameStatus:
    """Текущий статус игровой сессии: победитель, банкроты, сезон."""
    session = _get_session_or_404(session_id)
    return _build_game_status(session.state, session.engine)


@router.get(
    "/sessions/{session_id}/delivery-orders",
    response_model=list[DeliveryOrder],
)
async def session_list_delivery_orders(session_id: str) -> list[DeliveryOrder]:
    """Вернуть все заявки на доставку в сессии."""
    session = _get_session_or_404(session_id)
    return session.state.delivery_orders


@router.post(
    "/sessions/{session_id}/companies/{company_id}/delivery-orders",
    response_model=DeliveryOrder,
    status_code=201,
)
async def session_create_delivery_order(
    session_id: str,
    company_id: str,
    payload: DeliveryOrderCreate,
    user: Annotated[User, Depends(get_required_user)],
) -> DeliveryOrder:
    """Грузоотправитель создаёт заявку на доставку."""
    session = _get_session_or_404(session_id)
    _ensure_can_manage_company(company_id, user, session.state)
    try:
        return session.engine.create_delivery_order(company_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/delivery-orders/{order_id}/accept",
    response_model=DeliveryOrder,
)
async def session_accept_delivery_order(
    session_id: str,
    order_id: str,
    distributor_company_id: str,
    user: Annotated[User, Depends(get_required_user)],
) -> DeliveryOrder:
    """Дистрибьютор принимает pending-заявку на себя."""
    session = _get_session_or_404(session_id)
    _ensure_can_manage_company(distributor_company_id, user, session.state)
    try:
        return session.engine.accept_delivery_order(order_id, distributor_company_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/sessions/{session_id}/delivery-orders/{order_id}",
    response_model=DeliveryOrder,
)
async def session_cancel_delivery_order(
    session_id: str,
    order_id: str,
    shipper_company_id: str,
    user: Annotated[User, Depends(get_required_user)],
) -> DeliveryOrder:
    """Грузоотправитель отменяет ещё не исполненную заявку."""
    session = _get_session_or_404(session_id)
    _ensure_can_manage_company(shipper_company_id, user, session.state)
    try:
        return session.engine.cancel_delivery_order(order_id, shipper_company_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.websocket("/ws/sessions/{session_id}")
async def session_websocket(websocket: WebSocket, session_id: str) -> None:
    """WebSocket: события сессии в реальном времени (day_closed, player_submitted)."""
    try:
        session = _get_session_or_404(session_id)
    except KeyError:
        await websocket.accept()
        await websocket.close(code=4004)
        return

    await _ws.connect(session_id, websocket)
    try:
        await websocket.send_json({
            "event": "connected",
            "session_id": session_id,
            "day": session.state.day,
            "players_ready": session.readiness.ready_count,
            "players_total": session.readiness.total_count,
        })
        while True:
            data = await websocket.receive_json()
            if data.get("action") == "ping":
                await websocket.send_json({"event": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        _ws.disconnect(session_id, websocket)
