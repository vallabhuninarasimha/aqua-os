"""Aqua OS API Application Entrypoint.

Modular Monolith backend for aquaculture telemetry ingestion,
20-pond configuration management, and biological safety alerting.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from apps.api.src.config import settings
from apps.api.src.infrastructure.database import (
    SessionLocal,
    init_db,
    seed_beta_farm_if_empty,
    seed_default_hardware_if_empty,
    seed_default_ponds_if_empty,
    seed_default_users_if_empty,
)
from apps.api.src.routes.alerts import router as alerts_router
from apps.api.src.routes.auth import router as auth_router
from apps.api.src.routes.agent import router as agent_router
from apps.api.src.routes.dashboard import router as dashboard_router
from apps.api.src.routes.health import router as health_router
from apps.api.src.routes.ponds import router as ponds_router
from apps.api.src.routes.power import router as power_router
from apps.api.src.routes.production import router as production_router
from apps.api.src.routes.health_records import router as health_records_router
from apps.api.src.routes.simulator import router as simulator_router
from apps.api.src.routes.telemetry import router as telemetry_router
from apps.api.src.routes.water import router as water_router
from apps.api.src.routes.feed_inventory import router as feed_inventory_router
from apps.api.src.routes.feed_plans import router as feed_plans_router
from apps.api.src.routes.expenses import router as expenses_router
from apps.api.src.routes.edge_control import router as edge_control_router
from apps.api.src.routes.finance import router as finance_router
from apps.api.src.routes.sensors import router as sensors_router
from apps.api.src.routes.aerator_status import router as aerator_status_router
from apps.api.src.services.simulator_service import simulator_service


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown hooks."""
    # Startup: Ensure database schema exists and seed default configuration and users
    init_db()
    with SessionLocal() as session:
        seed_default_ponds_if_empty(session, farm_id=settings.default_farm_id)
        seed_default_hardware_if_empty(session, farm_id=settings.default_farm_id)
        seed_beta_farm_if_empty(session)
        seed_default_users_if_empty(session)

    yield
    # Shutdown: Clean up background simulation if active
    simulator_service.stop()


def create_app() -> FastAPI:
    """FastAPI application factory."""
    app = FastAPI(
        title="Aqua OS Platform API",
        description=(
            "AI-powered aquaculture monitoring and automation operating system. "
            "Engineered for 20-pond baseline operation and scalable to multi-farm operations."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Security headers middleware
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    # Configurable CORS origins with credentials enabled only for explicit origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # Register modular routes
    app.include_router(health_router)
    app.include_router(auth_router, prefix=settings.api_prefix)
    app.include_router(agent_router, prefix=settings.api_prefix)
    app.include_router(ponds_router, prefix=settings.api_prefix)
    app.include_router(telemetry_router, prefix=settings.api_prefix)
    app.include_router(dashboard_router, prefix=settings.api_prefix)
    app.include_router(simulator_router, prefix=settings.api_prefix)
    app.include_router(alerts_router, prefix=settings.api_prefix)
    app.include_router(power_router, prefix=settings.api_prefix)
    app.include_router(production_router, prefix=settings.api_prefix)
    app.include_router(health_records_router, prefix=settings.api_prefix)
    app.include_router(water_router, prefix=settings.api_prefix)
    app.include_router(feed_inventory_router, prefix=settings.api_prefix)
    app.include_router(feed_plans_router, prefix=settings.api_prefix)
    app.include_router(expenses_router, prefix=settings.api_prefix)
    app.include_router(edge_control_router, prefix=settings.api_prefix)
    app.include_router(finance_router, prefix=settings.api_prefix)
    app.include_router(sensors_router, prefix=settings.api_prefix)
    app.include_router(aerator_status_router, prefix=settings.api_prefix)

    # Mount static assets and serve dashboard UI
    dashboard_dir = Path(__file__).resolve().parent.parent.parent / "dashboard"
    if dashboard_dir.exists():
        app.mount("/static", StaticFiles(directory=str(dashboard_dir)), name="static")

        @app.get("/", include_in_schema=False)
        async def serve_dashboard():
            return FileResponse(str(dashboard_dir / "index.html"))

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("apps.api.src.main:app", host="0.0.0.0", port=settings.port, reload=True)
