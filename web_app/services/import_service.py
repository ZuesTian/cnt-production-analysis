from __future__ import annotations

import re
import shutil
import traceback
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session, sessionmaker

import analysis
from config import Settings
from models import Dataset, ExportArtifact, Job, QualityIssue, ShiftRecord, utcnow
from services.common import json_dumps


ProgressCallback = Callable[[str, int, str], None]


def _normalize_team(value: object, aliases: dict[str, str]) -> tuple[str, str, str, str]:
    raw = "" if value is None or pd.isna(value) else str(value)
    compact = re.sub(r"\s+", "", raw)
    normalized = aliases.get(compact, compact)
    if normalized.startswith("白班"):
        shift_name, operator = "白班", normalized[2:]
    elif normalized.startswith("夜班"):
        shift_name, operator = "夜班", normalized[2:]
    else:
        shift_name, operator = "未知", normalized
    return raw, normalized, shift_name, operator


def _is_single_edit_apart(left: str, right: str) -> bool:
    """Cheap bounded edit-distance check used only to surface review hints."""
    if left == right or abs(len(left) - len(right)) > 1:
        return False
    if len(left) > len(right):
        left, right = right, left
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) == 1
    index_left = index_right = differences = 0
    while index_left < len(left) and index_right < len(right):
        if left[index_left] == right[index_right]:
            index_left += 1
            index_right += 1
        else:
            differences += 1
            index_right += 1
            if differences > 1:
                return False
    return True


def _similar_operator_pairs(values: pd.Series) -> list[list[str]]:
    """Return conservative possible-name variants without changing either value."""
    names = sorted({str(value).strip() for value in values.dropna() if len(str(value).strip()) >= 2})[:200]
    pairs: list[list[str]] = []
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            if not _is_single_edit_apart(left, right):
                continue
            conservative_match = (
                min(len(left), len(right)) >= 4
                or left in right
                or right in left
                or (len(left) == len(right) >= 3 and left[0] == right[0] and left[-1] == right[-1])
            )
            if conservative_match:
                pairs.append([left, right])
                if len(pairs) >= 30:
                    return pairs
    return pairs


def _record_classes(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, dict[str, pd.Series]]:
    reaction = pd.to_numeric(df["反应时间"], errors="coerce")
    output = pd.to_numeric(df["产量"], errors="coerce")
    fault = pd.to_numeric(df["故障时间"], errors="coerce").fillna(0)
    clean = pd.to_numeric(df["空烧时间"], errors="coerce").fillna(0)

    production = reaction.gt(0) & output.notna() & output.ge(0)
    downtime = reaction.isna() & output.isna() & ((fault > 0) | (clean > 0))
    incomplete = reaction.notna() ^ output.notna()
    empty = reaction.isna() & output.isna() & ~downtime
    invalid = (
        reaction.lt(0).fillna(False)
        | output.lt(0).fillna(False)
        | fault.lt(0).fillna(False)
        | clean.lt(0).fillna(False)
        | reaction.gt(24).fillna(False)
        | fault.gt(24).fillna(False)
        | clean.gt(24).fillna(False)
        | (reaction.eq(0) & output.notna())
    )

    classes = pd.Series("other", index=df.index, dtype="object")
    classes.loc[production] = "production"
    classes.loc[downtime] = "downtime_only"
    classes.loc[incomplete] = "incomplete_production"
    classes.loc[empty] = "empty"
    classes.loc[invalid] = "invalid"
    valid = ~(invalid | empty)
    return classes, valid, {
        "production": production,
        "downtime": downtime,
        "incomplete": incomplete,
        "empty": empty,
        "invalid": invalid,
    }


