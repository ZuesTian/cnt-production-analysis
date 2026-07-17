from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


Grain = Literal["shift", "furnace_day"]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None


class DatasetSummary(BaseModel):
    id: str
    kind: Literal["shared", "temporary"]
    status: str
    name: str
    original_filename: str
    created_at: datetime
    published_at: datetime | None = None
    expires_at: datetime | None = None
    row_count: int
    valid_production_count: int
    furnace_count: int
    date_min: date | None = None
    date_max: date | None = None
    quality_status: str
    complete_dates: dict[str, str] = Field(default_factory=dict)
    coverage: dict[str, Any] = Field(default_factory=dict)


class QualityIssueBody(BaseModel):
    code: str
    severity: Literal["critical", "high", "medium", "low", "info"]
    title: str
    description: str
    affected_count: int
    affected_rate: float
    details: dict[str, Any] = Field(default_factory=dict)


class QualityReport(BaseModel):
    dataset: DatasetSummary
    issues: list[QualityIssueBody]


class ImportAccepted(BaseModel):
    job_id: str
    dataset_id: str
    status: str = "queued"


class ManualRecordInput(BaseModel):
    production_date: date
    production_line: str = Field(min_length=1, max_length=32)
    shift_name: Literal["白班", "夜班"]
    operator_name: str = Field(min_length=1, max_length=64)
    furnace: str = Field(min_length=1, max_length=64)
    reaction_time: float | None = Field(default=None, ge=0, le=24)
    clean_empty_burn_time: float = Field(default=0, ge=0, le=24)
    fault_time: float = Field(default=0, ge=0, le=24)
    output: float | None = Field(default=None, ge=0)
    source_yield: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_record(self):
        paired = self.reaction_time is not None and self.output is not None
        missing_pair = (self.reaction_time is None) != (self.output is None)
        if missing_pair:
            raise ValueError("反应时间与产量必须同时填写或同时留空")
        if paired and self.reaction_time <= 0:
            raise ValueError("生产记录的反应时间必须大于 0")
        if not paired and self.clean_empty_burn_time <= 0 and self.fault_time <= 0:
            raise ValueError("非生产记录至少填写故障或清理/空烧时长")
        return self


class ManualEntryRequest(BaseModel):
    kind: Literal["shared", "temporary"] = "shared"
    name: str = Field(min_length=1, max_length=255)
    base_dataset_id: str | None = None
    records: list[ManualRecordInput] = Field(min_length=1, max_length=500)


class JobStatus(BaseModel):
    id: str
    job_type: str
    status: str
    phase: str
    progress: int
    message: str
    dataset_id: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_detail: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobQueryRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)


class PublishRequest(BaseModel):
    confirm: bool
    complete_dates: dict[str, date] = Field(default_factory=dict)
    acknowledged_issue_codes: list[str] = Field(default_factory=list)


class FilterScope(BaseModel):
    dataset_id: str | None = None
    grain: Grain = "shift"
    production_lines: list[str] = Field(default_factory=list)
    furnaces: list[str] = Field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None


class FilterOptionsResponse(BaseModel):
    dataset: DatasetSummary
    scope: FilterScope
    production_lines: list[str] = Field(default_factory=list)
    furnaces: list[str] = Field(default_factory=list)
    furnaces_by_line: dict[str, list[str]] = Field(default_factory=dict)
    date_min: date | None = None
    date_max: date | None = None
    complete_dates: dict[str, str] = Field(default_factory=dict)


class KpiValue(BaseModel):
    key: str
    label: str
    value: float | int | None
    unit: str = ""
    previous_value: float | int | None = None
    delta_percent: float | None = None


class LineSnapshot(BaseModel):
    production_line: str
    snapshot_date: date
    is_confirmed_complete: bool
    kpis: list[KpiValue]
    active_furnaces: int
    serious_alerts: int
    pairing_completeness: float
    freshness_days: int


class OverviewResponse(BaseModel):
    dataset: DatasetSummary
    line_snapshots: list[LineSnapshot]
    common_comparison_date: date | None = None
    quality_issue_counts: dict[str, int] = Field(default_factory=dict)
    top_risks: list[dict[str, Any]] = Field(default_factory=list)


class SeriesResponse(BaseModel):
    grain: str
    rows: list[dict[str, Any]]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExportRequest(BaseModel):
    dataset_id: str | None = None
    report_type: Literal[
        "daily_summary",
        "monthly_summary",
        "furnace_stats",
        "furnace_daily_trend",
        "anomaly",
        "fault_analysis",
        "fault_warning",
        "all",
    ]
    production_lines: list[str] = Field(default_factory=list)
    furnaces: list[str] = Field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None
