from __future__ import annotations

from collections import Counter, OrderedDict
from datetime import date
from threading import RLock
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

import analysis
from models import Dataset, QualityIssue, ShiftRecord, utcnow
from services.common import ServiceError, dataset_dict, issue_dict, json_loads


RECORD_COLUMNS = (
    ShiftRecord.sequence_no,
    ShiftRecord.production_date,
    ShiftRecord.year_month,
    ShiftRecord.production_line,
    ShiftRecord.team_raw,
    ShiftRecord.team_normalized,
    ShiftRecord.shift_name,
    ShiftRecord.operator_name,
    ShiftRecord.furnace,
    ShiftRecord.reaction_time,
    ShiftRecord.clean_empty_burn_time,
    ShiftRecord.fault_time,
    ShiftRecord.output,
    ShiftRecord.calculated_yield,
    ShiftRecord.source_yield,
    ShiftRecord.source_sheet,
    ShiftRecord.source_row,
    ShiftRecord.record_class,
    ShiftRecord.is_valid,
)

_RECORD_CACHE: "OrderedDict[str, pd.DataFrame]" = OrderedDict()
_RECORD_CACHE_LOCK = RLock()
_RECORD_CACHE_SIZE = 3


def resolve_dataset(session: Session, dataset_id: str | None, workspace_id: str) -> Dataset:
    if dataset_id:
        dataset = session.get(Dataset, dataset_id)
    else:
        dataset = session.scalar(
            select(Dataset)
            .where(Dataset.kind == "shared", Dataset.status == "published")
            .order_by(Dataset.published_at.desc(), Dataset.created_at.desc())
        )
    if not dataset or dataset.status in {"failed", "expired", "processing"}:
        raise ServiceError("DATASET_NOT_FOUND", "没有可用的数据版本", 404)
    if dataset.kind == "temporary" and dataset.owner_workspace != workspace_id:
        raise ServiceError("DATASET_FORBIDDEN", "临时数据仅对创建它的浏览器会话可见", 403)
    if dataset.kind == "temporary" and dataset.expires_at and dataset.expires_at <= utcnow():
        raise ServiceError("DATASET_EXPIRED", "临时数据已超过 24 小时有效期", 410)
    return dataset