def _issue(
    code: str,
    severity: str,
    title: str,
    description: str,
    mask: pd.Series,
    total: int,
    details: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    count = int(mask.sum())
    if count <= 0:
        return None
    return {
        "code": code,
        "severity": severity,
        "title": title,
        "description": description,
        "affected_count": count,
        "affected_rate": round(count / total, 6) if total else 0,
        "details": details or {},
    }


def _suggest_complete_dates(df: pd.DataFrame, settings: Settings) -> tuple[dict[str, str], dict[str, Any]]:
    daily = (
        df.groupby(["生产线", "日期"], as_index=False)
        .size()
        .rename(columns={"size": "row_count"})
        .sort_values(["生产线", "日期"])
    )
    suggested: dict[str, str] = {}
    coverage: dict[str, Any] = {}
    for line, group in daily.groupby("生产线"):
        group = group.reset_index(drop=True)
        candidates: list[tuple[pd.Timestamp, int, float, bool]] = []
        for idx, row in group.iterrows():
            previous = group.iloc[max(0, idx - settings.complete_day_lookback):idx]["row_count"]
            if len(previous) < settings.complete_day_min_history:
                continue
            expected = float(previous.median())
            ratio = float(row["row_count"] / expected) if expected else 0.0
            if ratio >= settings.complete_day_min_coverage:
                candidates.append((pd.Timestamp(row["日期"]), int(row["row_count"]), ratio, True))

        latest = group.iloc[-1]
        if candidates:
            selected_date, selected_count, selected_ratio, verified = candidates[-1]
        else:
            selected_date = pd.Timestamp(latest["日期"])
            selected_count = int(latest["row_count"])
            selected_ratio = 1.0
            verified = False

        latest_date = pd.Timestamp(latest["日期"])
        latest_history = group.iloc[max(0, len(group) - settings.complete_day_lookback - 1):-1]["row_count"]
        expected_latest = float(latest_history.median()) if len(latest_history) else float(latest["row_count"])
        latest_ratio = float(latest["row_count"] / expected_latest) if expected_latest else 0.0
        suggested[str(line)] = selected_date.date().isoformat()
        coverage[str(line)] = {
            "date_min": pd.Timestamp(group["日期"].min()).date().isoformat(),
            "date_max": latest_date.date().isoformat(),
            "suggested_complete_date": selected_date.date().isoformat(),
            "suggested_verified": verified,
            "suggested_row_count": selected_count,
            "suggested_coverage_ratio": round(selected_ratio, 4),
            "latest_row_count": int(latest["row_count"]),
            "latest_coverage_ratio": round(latest_ratio, 4),
            "date_count": int(len(group)),
        }
    return suggested, coverage


def prepare_records(df: pd.DataFrame, settings: Settings) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, str], dict[str, Any]]:
    data = df.copy()
    aliases = {
        re.sub(r"\s+", "", str(key)): re.sub(r"\s+", "", str(value))
        for key, value in analysis.CONFIG.get("team_aliases", {}).items()
    }
    normalized = data["班组"].map(lambda value: _normalize_team(value, aliases))
    data[["班组原文", "班组标准", "班次", "操作人员"]] = pd.DataFrame(normalized.tolist(), index=data.index)

    record_class, is_valid, masks = _record_classes(data)
    data["记录类型"] = record_class
    data["是否有效"] = is_valid

    total = len(data)
    issues: list[dict[str, Any]] = []
    candidates = [
        _issue(
            "INCOMPLETE_PRODUCTION_PAIR",
            "high",
            "产量与反应时间不成对",
            "该记录无法参与加权产率计算，产量仍会保留在总产量中。",
            masks["incomplete"],
            total,
        ),
        _issue(
            "EMPTY_RECORD",
            "medium",
            "空记录",
            "生产、故障与清理字段均为空，该记录将从指标中排除。",
            masks["empty"],
            total,
        ),
        _issue(
            "INVALID_MEASURE",
            "high",
            "存在不可能的时间或产量",
            "负数、单班超过 24 小时或零反应时间带产量的记录将从指标中排除。",
            masks["invalid"],
            total,
        ),
        _issue(
            "DOWNTIME_ONLY",
            "info",
            "纯停机记录",
            "该类记录计入故障/清理时长，但不计入有效生产班次和产率。",
            masks["downtime"],
            total,
        ),
    ]

    comparable = data["产率"].notna() & data["源表小时产能"].notna()
    mismatch = comparable & ((data["产率"] - data["源表小时产能"]).abs() > settings.yield_delta_warning)
    candidates.append(
        _issue(
            "YIELD_SOURCE_MISMATCH",
            "medium",
            "源表产率与重算产率差异较大",
            f"绝对差超过 {settings.yield_delta_warning:g} kg/h；仪表盘以产量÷反应时间为准。",
            mismatch,
            total,
            {"threshold": settings.yield_delta_warning},
        )
    )

    duplicate = data.duplicated(["日期", "生产线", "炉号", "班组标准"], keep=False)
    candidates.append(
        _issue(
            "DUPLICATE_SHIFT_GRAIN",
            "medium",
            "同炉同日同班次存在多条记录",
            "记录保留在班次粒度，并在炉日粒度汇总；请结合来源行号复核。",
            duplicate,
            total,
        )
    )

    raw_variants = data.groupby("班组标准")["班组原文"].nunique(dropna=False)
    variant_labels = set(raw_variants[raw_variants > 1].index)
    team_variant = data["班组标准"].isin(variant_labels)
    candidates.append(
        _issue(
            "TEAM_LABEL_VARIANT",
            "low",
            "班组标签存在空格或换行变体",
            "展示使用标准化标签，原始文本仍保留用于追溯。",
            team_variant,
            total,
            {"normalized_labels": sorted(str(item) for item in variant_labels)[:30]},
        )
    )

    similar_operator_pairs = _similar_operator_pairs(data["操作人员"])
    similar_operators = {name for pair in similar_operator_pairs for name in pair}
    candidates.append(
        _issue(
            "OPERATOR_NAME_SIMILAR",
            "low",
            "操作人员姓名存在近似项",
            "仅提示可能的录入变体，不会自动模糊合并；请在 team_aliases 中显式确认。",
            data["操作人员"].isin(similar_operators),
            total,
            {"possible_pairs": similar_operator_pairs},
        )
    )

    known_lines = set(str(key) for key in analysis.CONFIG.get("production_lines", {}).keys())
    unknown_line = ~data["生产线"].astype(str).isin(known_lines) if known_lines else pd.Series(False, index=data.index)
    candidates.append(
        _issue(
            "UNKNOWN_PRODUCTION_LINE",
            "high",
            "存在未配置生产线",
            "未配置产线可能导致筛选和对比错误。",
            unknown_line,
            total,
        )
    )

    complete_dates, coverage = _suggest_complete_dates(data, settings)
    partial_latest = pd.Series(False, index=data.index)
    for line, details in coverage.items():
        if details["date_max"] != details["suggested_complete_date"]:
            partial_latest |= (data["生产线"].astype(str) == line) & (
                data["日期"].dt.date.astype(str) == details["date_max"]
            )
    candidates.append(
        _issue(
            "PARTIAL_LATEST_DAY",
            "high",
            "最新日期疑似不完整",
            "首页将使用建议完整日，发布时必须确认各产线数据截止日期。",
            partial_latest,
            total,
            coverage,
        )
    )

    now = pd.Timestamp.now().normalize()
    stale_mask = pd.Series(False, index=data.index)
    stale_lines: dict[str, int] = {}
    for line, details in coverage.items():
        lag = int((now - pd.Timestamp(details["suggested_complete_date"])).days)
        if lag > settings.freshness_warning_days:
            stale_lines[line] = lag
            stale_mask |= data["生产线"].astype(str) == line
    candidates.append(
        _issue(
            "STALE_LINE_DATA",
            "high",
            "生产线数据已滞后",
            "共享看板会持续显示数据截止日期和滞后天数。",
            stale_mask,
            total,
            {"freshness_days": stale_lines, "warning_days": settings.freshness_warning_days},
        )
    )

    issues.extend(item for item in candidates if item is not None)
    return data, issues, complete_dates, coverage


