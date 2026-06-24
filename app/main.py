"""FastAPI запускает API и HTML-прототип в одном процессе для быстрого старта."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import initialize_storage, router, shutdown_storage
from app.core.config import settings

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Подготовить место для будущих ресурсов БД, очередей и HTTP-клиентов."""
    app.state.settings = settings
    await initialize_storage()
    try:
        yield
    finally:
        await shutdown_storage()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """Отдать браузерный интерфейс прототипа."""
    return FileResponse(STATIC_DIR / "index.html")