def _record_statement(
    dataset_id: str,
    production_lines: Iterable[str] | None = None,
    furnaces: Iterable[str] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Select[Any]:
    statement = select(*RECORD_COLUMNS).where(ShiftRecord.dataset_id == dataset_id)
    lines = [item for item in (production_lines or []) if item]
    selected_furnaces = [item for item in (furnaces or []) if item]
    if lines:
        statement = statement.where(ShiftRecord.production_line.in_(lines))
    if selected_furnaces:
        statement = statement.where(ShiftRecord.furnace.in_(selected_furnaces))
    if date_from:
        statement = statement.where(ShiftRecord.production_date >= date_from)
    if date_to:
        statement = statement.where(ShiftRecord.production_date <= date_to)
    return statement.order_by(ShiftRecord.production_date, ShiftRecord.production_line, ShiftRecord.furnace)


def load_records(
    session: Session,
    dataset_id: str,
    production_lines: Iterable[str] | None = None,
    furnaces: Iterable[str] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> pd.DataFrame:
    columns = [column.key for column in RECORD_COLUMNS]
    with _RECORD_CACHE_LOCK:
        cached = _RECORD_CACHE.get(dataset_id)
        if cached is not None:
            _RECORD_CACHE.move_to_end(dataset_id)

    if cached is None:
        rows = session.execute(_record_statement(dataset_id)).mappings().all()
        if rows:
            loaded = pd.DataFrame(rows, columns=columns)
            loaded["production_date"] = pd.to_datetime(loaded["production_date"])
            for column in ("reaction_time", "clean_empty_burn_time", "fault_time", "output", "calculated_yield"):
                loaded[column] = pd.to_numeric(loaded[column], errors="coerce")
        else:
            loaded = pd.DataFrame(columns=columns)
        with _RECORD_CACHE_LOCK:
            existing = _RECORD_CACHE.get(dataset_id)
            cached = existing if existing is not None else loaded
            _RECORD_CACHE[dataset_id] = cached
            _RECORD_CACHE.move_to_end(dataset_id)
            while len(_RECORD_CACHE) > _RECORD_CACHE_SIZE:
                _RECORD_CACHE.popitem(last=False)

    frame = cached
    mask = pd.Series(True, index=frame.index)
    lines = [item for item in (production_lines or []) if item]
    selected_furnaces = [item for item in (furnaces or []) if item]
    if lines:
        mask &= frame["production_line"].isin(lines)
    if selected_furnaces:
        mask &= frame["furnace"].isin(selected_furnaces)
    if date_from:
        mask &= frame["production_date"].dt.date >= date_from
    if date_to:
        mask &= frame["production_date"].dt.date <= date_to
    return frame.loc[mask].copy()


def clear_dataset_cache(dataset_id: str | None = None) -> None:
    with _RECORD_CACHE_LOCK:
        if dataset_id is None:
            _RECORD_CACHE.clear()
        else:
            _RECORD_CACHE.pop(dataset_id, None)


def _paired(frame: pd.DataFrame) -> pd.Series:
    return (
        frame["record_class"].eq("production")
        & frame["is_valid"].astype(bool)
        & frame["reaction_time"].gt(0)
        & frame["output"].notna()
    )


def _valid_metric_rows(frame: pd.DataFrame) -> pd.Series:
    return frame["is_valid"].astype(bool) & ~frame["record_class"].eq("empty")


def _aggregate_metrics(frame: pd.DataFrame) -> dict[str, float | int | None]:
    if frame.empty:
        return {
            "total_output": 0.0,
            "weighted_yield": None,
            "fault_hours": 0.0,
            "clean_empty_burn_hours": 0.0,
            "production_shifts": 0,
            "pairing_completeness": 0.0,
        }
    valid = _valid_metric_rows(frame)
    paired = _paired(frame)
    output_total = float(frame.loc[valid, "output"].fillna(0).sum())
    paired_output = float(frame.loc[paired, "output"].sum())
    paired_time = float(frame.loc[paired, "reaction_time"].sum())
    potential = int(
        (
            frame["is_valid"].astype(bool)
            & (frame["reaction_time"].notna() | frame["output"].notna())
        ).sum()
    )
    production_count = int(paired.sum())
    return {
        "total_output": round(output_total, 2),
        "weighted_yield": round(paired_output / paired_time, 2) if paired_time > 0 else None,
        "fault_hours": round(float(frame.loc[valid, "fault_time"].fillna(0).sum()), 2),
        "clean_empty_burn_hours": round(
            float(frame.loc[valid, "clean_empty_burn_time"].fillna(0).sum()), 2
        ),
        "production_shifts": production_count,
        "pairing_completeness": round(production_count / potential, 4) if potential else 0.0,
    }


def _delta(current: float | int | None, previous: float | int | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return round((float(current) - float(previous)) / abs(float(previous)) * 100, 2)


def _kpi(key: str, label: str, value: Any, unit: str, previous: Any) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": value,
        "unit": unit,
        "previous_value": previous,
        "delta_percent": _delta(value, previous),
    }


def overview(
    session: Session,
    dataset: Dataset,
    production_lines: list[str] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    frame = load_records(session, dataset.id, production_lines, None, date_from, date_to)
    if frame.empty:
        raise ServiceError("NO_DATA", "当前筛选范围没有数据", 404)

    complete_dates = json_loads(dataset.complete_dates_json, {})
    lines = production_lines or sorted(frame["production_line"].dropna().unique().tolist())
    snapshots: list[dict[str, Any]] = []
    line_date_sets: list[set[date]] = []
    snapshot_dates: list[date] = []
    critical_hours = float(analysis.ALERT_THRESHOLDS.get("fault_critical_hours_per_day", 12))

    for line in lines:
        line_frame = frame[frame["production_line"] == line]
        if line_frame.empty:
            continue
        available_dates = sorted(pd.Timestamp(item).date() for item in line_frame["production_date"].unique())
        line_date_sets.append(set(available_dates))
        suggested_raw = complete_dates.get(str(line))
        suggested = pd.Timestamp(suggested_raw).date() if suggested_raw else available_dates[-1]
        eligible = [item for item in available_dates if item <= suggested]
        snapshot_date = eligible[-1] if eligible else available_dates[-1]
        previous_dates = [item for item in available_dates if item < snapshot_date]
        snapshot_dates.append(snapshot_date)
        previous_date = previous_dates[-1] if previous_dates else None

        current = line_frame[line_frame["production_date"].dt.date == snapshot_date]
        previous = (
            line_frame[line_frame["production_date"].dt.date == previous_date]
            if previous_date
            else line_frame.iloc[0:0]
        )
        current_metrics = _aggregate_metrics(current)
        previous_metrics = _aggregate_metrics(previous)
        current_valid = current.loc[_valid_metric_rows(current)]
        fault_by_furnace = current_valid.groupby("furnace")["fault_time"].sum(min_count=1)
        serious_alerts = int((fault_by_furnace.fillna(0) >= critical_hours).sum())
        snapshots.append(
            {
                "production_line": str(line),
                "snapshot_date": snapshot_date,
                "is_confirmed_complete": bool(suggested_raw and snapshot_date == suggested),
                "kpis": [
                    _kpi(
                        "total_output",
                        "总产量",
                        current_metrics["total_output"],
                        "kg",
                        previous_metrics["total_output"],
                    ),
                    _kpi(
                        "weighted_yield",
                        "加权产率",
                        current_metrics["weighted_yield"],
                        "kg/h",
                        previous_metrics["weighted_yield"],
                    ),
                    _kpi(
                        "fault_hours",
                        "故障时长",
                        current_metrics["fault_hours"],
                        "h",
                        previous_metrics["fault_hours"],
                    ),
                ],
                "active_furnaces": int(current.loc[_paired(current), "furnace"].nunique()),
                "serious_alerts": serious_alerts,
                "pairing_completeness": current_metrics["pairing_completeness"],
                "freshness_days": max(0, (date.today() - snapshot_date).days),
            }
        )

    common_date: date | None = None
    if line_date_sets:
        common = set.intersection(*line_date_sets)
        latest_safe_date = min(snapshot_dates) if snapshot_dates else None
        safe_common = {item for item in common if latest_safe_date is None or item <= latest_safe_date}
        common_date = max(safe_common) if safe_common else None

    issues = session.scalars(select(QualityIssue).where(QualityIssue.dataset_id == dataset.id)).all()
    issue_counts = Counter(issue.severity for issue in issues)
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    top_risks = [
        issue_dict(issue)
        for issue in sorted(
            issues,
            key=lambda item: (severity_order.get(item.severity, 9), -item.affected_count),
        )[:5]
    ]
    return {
        "dataset": dataset_dict(dataset),
        "line_snapshots": snapshots,
        "common_comparison_date": common_date,
        "quality_issue_counts": dict(issue_counts),
        "top_risks": top_risks,
    }


def _aggregate_group(group: pd.DataFrame) -> pd.Series:
    metrics = _aggregate_metrics(group)
    return pd.Series(metrics)


def aggregate_by(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Vectorized metric aggregation for chart-sized group queries."""
    if frame.empty:
        return pd.DataFrame(columns=[*keys, "total_output", "weighted_yield", "fault_hours"])
    valid = _valid_metric_rows(frame)
    paired = _paired(frame)
    potential = frame["is_valid"].astype(bool) & (frame["reaction_time"].notna() | frame["output"].notna())
    working = frame[keys].copy()
    working["metric_output"] = frame["output"].where(valid, 0).fillna(0)
    working["paired_output"] = frame["output"].where(paired, 0).fillna(0)
    working["paired_time"] = frame["reaction_time"].where(paired, 0).fillna(0)
    working["metric_fault"] = frame["fault_time"].where(valid, 0).fillna(0)
    working["metric_clean"] = frame["clean_empty_burn_time"].where(valid, 0).fillna(0)
    working["paired_count"] = paired.astype(int)
    working["potential_count"] = potential.astype(int)
    grouped = (
        working.groupby(keys, dropna=False, observed=True, as_index=False)
        .agg(
            total_output=("metric_output", "sum"),
            paired_output=("paired_output", "sum"),
            paired_time=("paired_time", "sum"),
            fault_hours=("metric_fault", "sum"),
            clean_empty_burn_hours=("metric_clean", "sum"),
            production_shifts=("paired_count", "sum"),
            potential_count=("potential_count", "sum"),
        )
    )
    grouped["weighted_yield"] = np.where(
        grouped["paired_time"] > 0,
        grouped["paired_output"] / grouped["paired_time"],
        np.nan,
    )
    grouped["pairing_completeness"] = np.where(
        grouped["potential_count"] > 0,
        grouped["production_shifts"] / grouped["potential_count"],
        0,
    )
    numeric = [
        "total_output",
        "weighted_yield",
        "fault_hours",
        "clean_empty_burn_hours",
        "pairing_completeness",
    ]
    grouped[numeric] = grouped[numeric].round(
        {"total_output": 2, "weighted_yield": 2, "fault_hours": 2, "clean_empty_burn_hours": 2, "pairing_completeness": 4}
    )
    return grouped.drop(columns=["paired_output", "paired_time", "potential_count"])


def trends(
    session: Session,
    dataset: Dataset,
    grain: str,
    production_lines: list[str] | None,
    furnaces: list[str] | None,
    date_from: date | None,
    date_to: date | None,
) -> dict[str, Any]:
    frame = load_records(session, dataset.id, production_lines, furnaces, date_from, date_to)
    if frame.empty:
        return {"grain": grain, "rows": [], "metadata": {"row_count": 0}}
    group_keys = ["production_date", "production_line"]
    if grain == "shift":
        group_keys.append("shift_name")
    grouped = aggregate_by(frame, group_keys).sort_values(group_keys)
    grouped["production_date"] = grouped["production_date"].dt.date.astype(str)
    return {
        "grain": grain,
        "rows": grouped.replace({np.nan: None}).to_dict("records"),
        "metadata": {
            "row_count": len(grouped),
            "dimensions": group_keys,
            "metric_definition": "加权产率=配对有效记录产量合计÷反应时间合计",
        },
    }


def furnace_ranking(
    session: Session,
    dataset: Dataset,
    grain: str,
    production_lines: list[str] | None,
    furnaces: list[str] | None,
    date_from: date | None,
    date_to: date | None,
    metric: str = "weighted_yield",
    limit: int = 50,
) -> dict[str, Any]:
    frame = load_records(session, dataset.id, production_lines, furnaces, date_from, date_to)
    if frame.empty:
        return {"grain": grain, "rows": [], "metadata": {}}
    grouped = aggregate_by(frame, ["production_line", "furnace"])
    grouped["active_days"] = (
        frame.loc[_paired(frame)]
        .groupby(["production_line", "furnace"])["production_date"]
        .nunique()
        .reindex(pd.MultiIndex.from_frame(grouped[["production_line", "furnace"]]))
        .fillna(0)
        .to_numpy()
    )
    if metric not in grouped.columns:
        raise ServiceError("INVALID_METRIC", "不支持的炉号排名指标", 422)
    ascending = metric in {"fault_hours", "clean_empty_burn_hours"}
    grouped = grouped.sort_values(metric, ascending=ascending, na_position="last").head(max(1, min(limit, 200)))
    return {
        "grain": grain,
        "rows": grouped.replace({np.nan: None}).to_dict("records"),
        "metadata": {"metric": metric, "ascending": ascending},
    }


def furnace_detail(
    session: Session,
    dataset: Dataset,
    furnace: str,
    grain: str,
    date_from: date | None,
    date_to: date | None,
) -> dict[str, Any]:
    frame = load_records(session, dataset.id, None, [furnace], date_from, date_to)
    if frame.empty:
        raise ServiceError("FURNACE_NOT_FOUND", f"未找到炉号 {furnace}", 404)
    if grain == "shift":
        metric_frame = frame.loc[_valid_metric_rows(frame)]
        group_keys = [
            "production_date",
            "production_line",
            "furnace",
            "shift_name",
            "team_normalized",
            "sequence_no",
        ]
        detail_rows = aggregate_by(metric_frame, group_keys).sort_values(["production_date", "sequence_no"])
    else:
        group_keys = ["production_date", "production_line", "furnace"]
        detail_rows = aggregate_by(frame, group_keys).sort_values("production_date")
    if not detail_rows.empty:
        detail_rows["production_date"] = detail_rows["production_date"].dt.date.astype(str)
    return {
        "grain": grain,
        "rows": detail_rows.replace({np.nan: None}).to_dict("records"),
        "metadata": {
            "furnace": furnace,
            "dimensions": group_keys,
            "summary": _aggregate_metrics(frame),
            "production_lines": sorted(frame["production_line"].unique().tolist()),
        },
    }


def filter_options(session: Session, dataset: Dataset) -> dict[str, Any]:
    frame = load_records(session, dataset.id)
    if frame.empty:
        return {"production_lines": [], "furnaces": [], "date_min": None, "date_max": None}
    lines = sorted(frame["production_line"].dropna().unique().tolist())
    furnaces_by_line: dict[str, list[str]] = {}
    for line in lines:
        furnaces_by_line[line] = sorted(frame.loc[frame["production_line"] == line, "furnace"].dropna().unique().tolist())
    dates = frame["production_date"].dt.date
    return {
        "production_lines": lines,
        "furnaces": sorted(frame["furnace"].dropna().unique().tolist()),
        "furnaces_by_line": furnaces_by_line,
        "date_min": dates.min(),
        "date_max": dates.max(),
        "complete_dates": json_loads(dataset.complete_dates_json, {}),
    }


def diagnostics(
    session: Session,
    dataset: Dataset,
    kind: str,
    grain: str,
    production_lines: list[str] | None,
    furnaces: list[str] | None,
    date_from: date | None,
    date_to: date | None,
) -> dict[str, Any]:
    frame = load_records(session, dataset.id, production_lines, furnaces, date_from, date_to)
    if frame.empty:
        return {"grain": grain, "rows": [], "metadata": {"kind": kind}}

    if kind in {"faults", "fault_heatmap"}:
        valid_faults = frame.loc[_valid_metric_rows(frame)]
        rows = (
            valid_faults.groupby(["production_date", "production_line", "furnace"], as_index=False)["fault_time"]
            .sum()
            .query("fault_time > 0")
            .sort_values("fault_time", ascending=False)
        )
        warning = float(analysis.ALERT_THRESHOLDS.get("fault_warning_hours_per_day", 8))
        critical = float(analysis.ALERT_THRESHOLDS.get("fault_critical_hours_per_day", 12))
        rows["level"] = np.select(
            [rows["fault_time"] >= critical, rows["fault_time"] >= warning],
            ["critical", "warning"],
            default="attention",
        )
        rows["production_date"] = rows["production_date"].dt.date.astype(str)
        return {
            "grain": "furnace_day",
            "rows": rows.to_dict("records"),
            "metadata": {"kind": kind, "warning_hours": warning, "critical_hours": critical},
        }

    paired = frame.loc[_paired(frame)].copy()
    if kind in {"yield_heatmap", "distribution"}:
        if kind == "yield_heatmap":
            rows = aggregate_by(paired, ["production_date", "production_line", "furnace"])
            rows["production_date"] = rows["production_date"].dt.date.astype(str)
            return {
                "grain": "furnace_day",
                "rows": rows.replace({np.nan: None}).to_dict("records"),
                "metadata": {"kind": kind},
            }
        values = paired[["production_line", "furnace", "reaction_time", "calculated_yield"]].copy()
        values = values.rename(columns={"calculated_yield": "weighted_yield"})
        return {
            "grain": "shift",
            "rows": values.replace({np.nan: None}).to_dict("records"),
            "metadata": {"kind": kind, "count": len(values)},
        }

    if kind in {"anomalies", "rules"}:
        sigma = float(analysis.ALERT_THRESHOLDS.get("anomaly_sigma", 2.0))
        minimum = analysis.configured_min_yield_rate()
        anomaly_rows: list[pd.DataFrame] = []
        for furnace_name, group in paired.groupby("furnace"):
            mean = group["calculated_yield"].mean()
            std = group["calculated_yield"].std()
            sigma_threshold = mean - sigma * std if pd.notna(std) and std > 0 else np.nan
            mask = pd.Series(False, index=group.index)
            if np.isfinite(sigma_threshold):
                mask |= group["calculated_yield"] < sigma_threshold
            if minimum is not None:
                mask |= group["calculated_yield"] < float(minimum)
            selected = group.loc[mask].copy()
            if selected.empty:
                continue
            selected["furnace_mean"] = round(float(mean), 2)
            selected["sigma_threshold"] = round(float(sigma_threshold), 2) if np.isfinite(sigma_threshold) else None
            selected["minimum_threshold"] = minimum
            selected["rule"] = "固定最低产率 + 炉号内 2σ"
            anomaly_rows.append(selected)
        if anomaly_rows:
            result = pd.concat(anomaly_rows, ignore_index=True)
            result["production_date"] = result["production_date"].dt.date.astype(str)
            columns = [
                "production_date",
                "production_line",
                "furnace",
                "team_normalized",
                "output",
                "reaction_time",
                "calculated_yield",
                "furnace_mean",
                "sigma_threshold",
                "minimum_threshold",
                "rule",
            ]
            result_rows = result[columns].replace({np.nan: None}).to_dict("records")
        else:
            result_rows = []
        return {
            "grain": "shift",
            "rows": result_rows,
            "metadata": {
                "kind": kind,
                "algorithm": "规则异常（非预测模型）",
                "sigma": sigma,
                "minimum_yield": minimum,
            },
        }

    raise ServiceError("INVALID_DIAGNOSTIC", "不支持的诊断类型", 404)
