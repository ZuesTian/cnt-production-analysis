from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Any

import numpy as np


class ServiceError(Exception):
    """Domain error that can be translated into a stable API response."""

    def __init__(self, code: str, message: str, status_code: int = 400, details: Any | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
import pandas as pd

from models import Dataset, Job, QualityIssue


def json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=json_default)


def json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def finite_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def dataset_dict(dataset: Dataset) -> dict[str, Any]:
    return {
        "id": dataset.id,
        "kind": dataset.kind,
        "status": dataset.status,
        "name": dataset.name,
        "original_filename": dataset.original_filename,
        "created_at": dataset.created_at,
        "published_at": dataset.published_at,
        "expires_at": dataset.expires_at,
        "row_count": dataset.row_count,
        "valid_production_count": dataset.valid_production_count,
        "furnace_count": dataset.furnace_count,
        "date_min": dataset.date_min,
        "date_max": dataset.date_max,
        "quality_status": dataset.quality_status,
        "complete_dates": json_loads(dataset.complete_dates_json, {}),
        "coverage": json_loads(dataset.coverage_json, {}),
    }


def issue_dict(issue: QualityIssue) -> dict[str, Any]:
    return {
        "code": issue.code,
        "severity": issue.severity,
        "title": issue.title,
        "description": issue.description,
        "affected_count": issue.affected_count,
        "affected_rate": issue.affected_rate,
        "details": json_loads(issue.details_json, {}),
    }


def job_dict(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "phase": job.phase,
        "progress": job.progress,
        "message": job.message,
        "dataset_id": job.dataset_id,
        "result": json_loads(job.result_json, {}),
        "error_code": job.error_code,
        "error_detail": job.error_detail,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }
