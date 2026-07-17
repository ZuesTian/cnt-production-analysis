from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)  # shared | temporary
    status: Mapped[str] = mapped_column(String(20), index=True)  # processing | ready | published | archived | failed | expired
    name: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    owner_workspace: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    valid_production_count: Mapped[int] = mapped_column(Integer, default=0)
    furnace_count: Mapped[int] = mapped_column(Integer, default=0)
    date_min: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_max: Mapped[date | None] = mapped_column(Date, nullable=True)
    quality_status: Mapped[str] = mapped_column(String(16), default="pending")
    coverage_json: Mapped[str] = mapped_column(Text, default="{}")
    complete_dates_json: Mapped[str] = mapped_column(Text, default="{}")

    records: Mapped[list["ShiftRecord"]] = relationship(back_populates="dataset", cascade="all, delete-orphan")
    issues: Mapped[list["QualityIssue"]] = relationship(back_populates="dataset", cascade="all, delete-orphan")


Index(
    "uq_datasets_single_published_shared",
    Dataset.status,
    unique=True,
    sqlite_where=(Dataset.kind == "shared") & (Dataset.status == "published"),
)


class ShiftRecord(Base):
    __tablename__ = "shift_records"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer)
    production_date: Mapped[date] = mapped_column(Date, index=True)
    year_month: Mapped[str] = mapped_column(String(7), index=True)
    production_line: Mapped[str] = mapped_column(String(32), index=True)
    team_raw: Mapped[str] = mapped_column(Text, default="")
    team_normalized: Mapped[str] = mapped_column(String(128), default="")
    shift_name: Mapped[str] = mapped_column(String(16), default="未知")
    operator_name: Mapped[str] = mapped_column(String(64), default="")
    furnace: Mapped[str] = mapped_column(String(64), index=True)
    reaction_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    clean_empty_burn_time: Mapped[float] = mapped_column(Float, default=0.0)
    fault_time: Mapped[float] = mapped_column(Float, default=0.0)
    output: Mapped[float | None] = mapped_column(Float, nullable=True)
    calculated_yield: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_yield: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_sheet: Mapped[str] = mapped_column(String(255), default="")
    source_row: Mapped[str] = mapped_column(String(64), default="")
    record_class: Mapped[str] = mapped_column(String(32), index=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    dataset: Mapped[Dataset] = relationship(back_populates="records")

    __table_args__ = (
        Index("ix_shift_dataset_date_line_furnace", "dataset_id", "production_date", "production_line", "furnace"),
    )


class QualityIssue(Base):
    __tablename__ = "quality_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    affected_count: Mapped[int] = mapped_column(Integer, default=0)
    affected_rate: Mapped[float] = mapped_column(Float, default=0.0)
    details_json: Mapped[str] = mapped_column(Text, default="{}")

    dataset: Mapped[Dataset] = relationship(back_populates="issues")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    phase: Mapped[str] = mapped_column(String(64), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    dataset_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ExportArtifact(Base):
    __tablename__ = "export_artifacts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(32), index=True)
    dataset_id: Mapped[str] = mapped_column(String(32), index=True)
    report_type: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    dataset_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    previous_dataset_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    client_ip: Mapped[str] = mapped_column(String(64), default="unknown")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
