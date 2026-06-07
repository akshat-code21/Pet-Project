from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Hedge Fund Intelligence API", env=settings.app_env)
    if settings.scheduler_enabled:
        from jobs.scheduler import start_scheduler
        start_scheduler()
        logger.info("Scheduler started")
    yield
    # Shutdown
    if settings.scheduler_enabled:
        from jobs.scheduler import stop_scheduler
        stop_scheduler()
    logger.info("API shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Hedge Fund Intelligence API",
        version="1.0.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # CORS
    origins = []
    if settings.frontend_url:
        if "," in settings.frontend_url:
            origins.extend([o.strip() for o in settings.frontend_url.split(",") if o.strip()])
        else:
            origins.append(settings.frontend_url)
    
    # Add common local development origins if not already present
    local_origins = ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:3001"]
    for lo in local_origins:
        if lo not in origins:
            origins.append(lo)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    from api.auth import router as auth_router
    from api.investors import router as investors_router
    from api.sources import router as sources_router
    from api.content import router as content_router
    from api.reports import router as reports_router
    from api.alerts import router as alerts_router
    from api.search import router as search_router
    from api.admin import router as admin_router

    prefix = "/api/v1"
    app.include_router(auth_router, prefix=f"{prefix}/auth", tags=["auth"])
    app.include_router(investors_router, prefix=f"{prefix}/investors", tags=["investors"])
    app.include_router(sources_router, prefix=f"{prefix}/investors", tags=["sources"])
    app.include_router(content_router, prefix=f"{prefix}/content", tags=["content"])
    app.include_router(reports_router, prefix=f"{prefix}/reports", tags=["reports"])
    app.include_router(alerts_router, prefix=f"{prefix}/alerts", tags=["alerts"])
    app.include_router(search_router, prefix=f"{prefix}/search", tags=["search"])
    app.include_router(admin_router, prefix=f"{prefix}/admin", tags=["admin"])

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
