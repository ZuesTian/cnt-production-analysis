# -*- coding: utf-8 -*-

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import analysis


def write_workbook(path: Path, df: pd.DataFrame, sheet_name: str = "L3产出1月") -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)


def test_load_and_clean_data_merges_same_day_furnace_cycles(tmp_path: Path) -> None:
    source = pd.DataFrame(
        [
            {
                "日期": 46023,
                "班组": "白班",
                "炉号": "E01",
                "生产时间": "9..2",
                "设备故障影响时间": np.nan,
                "停机清理空烧": np.nan,
                "产量": "800",
                "小时产能": 86.96,
            },
            {
                "日期": 46023,
                "班组": np.nan,
                "炉号": "E01",
                "生产时间": " 10 ",
                "设备故障影响时间": np.nan,
                "停机清理空烧": "1.5",
                "产量": "1000",
                "小时产能": 100,
            },
            {
                "日期": 46023,
                "班组": np.nan,
                "炉号": "总计",
                "生产时间": 19.2,
                "设备故障影响时间": 0,
                "停机清理空烧": 1.5,
                "产量": 1800,
                "小时产能": 93.75,
            },
        ]
    )
    workbook = tmp_path / "sample.xlsx"
    write_workbook(workbook, source)

    cycles = analysis.load_and_clean_data(workbook)

    assert len(cycles) == 1
    row = cycles.iloc[0]
    assert row["炉号"] == "E01"
    assert row["日期"] == pd.Timestamp("2026-01-01")
    assert row["生产线"] == "L3"
    assert row["原始记录数"] == 2
    assert row["来源行号"] == "2,3"
    assert row["反应时间"] == pytest.approx(19.2)
    assert row["空烧时间"] == pytest.approx(1.5)
    assert row["降清时间"] == pytest.approx(1.5)
    assert row["故障时间"] == pytest.approx(0)
    assert row["产量"] == pytest.approx(1800)
    assert row["产率"] == pytest.approx(1800 / 19.2)


def test_load_and_clean_data_reports_file_level_missing_columns(tmp_path: Path) -> None:
    workbook = tmp_path / "bad.xlsx"
    write_workbook(workbook, pd.DataFrame({"日期": [46023], "炉号": ["E01"]}))

    with pytest.raises(ValueError, match="必需列"):
        analysis.load_and_clean_data(workbook)


def test_resolve_furnaces_supports_exact_and_prefix() -> None:
    cycles = pd.DataFrame({"炉号": ["E01", "E02", "F01"]})

    assert analysis.resolve_furnaces(cycles, ["E01,F"]) == ["E01", "F01"]
    assert analysis.resolve_furnaces(cycles, ["E"]) == ["E01", "E02"]


def test_scope_name_and_production_line_are_unambiguous() -> None:
    first = ["E01", "E02", "E03", "E04", "E05", "E06", "E08"]
    second = ["E01", "E02", "E03", "E04", "E05", "E07", "E08"]

    assert analysis.scope_name(first).startswith("自选7炉_")
    assert analysis.scope_name(first) != analysis.scope_name(second)
    assert analysis.production_line_from_furnace("11A17", "L3") == "11A"
    assert analysis.production_line_from_furnace("E01", "11A") == "L3"


def test_furnace_daily_trend_summary_uses_weighted_yield() -> None:
    trend_data = pd.DataFrame(
        {
            "日期": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "生产线": ["L3", "L3"],
            "炉号": ["E01", "E01"],
            "产量": [100, 300],
            "反应时间": [10, 30],
            "故障时间": [0, 1],
            "空烧时间": [0, 2],
            "降清时间": [0, 3],
            "产率": [10, 999],
        }
    )

    summary = analysis.furnace_daily_trend_summary(trend_data)

    assert summary.iloc[0]["平均产率"] == pytest.approx(10)


def test_anomaly_detection_and_fault_ranking() -> None:
    cycles = pd.DataFrame(
        {
            "日期": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]),
            "年月": ["2026-01"] * 4,
            "生产线": ["L3"] * 4,
            "炉号": ["E01"] * 4,
            "班组": ["白班"] * 4,
            "产量": [1000, 980, 990, 100],
            "反应时间": [10, 10, 10, 10],
            "故障时间": [0, 2, 0, 5],
            "空烧时间": [0, 0, 0, 0],
            "降清时间": [0, 0, 0, 0],
            "产率": [100, 98, 99, 10],
            "来源工作表": ["测试"] * 4,
            "来源行号": ["2", "3", "4", "5"],
        }
    )

    anomalies = analysis.detect_anomalies(cycles, sigma=1.0)
    assert len(anomalies) == 1
    assert anomalies.iloc[0]["产率"] == 10
    assert "低于最低产率阈值" in anomalies.iloc[0]["异常类型"]

    ranking = analysis.fault_ranking(cycles)
    assert ranking.iloc[0]["故障总时间"] == pytest.approx(7)
    assert ranking.iloc[0]["故障次数"] == 2


def test_selected_furnace_summary_and_fault_warning() -> None:
    cycles = pd.DataFrame(
        {
            "日期": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-01-02"]),
            "年月": ["2026-01", "2026-01", "2026-01"],
            "生产线": ["L3", "L3", "L3"],
            "炉号": ["E01", "E02", "E01"],
            "班组": ["白班", "白班", "夜班"],
            "产量": [100, 200, 110],
            "反应时间": [10, 20, 11],
            "故障时间": [9, 0, 13],
            "空烧时间": [0, 0, 0],
            "降清时间": [0, 0, 0],
            "产率": [10, 10, 10],
            "来源工作表": ["测试"] * 3,
            "来源行号": ["2", "3", "4"],
        }
    )

    daily_all, _ = analysis.summary_by_day(cycles, ["E01"])
    assert daily_all["总产量"].sum() == 210
    assert daily_all["总故障时间"].sum() == 22

    warnings, summary = analysis.detect_fault_warnings(cycles, ["E01"])
    assert not warnings.empty
    assert "阈值单位" in warnings.columns
    assert set(warnings["阈值单位"]) <= {"小时", "天"}
    assert set(warnings["炉号"]) == {"E01"}
    assert "严重" in set(warnings["预警级别"])
    assert summary["预警次数"].sum() == len(warnings)
