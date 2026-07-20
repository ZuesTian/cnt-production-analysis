from __future__ import annotations

import logging
import re
import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse


WEB_APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_APP_DIR.parent
for item in (PROJECT_ROOT, WEB_APP_DIR):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import analysis
from auth import AuthManager, InvalidSessionError
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
WORKSPACE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{24,64}$")


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
    auth_manager = AuthManager.from_settings(settings)

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
    app.state.auth_manager = auth_manager

    @app.middleware("http")
    async def security_and_workspace(request: Request, call_next):
        request.state.auth_user = None
        workspace_header = request.headers.get("X-CNT-Workspace", "")
        workspace_id = workspace_header if WORKSPACE_PATTERN.fullmatch(workspace_header) else None
        if not workspace_id:
            workspace_id = request.cookies.get("cnt_workspace")
        created = False
        if not workspace_id or len(workspace_id) < 24:
            workspace_id = secrets.token_urlsafe(32)
            created = True
        request.state.workspace_id = workspace_id

        public_api_paths = {"/api/v1/health", "/api/v1/auth/login"}
        protected_api = request.url.path.startswith("/api/v1/") and request.url.path not in public_api_paths
        if auth_manager and protected_api and request.method != "OPTIONS":
            scheme, _, supplied_token = request.headers.get("Authorization", "").partition(" ")
            if scheme.lower() != "bearer" or not supplied_token:
                return JSONResponse(
                    status_code=401,
                    content={"code": "AUTH_REQUIRED", "message": "请先登录后再访问生产数据", "details": None},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            try:
                request.state.auth_user = auth_manager.verify_token(supplied_token)
            except InvalidSessionError:
                return JSONResponse(
                    status_code=401,
                    content={"code": "AUTH_INVALID", "message": "登录已失效，请重新登录", "details": None},
                    headers={"WWW-Authenticate": "Bearer"},
                )
        elif settings.api_token and protected_api and request.method != "OPTIONS":
            scheme, _, supplied_token = request.headers.get("Authorization", "").partition(" ")
            if not (
                scheme.lower() == "bearer"
                and secrets.compare_digest(supplied_token, settings.api_token)
            ):
                return JSONResponse(
                    status_code=401,
                    content={"code": "AUTH_REQUIRED", "message": "需要有效的生产数据访问密钥", "details": None},
                    headers={"WWW-Authenticate": "Bearer"},
                )

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

    if settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.allowed_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-CNT-Workspace"],
            expose_headers=["Content-Disposition"],
            max_age=3600,
        )

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
