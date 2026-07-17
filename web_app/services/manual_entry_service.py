from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session, sessionmaker

from config import Settings
from models import Dataset, QualityIssue, ShiftRecord
from services.common import json_dumps
from services.import_service import _set_job, prepare_records
from services.metrics_service import clear_dataset_cache, load_records


def _base_cycles(session: Session, dataset_id: str | None) -> pd.DataFrame:
    if not dataset_id:
        return pd.DataFrame()
    frame = load_records(session, dataset_id)
    if frame.empty:
        return pd.DataFrame()
    dates = pd.to_datetime(frame["production_date"])
    return pd.DataFrame({
        "日期": dates,
        "年月": dates.dt.strftime("%Y-%m"),
        "生产线": frame["production_line"].astype(str),
        "班组": frame["team_raw"].astype(str),
        "炉号": frame["furnace"].astype(str),
        "反应时间": frame["reaction_time"],
        "故障时间": frame["fault_time"].fillna(0),
        "空烧时间": frame["clean_empty_burn_time"].fillna(0),
        "产量": frame["output"],
        "产率": frame["calculated_yield"],
        "源表小时产能": frame["source_yield"],
        "来源工作表": frame["source_sheet"].astype(str),
        "来源行号": frame["source_row"].astype(str),
        "周期序号": frame["sequence_no"].astype(int),
    })


