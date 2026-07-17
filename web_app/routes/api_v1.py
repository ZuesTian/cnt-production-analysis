from __future__ import annotations

import hashlib
import secrets
import time
import uuid
import zipfile
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import Settings
from models import AuditEvent, Dataset, ExportArtifact, Job, QualityIssue, utcnow
from schemas_v1 import (
    DatasetSummary,
    ExportRequest,
    FilterOptionsResponse,
    ImportAccepted,
    JobQueryRequest,
    JobStatus,
    OverviewResponse,
    PublishRequest,
    QualityReport,
    SeriesResponse,
)
from services.common import ServiceError, dataset_dict, issue_dict, job_dict, json_dumps
from services.export_service import process_export
from services.import_service import cleanup_expired_temporary, process_import
from services.metrics_service import (
    diagnostics,
    filter_options,
    furnace_detail,
    furnace_ranking,
    overview,
    resolve_dataset,
    trends,
)


router = APIRouter(prefix="/api/v1", tags=["v1"])


class UploadRateLimiter:
    def __init__(self, attempts: int = 5, window_seconds: int = 60):
        self.attempts = attempts
        self.window_seconds = window_seconds
        self.events: dict[str, deque[float]] = defaultdict(deque)
        self.lock = Lock()

    def check(self, client: str) -> None:
        now = time.monotonic()
        with self.lock:
            queue = self.events[client]
            while queue and now - queue[0] > self.window_seconds:
                queue.popleft()
            if len(queue) >= self.attempts:
                raise ServiceError("UPLOAD_RATE_LIMITED", "上传过于频繁，请稍后再试", 429)
            queue.append(now)


def get_session(request: Request):
    session_factory = request.app.state.SessionLocal
    with session_factory() as session:
        yield session


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def workspace(request: Request) -> str:
    return request.state.workspace_id


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _parse_csv(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _verify_signature(path: Path, extension: str) -> None:
    header = path.read_bytes()[:16]
    if extension == ".xlsx":
        if not header.startswith(b"PK"):
            raise ServiceError("FILE_FORMAT_MISMATCH", "文件扩展名与 Excel xlsx 格式不匹配", 415)
        try:
            with zipfile.ZipFile(path) as workbook:
                names = set(workbook.namelist())
                required = {"[Content_Types].xml", "xl/workbook.xml"}
                if not required.issubset(names):
                    raise ServiceError("FILE_FORMAT_MISMATCH", "文件不是有效的 Excel xlsx 工作簿", 415)
                uncompressed_size = sum(item.file_size for item in workbook.infolist())
                if uncompressed_size > 250 * 1024 * 1024:
                    raise ServiceError("FILE_EXPANSION_TOO_LARGE", "Excel 解压后体积超过安全上限", 413)
        except zipfile.BadZipFile as exc:
            raise ServiceError("FILE_FORMAT_MISMATCH", "Excel xlsx 压缩结构无效", 415) from exc
    if extension == ".xls" and not header.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        raise ServiceError("FILE_FORMAT_MISMATCH", "文件扩展名与 Excel xls 格式不匹配", 415)
    if extension == ".csv":
        if b"\x00" in header:
            raise ServiceError("FILE_FORMAT_MISMATCH", "CSV 文件包含二进制内容", 415)
        sample = path.read_bytes()[:8192]
        if not any(delimiter in sample for delimiter in (b",", b";", b"\t")):
            raise ServiceError("FILE_FORMAT_MISMATCH", "无法识别 CSV 分隔符", 415)


def _accessible_dataset(session: Session, dataset_id: str, workspace_id: str) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise ServiceError("DATASET_NOT_FOUND", "数据版本不存在", 404)
    if dataset.kind == "temporary" and dataset.owner_workspace != workspace_id:
        raise ServiceError("DATASET_FORBIDDEN", "无权访问其他会话的临时数据", 403)
    if dataset.kind == "temporary" and dataset.expires_at and dataset.expires_at <= utcnow():
        raise ServiceError("DATASET_EXPIRED", "临时数据已超过 24 小时有效期", 410)
    return dataset


@router.get("/health")
def health(request: Request) -> dict[str, str]:
    return {"status": "ok", "version": request.app.version}


@router.get("/auth/check")
def auth_check() -> dict[str, str]:
    return {"status": "ok"}


@router.post(
    "/datasets/imports",
    response_model=ImportAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_import(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    kind: Annotated[Literal["shared", "temporary"], Form()] = "temporary",
    name: Annotated[str | None, Form()] = None,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    request.app.state.upload_limiter.check(_client_ip(request))
    original_name = Path(file.filename or "data").name
    extension = Path(original_name).suffix.lower()
    if extension not in settings.allowed_extensions:
        raise ServiceError("UNSUPPORTED_FILE_TYPE", "仅支持 .xlsx、.xls 和 .csv 文件", 415)

    dataset_id = uuid.uuid4().hex
    job_id = uuid.uuid4().hex
    stored_path = settings.import_dir / f"{dataset_id}{extension}"
    digest = hashlib.sha256()
    size = 0
    try:
        with stored_path.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise ServiceError("FILE_TOO_LARGE", "文件超过 50MB 限制", 413)
                digest.update(chunk)
                target.write(chunk)
        if size == 0:
            raise ServiceError("EMPTY_FILE", "上传文件为空", 422)
        _verify_signature(stored_path, extension)
    except Exception:
        stored_path.unlink(missing_ok=True)
        raise

    sha256 = digest.hexdigest()
    if kind == "shared":
        duplicate = session.scalar(
            select(Dataset).where(
                Dataset.kind == "shared",
                Dataset.sha256 == sha256,
                Dataset.status.in_(["processing", "ready", "published", "archived"]),
            )
        )
        if duplicate:
            stored_path.unlink(missing_ok=True)
            raise ServiceError(
                "DUPLICATE_SNAPSHOT",
                "相同文件已作为共享快照导入",
                409,
                {"dataset_id": duplicate.id},
            )

    workspace_id = workspace(request)
    expires_at = utcnow() + timedelta(hours=settings.temporary_ttl_hours) if kind == "temporary" else None
    session.add(
        Dataset(
            id=dataset_id,
            kind=kind,
            status="processing",
            name=(name or Path(original_name).stem)[:255],
            original_filename=original_name[:255],
            stored_path=str(stored_path.resolve()),
            sha256=sha256,
            owner_workspace=workspace_id if kind == "temporary" else None,
            expires_at=expires_at,
            quality_status="pending",
        )
    )
    session.add(
        Job(
            id=job_id,
            job_type="dataset_import",
            status="queued",
            phase="queued",
            progress=0,
            message="文件已接收，等待预检",
            dataset_id=dataset_id,
            workspace_id=workspace_id,
        )
    )
    session.commit()
    request.app.state.job_manager.submit(
        job_id,
        process_import,
        request.app.state.SessionLocal,
        settings,
        job_id,
        dataset_id,
        stored_path,
    )
    return {"job_id": job_id, "dataset_id": dataset_id, "status": "queued"}


@router.get("/datasets", response_model=list[DatasetSummary])
def list_datasets(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> list[dict]:
    cleanup_expired_temporary(request.app.state.SessionLocal, request.app.state.settings)
    workspace_id = workspace(request)
    datasets = session.scalars(
        select(Dataset)
        .where(
            or_(
                Dataset.kind == "shared",
                (Dataset.kind == "temporary") & (Dataset.owner_workspace == workspace_id),
            ),
            Dataset.status != "expired",
        )
        .order_by(Dataset.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [dataset_dict(item) for item in datasets]


@router.get("/datasets/{dataset_id}/quality", response_model=QualityReport)
def dataset_quality(
    dataset_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    dataset = _accessible_dataset(session, dataset_id, workspace(request))
    issues = session.scalars(
        select(QualityIssue)
        .where(QualityIssue.dataset_id == dataset_id)
        .order_by(QualityIssue.id)
    ).all()
    return {"dataset": dataset_dict(dataset), "issues": [issue_dict(item) for item in issues]}


def _publish_or_activate(
    request: Request,
    session: Session,
    dataset_id: str,
    payload: PublishRequest,
    action: str,
) -> dict:
    if not payload.confirm:
        raise ServiceError("CONFIRMATION_REQUIRED", "发布或回滚需要二次确认", 422)
    with request.app.state.publish_lock:
        dataset = session.get(Dataset, dataset_id)
        if not dataset or dataset.kind != "shared":
            raise ServiceError("DATASET_NOT_FOUND", "共享数据版本不存在", 404)
        allowed = {"ready"} if action == "publish" else {"archived", "ready"}
        if dataset.status not in allowed:
            raise ServiceError("INVALID_DATASET_STATE", f"当前状态 {dataset.status} 不允许此操作", 409)

        issues = session.scalars(select(QualityIssue).where(QualityIssue.dataset_id == dataset_id)).all()
        critical = [item.code for item in issues if item.severity == "critical"]
        if critical:
            raise ServiceError("QUALITY_BLOCKED", "存在阻断级数据质量问题，不能发布", 409, critical)
        high_codes = sorted({item.code for item in issues if item.severity == "high"})
        missing_ack = sorted(set(high_codes) - set(payload.acknowledged_issue_codes))
        if missing_ack:
            raise ServiceError(
                "QUALITY_ACK_REQUIRED",
                "发布前需确认高等级质量风险",
                422,
                {"issue_codes": missing_ack},
            )

        current = session.scalar(
            select(Dataset).where(Dataset.kind == "shared", Dataset.status == "published")
        )
        previous_id = current.id if current else None
        if current and current.id != dataset.id:
            current.status = "archived"
        dataset_snapshot = dataset_dict(dataset)
        coverage = dataset_snapshot["coverage"]
        manual_lines = {
            line for line, details in coverage.items()
            if not bool(details.get("suggested_verified"))
        }
        missing_manual_confirmation = sorted(manual_lines - set(payload.complete_dates))
        if missing_manual_confirmation:
            raise ServiceError(
                "MANUAL_COMPLETE_DATE_REQUIRED",
                "历史不足 7 天的生产线必须人工确认完整日",
                422,
                {"production_lines": missing_manual_confirmation},
            )
        complete_dates = dict(dataset_snapshot["complete_dates"])
        complete_dates.update({key: value.isoformat() for key, value in payload.complete_dates.items()})
        configured_lines = set(coverage.keys())
        if configured_lines - set(complete_dates):
            raise ServiceError(
                "COMPLETE_DATE_REQUIRED",
                "每条生产线都必须确认最新完整日",
                422,
                {"production_lines": sorted(configured_lines - set(complete_dates))},
            )
        # The database enforces one published shared snapshot. Flush the previous
        # version's archive transition before promoting the next version so the
        # unique partial index is never transiently violated.
        if current and current.id != dataset.id:
            session.flush()
        dataset.complete_dates_json = json_dumps(complete_dates)
        dataset.status = "published"
        dataset.published_at = utcnow()
        session.add(
            AuditEvent(
                action=action,
                dataset_id=dataset.id,
                previous_dataset_id=previous_id,
                client_ip=_client_ip(request),
                metadata_json=json_dumps(
                    {
                        "sha256": dataset.sha256,
                        "complete_dates": complete_dates,
                        "acknowledged_issue_codes": payload.acknowledged_issue_codes,
                    }
                ),
            )
        )
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ServiceError(
                "PUBLISH_CONFLICT",
                "另一个发布操作已先完成，请刷新版本列表后重试",
                409,
            ) from exc
        session.refresh(dataset)
        return dataset_dict(dataset)


@router.post("/datasets/{dataset_id}/publish", response_model=DatasetSummary)
def publish_dataset(
    dataset_id: str,
    payload: PublishRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    return _publish_or_activate(request, session, dataset_id, payload, "publish")


@router.post("/datasets/{dataset_id}/activate", response_model=DatasetSummary)
def activate_dataset(
    dataset_id: str,
    payload: PublishRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    return _publish_or_activate(request, session, dataset_id, payload, "activate")


@router.get("/filters", response_model=FilterOptionsResponse)
def filters(
    request: Request,
    dataset_id: str | None = None,
    session: Session = Depends(get_session),
) -> dict:
    dataset = resolve_dataset(session, dataset_id, workspace(request))
    options = filter_options(session, dataset)
    return {
        "dataset": dataset_dict(dataset),
        "scope": {
            "dataset_id": dataset.id,
            "grain": "furnace_day",
            "date_from": options.get("date_min"),
            "date_to": options.get("date_max"),
        },
        **options,
    }


@router.get("/dashboard/overview", response_model=OverviewResponse)
def dashboard_overview(
    request: Request,
    dataset_id: str | None = None,
    grain: Literal["shift", "furnace_day"] = "furnace_day",
    production_lines: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    session: Session = Depends(get_session),
) -> dict:
    dataset = resolve_dataset(session, dataset_id, workspace(request))
    lines, _, start, end = _scope_query(production_lines, None, date_from, date_to)
    return overview(session, dataset, lines, start, end)


def _scope_query(
    production_lines: str | None,
    furnaces: str | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[list[str], list[str], object, object]:
    try:
        start = datetime.fromisoformat(date_from).date() if date_from else None
        end = datetime.fromisoformat(date_to).date() if date_to else None
    except ValueError as exc:
        raise ServiceError("INVALID_DATE", "日期参数必须使用 YYYY-MM-DD", 422) from exc
    if start and end and start > end:
        raise ServiceError("INVALID_DATE_RANGE", "开始日期不能晚于结束日期", 422)
    return _parse_csv(production_lines), _parse_csv(furnaces), start, end


@router.get("/dashboard/trends", response_model=SeriesResponse)
def dashboard_trends(
    request: Request,
    dataset_id: str | None = None,
    grain: Literal["shift", "furnace_day"] = "furnace_day",
    production_lines: str | None = None,
    furnaces: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    session: Session = Depends(get_session),
) -> dict:
    dataset = resolve_dataset(session, dataset_id, workspace(request))
    lines, selected_furnaces, start, end = _scope_query(production_lines, furnaces, date_from, date_to)
    return trends(session, dataset, grain, lines, selected_furnaces, start, end)


@router.get("/furnaces/ranking", response_model=SeriesResponse)
def ranking(
    request: Request,
    dataset_id: str | None = None,
    grain: Literal["shift", "furnace_day"] = "furnace_day",
    production_lines: str | None = None,
    furnaces: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    metric: str = "weighted_yield",
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> dict:
    dataset = resolve_dataset(session, dataset_id, workspace(request))
    lines, selected_furnaces, start, end = _scope_query(production_lines, furnaces, date_from, date_to)
    return furnace_ranking(session, dataset, grain, lines, selected_furnaces, start, end, metric, limit)


@router.get("/furnaces/{furnace_id}", response_model=SeriesResponse)
def furnace(
    furnace_id: str,
    request: Request,
    dataset_id: str | None = None,
    grain: Literal["shift", "furnace_day"] = "furnace_day",
    date_from: str | None = None,
    date_to: str | None = None,
    session: Session = Depends(get_session),
) -> dict:
    dataset = resolve_dataset(session, dataset_id, workspace(request))
    _, _, start, end = _scope_query(None, None, date_from, date_to)
    return furnace_detail(session, dataset, furnace_id, grain, start, end)


@router.get("/diagnostics/{kind}", response_model=SeriesResponse)
def diagnostic(
    kind: str,
    request: Request,
    dataset_id: str | None = None,
    grain: Literal["shift", "furnace_day"] = "furnace_day",
    production_lines: str | None = None,
    furnaces: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    session: Session = Depends(get_session),
) -> dict:
    dataset = resolve_dataset(session, dataset_id, workspace(request))
    lines, selected_furnaces, start, end = _scope_query(production_lines, furnaces, date_from, date_to)
    return diagnostics(session, dataset, kind, grain, lines, selected_furnaces, start, end)


@router.get("/jobs", response_model=list[JobStatus])
def list_jobs(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[dict]:
    workspace_id = workspace(request)
    jobs = session.scalars(
        select(Job)
        .where(or_(Job.workspace_id == workspace_id, Job.workspace_id.is_(None)))
        .order_by(Job.created_at.desc())
        .limit(limit)
    ).all()
    return [job_dict(item) for item in jobs]


@router.post("/jobs", response_model=list[JobStatus])
def query_jobs(
    payload: JobQueryRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> list[dict]:
    """Return a bounded job batch for clients polling several background tasks."""
    workspace_id = workspace(request)
    jobs = session.scalars(
        select(Job)
        .where(
            Job.id.in_(payload.ids),
            or_(Job.workspace_id == workspace_id, Job.workspace_id.is_(None)),
        )
        .order_by(Job.created_at.desc())
    ).all()
    return [job_dict(item) for item in jobs]


@router.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(
    job_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    job = session.get(Job, job_id)
    if not job or (job.workspace_id and job.workspace_id != workspace(request)):
        raise ServiceError("JOB_NOT_FOUND", "作业不存在", 404)
    return job_dict(job)


@router.post("/exports", response_model=ImportAccepted, status_code=status.HTTP_202_ACCEPTED)
def create_export(
    payload: ExportRequest,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    dataset = resolve_dataset(session, payload.dataset_id, workspace(request))
    job_id = uuid.uuid4().hex
    session.add(
        Job(
            id=job_id,
            job_type="export",
            status="queued",
            phase="queued",
            progress=0,
            message="报表作业已排队",
            dataset_id=dataset.id,
            workspace_id=workspace(request),
        )
    )
    session.commit()
    filters_payload = {
        "production_lines": payload.production_lines,
        "furnaces": payload.furnaces,
        "date_from": payload.date_from.isoformat() if payload.date_from else None,
        "date_to": payload.date_to.isoformat() if payload.date_to else None,
    }
    request.app.state.job_manager.submit(
        job_id,
        process_export,
        request.app.state.SessionLocal,
        settings,
        job_id,
        dataset.id,
        payload.report_type,
        filters_payload,
    )
    return {"job_id": job_id, "dataset_id": dataset.id, "status": "queued"}


@router.get("/exports")
def list_exports(
    request: Request,
    session: Session = Depends(get_session),
) -> list[dict]:
    artifacts = session.scalars(select(ExportArtifact).order_by(ExportArtifact.created_at.desc()).limit(100)).all()
    result: list[dict] = []
    for artifact in artifacts:
        try:
            _accessible_dataset(session, artifact.dataset_id, workspace(request))
        except ServiceError:
            continue
        result.append(
            {
                "id": artifact.id,
                "dataset_id": artifact.dataset_id,
                "report_type": artifact.report_type,
                "filename": artifact.filename,
                "size": artifact.size,
                "created_at": artifact.created_at,
            }
        )
    return result


@router.get("/exports/{export_id}/download")
def download_export(
    export_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> FileResponse:
    artifact = session.get(ExportArtifact, export_id)
    if not artifact:
        raise ServiceError("EXPORT_NOT_FOUND", "导出文件不存在", 404)
    _accessible_dataset(session, artifact.dataset_id, workspace(request))
    path = Path(artifact.stored_path).resolve()
    root = request.app.state.settings.export_dir.resolve()
    if root not in path.parents or not path.is_file():
        raise ServiceError("EXPORT_FILE_MISSING", "导出文件已失效", 410)
    return FileResponse(path, filename=artifact.filename)