def _set_job(
    session_factory: sessionmaker[Session],
    job_id: str,
    *,
    status: str | None = None,
    phase: str | None = None,
    progress: int | None = None,
    message: str | None = None,
    error_code: str | None = None,
    error_detail: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    with session_factory() as session:
        job = session.get(Job, job_id)
        if not job:
            return
        if status is not None:
            job.status = status
            if status == "running" and not job.started_at:
                job.started_at = utcnow()
            if status in {"completed", "failed", "cancelled"}:
                job.finished_at = utcnow()
        if phase is not None:
            job.phase = phase
        if progress is not None:
            job.progress = max(0, min(100, int(progress)))
        if message is not None:
            job.message = message
        if error_code is not None:
            job.error_code = error_code
        if error_detail is not None:
            job.error_detail = error_detail
        if result is not None:
            job.result_json = json_dumps(result)
        session.commit()


def process_import(
    session_factory: sessionmaker[Session],
    settings: Settings,
    job_id: str,
    dataset_id: str,
    source_path: Path,
) -> None:
    def progress(phase: str, percent: int, message: str) -> None:
        _set_job(
            session_factory,
            job_id,
            status="running",
            phase=phase,
            progress=percent,
            message=message,
        )

    try:
        progress("schema_validation", 10, "正在读取工作表并校验字段")
        # Web versions are already immutable and persisted in SQLite. Avoid the
        # legacy global pickle cache so temporary datasets leave no residual copy.
        cycles = analysis.load_and_clean_data(source_path, use_cache=False)
        if cycles.empty:
            raise ValueError("清洗后没有可分析记录")
        if len(cycles) > settings.max_rows:
            raise ValueError(f"清洗后记录数 {len(cycles)} 超过上限 {settings.max_rows}")

        progress("quality_profiling", 38, "正在分析完整性、有效性和覆盖范围")
        prepared, issues, complete_dates, coverage = prepare_records(cycles, settings)
        source_quality = cycles.attrs.get("source_quality", {})
        invalid_date_count = int(source_quality.get("invalid_date_count", 0))
        if invalid_date_count:
            source_total = int(source_quality.get("source_row_count", len(cycles) + invalid_date_count))
            issues.append(
                {
                    "code": "INVALID_DATE",
                    "severity": "high",
                    "title": "存在无法解析的日期",
                    "description": "无效日期记录已从分析指标中排除，并保留受影响数量供源表复核。",
                    "affected_count": invalid_date_count,
                    "affected_rate": round(invalid_date_count / source_total, 6) if source_total else 0,
                    "details": {},
                }
            )
        issue_severities = {item["severity"] for item in issues}
        quality_status = "blocked" if "critical" in issue_severities else ("warning" if issue_severities - {"info", "low"} else "pass")

        progress("normalizing", 58, "正在建立班次记录与双粒度字段")
        def optional_numbers(column: str, default: float | None = None) -> list[float | None]:
            values = pd.to_numeric(prepared[column], errors="coerce").to_numpy()
            return [
                float(value) if np.isfinite(value) else default
                for value in values
            ]

        fallback_sequence = pd.Series(np.arange(1, len(prepared) + 1), index=prepared.index)
        if "周期序号" in prepared.columns:
            sequence = pd.to_numeric(prepared["周期序号"], errors="coerce")
            sequence = sequence.where(sequence.notna(), fallback_sequence).astype(int)
        else:
            sequence = fallback_sequence
        mapping_frame = pd.DataFrame(
            {
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
                "reaction_time": optional_numbers("反应时间"),
                "clean_empty_burn_time": optional_numbers("空烧时间", 0.0),
                "fault_time": optional_numbers("故障时间", 0.0),
                "output": optional_numbers("产量"),
                "calculated_yield": optional_numbers("产率"),
                "source_yield": optional_numbers("源表小时产能"),
                "source_sheet": prepared["来源工作表"].astype(str).to_numpy(),
                "source_row": prepared["来源行号"].astype(str).to_numpy(),
                "record_class": prepared["记录类型"].astype(str).to_numpy(),
                "is_valid": prepared["是否有效"].astype(bool).to_numpy(),
            }
        )
        mappings: list[dict[str, Any]] = mapping_frame.to_dict("records")

        progress("persisting", 72, "正在写入共享分析库")
        with session_factory() as session:
            session.execute(delete(ShiftRecord).where(ShiftRecord.dataset_id == dataset_id))
            session.execute(delete(QualityIssue).where(QualityIssue.dataset_id == dataset_id))
            for start in range(0, len(mappings), 5000):
                session.execute(insert(ShiftRecord), mappings[start:start + 5000])

            for item in issues:
                session.add(
                    QualityIssue(
                        dataset_id=dataset_id,
                        code=item["code"],
                        severity=item["severity"],
                        title=item["title"],
                        description=item["description"],
                        affected_count=item["affected_count"],
                        affected_rate=item["affected_rate"],
                        details_json=json_dumps(item["details"]),
                    )
                )

            dataset = session.get(Dataset, dataset_id)
            if not dataset:
                raise RuntimeError("数据集已不存在")
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

        progress("aggregating", 90, "正在准备只读聚合查询缓存")
        from services.metrics_service import clear_dataset_cache, load_records

        clear_dataset_cache(dataset_id)
        with session_factory() as session:
            load_records(session, dataset_id)

        progress("ready", 96, "数据预检完成，等待发布确认")
        result = {
            "dataset_id": dataset_id,
            "row_count": len(prepared),
            "valid_production_count": int((prepared["记录类型"] == "production").sum()),
            "quality_status": quality_status,
            "complete_dates": complete_dates,
            "issue_count": len(issues),
        }
        _set_job(
            session_factory,
            job_id,
            status="completed",
            phase="ready",
            progress=100,
            message="数据预检完成",
            result=result,
        )
    except Exception as exc:
        with session_factory() as session:
            dataset = session.get(Dataset, dataset_id)
            if dataset:
                dataset.status = "failed"
                dataset.quality_status = "blocked"
                message = str(exc)
                if "必需列" in message or "缺少列" in message or "缺少" in message:
                    session.add(
                        QualityIssue(
                            dataset_id=dataset_id,
                            code="MISSING_REQUIRED_COLUMNS",
                            severity="critical",
                            title="缺少必需列",
                            description=message[:2000],
                            affected_count=0,
                            affected_rate=0,
                            details_json="{}",
                        )
                    )
                session.commit()
        _set_job(
            session_factory,
            job_id,
            status="failed",
            phase="failed",
            progress=100,
            message="导入失败",
            error_code="IMPORT_FAILED",
            error_detail=f"{exc}\n{traceback.format_exc(limit=5)}",
        )


def cleanup_expired_temporary(
    session_factory: sessionmaker[Session],
    settings: Settings | None = None,
) -> list[str]:
    now = utcnow()
    removed_paths: list[str] = []
    export_paths: list[str] = []
    with session_factory() as session:
        datasets = session.scalars(
            select(Dataset).where(
                Dataset.kind == "temporary",
                Dataset.expires_at.is_not(None),
                Dataset.expires_at < now,
                Dataset.status != "expired",
            )
        ).all()
        for dataset in datasets:
            removed_paths.append(dataset.stored_path)
            artifacts = session.scalars(
                select(ExportArtifact).where(ExportArtifact.dataset_id == dataset.id)
            ).all()
            export_paths.extend(artifact.stored_path for artifact in artifacts)
            session.execute(delete(ExportArtifact).where(ExportArtifact.dataset_id == dataset.id))
            session.execute(delete(Job).where(Job.dataset_id == dataset.id))
            session.delete(dataset)
        session.commit()
    for raw_path in removed_paths:
        try:
            path = Path(raw_path).resolve()
            if settings is None or settings.import_dir.resolve() in path.parents:
                path.unlink(missing_ok=True)
        except OSError:
            pass
    for raw_path in export_paths:
        try:
            path = Path(raw_path).resolve()
            if settings is None:
                path.unlink(missing_ok=True)
            elif settings.export_dir.resolve() in path.parents:
                report_dir = path.parent
                if report_dir.parent.resolve() == settings.export_dir.resolve():
                    shutil.rmtree(report_dir, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
        except OSError:
            pass
    if datasets:
        from services.metrics_service import clear_dataset_cache

        for dataset in datasets:
            clear_dataset_cache(dataset.id)
    return removed_paths
