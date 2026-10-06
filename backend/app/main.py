from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from backend.app.api.admin import router as admin_router
from backend.app.api.errors import register_exception_handlers
from backend.app.api.public import router as public_router
from backend.app.core.config import Settings, get_settings
from backend.app.core.logging import configure_logging
from backend.app.core.middleware import RequestContextMiddleware
from backend.app.db.schema import prepare_runtime_schema, readiness_payload, schema_health
from backend.app.db.session import create_db_engine, create_session_factory


DEMO_UI_DIRECTORY = Path(__file__).resolve().parents[2] / "frontend" / "demo"
PUBLIC_UI_DIRECTORY = Path(__file__).resolve().parents[2] / "frontend" / "app"


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or get_settings()
    configure_logging(runtime_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine = create_db_engine(
            runtime_settings.database_url,
            pool_size=runtime_settings.db_pool_size,
            max_overflow=runtime_settings.db_max_overflow,
            pool_timeout=runtime_settings.db_pool_timeout,
            pool_recycle=runtime_settings.db_pool_recycle,
        )
        prepare_runtime_schema(engine, runtime_settings)
        application.state.engine = engine
        application.state.session_factory = create_session_factory(engine)
        try:
            yield
        finally:
            engine.dispose()

    application = FastAPI(
        title="VeraPolitica",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if runtime_settings.api_docs_enabled else None,
        redoc_url="/redoc" if runtime_settings.api_docs_enabled else None,
        openapi_url="/openapi.json" if runtime_settings.api_docs_enabled else None,
    )
    application.state.settings = runtime_settings
    application.add_middleware(RequestContextMiddleware)
    if runtime_settings.cors_origin_list:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(runtime_settings.cors_origin_list),
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )
    if runtime_settings.trusted_host_list:
        application.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=list(runtime_settings.trusted_host_list),
        )
    if runtime_settings.forwarded_allow_ip_list:
        application.add_middleware(
            ProxyHeadersMiddleware,
            trusted_hosts=",".join(runtime_settings.forwarded_allow_ip_list),
        )
    register_exception_handlers(application)
    application.include_router(public_router)
    application.include_router(admin_router)
    if runtime_settings.demo_ui_enabled:
        application.mount(
            "/demo",
            StaticFiles(directory=DEMO_UI_DIRECTORY, html=True),
            name="demo-ui",
        )
    application.mount(
        "/app",
        StaticFiles(directory=PUBLIC_UI_DIRECTORY, html=True),
        name="public-ui",
    )

    @application.get("/health", tags=["health"])
    def health() -> dict[str, object]:
        engine = getattr(application.state, "engine", None)
        if engine is None:
            return {
                "status": "degraded",
                "database": "error",
                "dialect": "unknown",
                "schema_revision": None,
                "schema_head": None,
                "schema_current": False,
                "scheduler_enabled": runtime_settings.scheduler_enabled,
            }
        return schema_health(engine, runtime_settings)

    @application.get("/health/live", tags=["health"])
    def liveness() -> dict[str, object]:
        return {"status": "ok"}

    @application.get("/health/ready", tags=["health"])
    def readiness(response: Response) -> dict[str, object]:
        engine = getattr(application.state, "engine", None)
        if engine is None:
            response.status_code = 503
            return {"status": "not_ready", "ready": False, "database": "error"}
        ready, payload = readiness_payload(engine, runtime_settings)
        if not ready:
            response.status_code = 503
        return payload

    return application


app = create_app()
