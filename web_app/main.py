from __future__ import annotations

import logging
import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse


WEB_APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_APP_DIR.parent
for item in (PROJECT_ROOT, WEB_APP_DIR):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import analysis
from config import build_settings
from database import create_database, migrate_database
from models import Dataset
from routes.api_v1 import UploadRateLimiter, router as api_v1_router
from services.common import ServiceError
from services.import_service import cleanup_expired_temporary
from services.job_manager import JobManager
from services.metrics_service import load_records
from sqlalchemy import select


logger = logging.getLogger(__name__)


CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)


def create_app(data_dir: str | Path | None = None, *, serve_frontend: bool = True) -> FastAPI:
    settings = build_settings(data_dir)
    migrate_database(settings.database_path)
    engine, session_factory = create_database(settings.database_path)
    manager = JobManager(session_factory)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        analysis.configure_chinese_fonts()
        manager.recover_interrupted_jobs()
        cleanup_expired_temporary(session_factory, settings)
        with session_factory() as session:
            active_dataset = session.scalar(
                select(Dataset).where(Dataset.kind == "shared", Dataset.status == "published")
            )
            if active_dataset:
                load_records(session, active_dataset.id)
        yield
        manager.shutdown()
        engine.dispose()

    app = FastAPI(
        title="碳纳米管生产数据分析工作台",
        version="2.0.0",
        description="厂内离线数据版本、质量门禁与双粒度生产分析 API",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.SessionLocal = session_factory
    app.state.job_manager = manager
    app.state.publish_lock = Lock()
    app.state.upload_limiter = UploadRateLimiter()

    @app.middleware("http")
    async def security_and_workspace(request: Request, call_next):
        workspace_id = request.cookies.get("cnt_workspace")
        created = False
        if not workspace_id or len(workspace_id) < 24:
            workspace_id = secrets.token_urlsafe(32)
            created = True
        request.state.workspace_id = workspace_id
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if created:
            response.set_cookie(
                "cnt_workspace",
                workspace_id,
                max_age=60 * 60 * 24 * 30,
                httponly=True,
                samesite="lax",
                secure=False,
                path="/",
            )
        return response

    @app.exception_handler(ServiceError)
    async def service_error_handler(_request: Request, exc: ServiceError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message, "details": exc.details},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"code": "VALIDATION_ERROR", "message": "请求参数不符合要求", "details": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def internal_error_handler(request: Request, exc: Exception):
        logger.error(
            "Unhandled request error: %s %s",
            request.method,
            request.url.path,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return JSONResponse(
            status_code=500,
            content={"code": "INTERNAL_ERROR", "message": "服务器处理请求时发生错误", "details": None},
        )

    app.include_router(api_v1_router)

    if serve_frontend and settings.frontend_dist.is_dir():
        app.frontend("/", directory=settings.frontend_dist, fallback="index.html")
    elif serve_frontend:
        @app.get("/", include_in_schema=False)
        def frontend_not_built() -> HTMLResponse:
            return HTMLResponse(
                "<main style='font:16px system-ui;padding:40px'>"
                "<h1>前端尚未构建</h1><p>请在 web_app/frontend 运行 npm install && npm run build。</p>"
                "</main>",
                status_code=503,
            )

    return app


app = create_app()
