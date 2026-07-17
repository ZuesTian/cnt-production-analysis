from __future__ import annotations

import shutil
import traceback
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session, sessionmaker

import analysis
from config import Settings
from models import ExportArtifact
from services.import_service import _set_job
from services.metrics_service import load_records


def records_to_legacy_cycles(frame: pd.DataFrame) -> pd.DataFrame:
    """Build the legacy CLI/report schema without duplicating cleaning downtime."""
    if frame.empty:
        return pd.DataFrame()
    # Keep valid production, incomplete-production and downtime-only rows so the
    # legacy report totals match the Web API. Empty and invalid source rows stay
    # visible in the quality report instead of contaminating exported metrics.
    frame = frame.loc[frame["is_valid"].astype(bool) & ~frame["record_class"].eq("empty")].copy()
    if frame.empty:
        return pd.DataFrame()
    result = pd.DataFrame(
        {
            "日期": pd.to_datetime(frame["production_date"]),
            "年月": frame["year_month"].astype(str),
            "生产线": frame["production_line"].astype(str),
            "班组": frame["team_normalized"].astype(str),
            "炉号": frame["furnace"].astype(str),
            "反应时间": frame["reaction_time"],
            "空烧时间": frame["clean_empty_burn_time"].fillna(0),
            # Kept for old workbook schemas. It is zero because both old columns
            # originate from the same source field and must not be added twice.
            "降清时间": 0.0,
            "故障时间": frame["fault_time"].fillna(0),
            "产量": frame["output"],
            "产率": np.where(
                frame["reaction_time"].fillna(0) > 0,
                frame["output"] / frame["reaction_time"],
                np.nan,
            ),
            "源表小时产能": frame["source_yield"],
            "来源工作表": frame["source_sheet"].astype(str),
            "来源行号": frame["source_row"].astype(str),
            "周期序号": frame["sequence_no"].astype(int),
        }
    )
    return result


def _generate_report(report_type: str, cycles: pd.DataFrame, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if report_type == "daily_summary":
        path, _, _ = analysis.write_daily_summary(cycles, output_dir=output_dir)
        return [path]
    if report_type == "monthly_summary":
        path, _, _ = analysis.write_monthly_summary(cycles, output_dir=output_dir)
        return [path]
    if report_type == "furnace_stats":
        return [analysis.furnace_stats(cycles, output_dir=output_dir)]
    if report_type == "furnace_daily_trend":
        path, _ = analysis.write_furnace_daily_trend_data(cycles, output_dir=output_dir)
        return [path]
    if report_type == "anomaly":
        return [analysis.write_anomaly_report(cycles, output_dir=output_dir)]
    if report_type == "fault_analysis":
        return [analysis.write_fault_analysis_report(cycles, output_dir=output_dir)]
    if report_type == "fault_warning":
        path, _, _ = analysis.write_fault_warning_report(cycles, output_dir=output_dir)
        return [path]
    if report_type == "all":
        paths: list[Path] = []
        paths.append(analysis.furnace_stats(cycles, output_dir=output_dir))
        paths.append(analysis.write_daily_summary(cycles, output_dir=output_dir)[0])
        paths.append(analysis.write_monthly_summary(cycles, output_dir=output_dir)[0])
        paths.append(analysis.write_furnace_daily_trend_data(cycles, output_dir=output_dir)[0])
        paths.append(analysis.write_anomaly_report(cycles, output_dir=output_dir))
        paths.append(analysis.write_fault_analysis_report(cycles, output_dir=output_dir))
        paths.append(analysis.write_fault_warning_report(cycles, output_dir=output_dir)[0])
        return paths
    raise ValueError(f"不支持的报表类型：{report_type}")


def process_export(
    session_factory: sessionmaker[Session],
    settings: Settings,
    job_id: str,
    dataset_id: str,
    report_type: str,
    filters: dict[str, Any],
) -> None:
    try:
        _set_job(
            session_factory,
            job_id,
            status="running",
            phase="querying",
            progress=12,
            message="正在读取筛选后的班次记录",
        )
        with session_factory() as session:
            frame = load_records(
                session,
                dataset_id,
                filters.get("production_lines"),
                filters.get("furnaces"),
                date.fromisoformat(filters["date_from"]) if filters.get("date_from") else None,
                date.fromisoformat(filters["date_to"]) if filters.get("date_to") else None,
            )
        if frame.empty:
            raise ValueError("当前筛选范围没有可导出的记录")

        _set_job(
            session_factory,
            job_id,
            phase="rendering",
            progress=38,
            message="正在生成兼容 Excel 报表",
        )
        cycles = records_to_legacy_cycles(frame)
        if cycles.empty:
            raise ValueError("当前筛选范围只有空记录或无效记录，无法生成报表")
        artifact_id = uuid.uuid4().hex
        report_dir = settings.export_dir / artifact_id
        paths = _generate_report(report_type, cycles, report_dir)

        if len(paths) == 1:
            stored_path = paths[0]
            filename = paths[0].name
        else:
            _set_job(
                session_factory,
                job_id,
                phase="packaging",
                progress=82,
                message="正在打包全量分析报表",
            )
            archive_base = report_dir / "碳纳米管生产分析报表"
            stored_path = Path(shutil.make_archive(str(archive_base), "zip", report_dir))
            filename = stored_path.name

        with session_factory() as session:
            session.add(
                ExportArtifact(
                    id=artifact_id,
                    job_id=job_id,
                    dataset_id=dataset_id,
                    report_type=report_type,
                    filename=filename,
                    stored_path=str(stored_path.resolve()),
                    size=stored_path.stat().st_size,
                )
            )
            session.commit()
        _set_job(
            session_factory,
            job_id,
            status="completed",
            phase="ready",
            progress=100,
            message="报表已生成",
            result={"export_id": artifact_id, "filename": filename},
        )
    except Exception as exc:
        _set_job(
            session_factory,
            job_id,
            status="failed",
            phase="failed",
            progress=100,
            message="报表生成失败",
            error_code="EXPORT_FAILED",
            error_detail=f"{exc}\n{traceback.format_exc(limit=5)}",
        )