def _manual_cycles(records: list[dict[str, Any]], sequence_start: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(records, start=1):
        production_date = pd.Timestamp(item["production_date"])
        reaction = item.get("reaction_time")
        output = item.get("output")
        rows.append({
            "日期": production_date,
            "年月": production_date.strftime("%Y-%m"),
            "生产线": str(item["production_line"]).strip(),
            "班组": f'{item["shift_name"]}{str(item["operator_name"]).strip()}',
            "炉号": str(item["furnace"]).strip(),
            "反应时间": reaction,
            "故障时间": item.get("fault_time", 0),
            "空烧时间": item.get("clean_empty_burn_time", 0),
            "产量": output,
            "产率": (float(output) / float(reaction)) if reaction and output is not None else np.nan,
            "源表小时产能": item.get("source_yield"),
            "来源工作表": "人工录入",
            "来源行号": f"manual:{index}",
            "周期序号": sequence_start + index,
        })
    return pd.DataFrame(rows)


def _optional_numbers(frame: pd.DataFrame, column: str, default: float | None = None) -> list[float | None]:
    values = pd.to_numeric(frame[column], errors="coerce").to_numpy()
    return [float(value) if np.isfinite(value) else default for value in values]


def _persist(
    session_factory: sessionmaker[Session],
    dataset_id: str,
    prepared: pd.DataFrame,
    issues: list[dict[str, Any]],
    complete_dates: dict[str, str],
    coverage: dict[str, Any],
) -> str:
    severities = {item["severity"] for item in issues}
    quality_status = "blocked" if "critical" in severities else ("warning" if severities - {"info", "low"} else "pass")
    fallback = pd.Series(np.arange(1, len(prepared) + 1), index=prepared.index)
    sequence = pd.to_numeric(prepared.get("周期序号", fallback), errors="coerce").fillna(fallback).astype(int)
    mappings = pd.DataFrame({
        "dataset_id": dataset_id,
        "sequence_no": sequence.to_numpy(),
        "production_date": prepared["日期"].dt.date.to_numpy(),
        "year_month": prepared["年月"].astype(str).to_numpy(),
        "production_line": prepared["生产线"].astype(str).to_numpy(),
        "team_raw": prepared["班组原文"].astype(str).to_numpy(),
        "team_normalized": prepared["班组标准"].astype(str).to_numpy(),
        "shift_name": prepared["班次"].astype(str).to_numpy(),
        "operator_name": prepared["操作人员"].astype(str).to_numpy(),
        "furnace": prepared["炉号"].astype(str).to_numpy(),
        "reaction_time": _optional_numbers(prepared, "反应时间"),
        "clean_empty_burn_time": _optional_numbers(prepared, "空烧时间", 0.0),
        "fault_time": _optional_numbers(prepared, "故障时间", 0.0),
        "output": _optional_numbers(prepared, "产量"),
        "calculated_yield": _optional_numbers(prepared, "产率"),
        "source_yield": _optional_numbers(prepared, "源表小时产能"),
        "source_sheet": prepared["来源工作表"].astype(str).to_numpy(),
        "source_row": prepared["来源行号"].astype(str).to_numpy(),
        "record_class": prepared["记录类型"].astype(str).to_numpy(),
        "is_valid": prepared["是否有效"].astype(bool).to_numpy(),
    }).to_dict("records")

    with session_factory() as session:
        session.execute(delete(ShiftRecord).where(ShiftRecord.dataset_id == dataset_id))
        session.execute(delete(QualityIssue).where(QualityIssue.dataset_id == dataset_id))
        for start in range(0, len(mappings), 5000):
            session.execute(insert(ShiftRecord), mappings[start:start + 5000])
        for item in issues:
            session.add(QualityIssue(
                dataset_id=dataset_id,
                code=item["code"],
                severity=item["severity"],
                title=item["title"],
                description=item["description"],
                affected_count=item["affected_count"],
                affected_rate=item["affected_rate"],
                details_json=json_dumps(item["details"]),
            ))
        dataset = session.get(Dataset, dataset_id)
        if not dataset:
            raise RuntimeError("人工录入数据版本已不存在")
        dataset.status = "ready"
        dataset.row_count = len(prepared)
        dataset.valid_production_count = int((prepared["记录类型"] == "production").sum())
        dataset.furnace_count = int(prepared["炉号"].nunique())
        dataset.date_min = pd.Timestamp(prepared["日期"].min()).date()
        dataset.date_max = pd.Timestamp(prepared["日期"].max()).date()
        dataset.quality_status = quality_status
        dataset.coverage_json = json_dumps(coverage)
        dataset.complete_dates_json = json_dumps(complete_dates)
        session.commit()
    clear_dataset_cache(dataset_id)
    return quality_status


def process_manual_entry(
    session_factory: sessionmaker[Session],
    settings: Settings,
    job_id: str,
    dataset_id: str,
    base_dataset_id: str | None,
    records: list[dict[str, Any]],
) -> None:
    def progress(phase: str, percent: int, message: str) -> None:
        _set_job(session_factory, job_id, status="running", phase=phase, progress=percent, message=message)

    try:
        progress("copying_base", 15, "正在复制基础版本，保持原版本不可变")
        with session_factory() as session:
            base = _base_cycles(session, base_dataset_id)
        if len(base) + len(records) > settings.max_rows:
            raise ValueError(f"合并后记录数 {len(base) + len(records)} 超过上限 {settings.max_rows}")
        sequence_start = int(base["周期序号"].max()) if not base.empty else 0
        combined = pd.concat([base, _manual_cycles(records, sequence_start)], ignore_index=True)

        progress("quality_profiling", 45, "正在校验人工记录并重新计算质量状态")
        prepared, issues, complete_dates, coverage = prepare_records(combined, settings)
        progress("persisting", 75, "正在建立新的不可变数据版本")
        quality_status = _persist(session_factory, dataset_id, prepared, issues, complete_dates, coverage)
        with session_factory() as session:
            load_records(session, dataset_id)
        _set_job(
            session_factory,
            job_id,
            status="completed",
            phase="ready",
            progress=100,
            message="人工录入预检完成，等待确认",
            result={"dataset_id": dataset_id, "manual_record_count": len(records), "row_count": len(prepared), "quality_status": quality_status},
        )
    except Exception as exc:
        with session_factory() as session:
            dataset = session.get(Dataset, dataset_id)
            if dataset:
                dataset.status = "failed"
                dataset.quality_status = "blocked"
                session.commit()
        _set_job(
            session_factory,
            job_id,
            status="failed",
            phase="failed",
            progress=100,
            message="人工录入预检失败",
            error_code="MANUAL_ENTRY_FAILED",
            error_detail=f"{exc}\n{traceback.format_exc(limit=5)}",
        )
