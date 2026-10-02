from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.api.admin import router as admin_router
from backend.app.api.errors import register_exception_handlers
from backend.app.core.config import Settings, get_settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine = create_db_engine(runtime_settings.database_url)
        Base.metadata.create_all(engine)
        application.state.engine = engine
        application.state.session_factory = create_session_factory(engine)
        try:
            yield
        finally:
            engine.dispose()

    application = FastAPI(
        title="VeraPolitica",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = runtime_settings
    register_exception_handlers(application)
    application.include_router(admin_router)

    @application.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
