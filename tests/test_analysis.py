# -*- coding: utf-8 -*-

from pathlib import Path
import shutil
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import analysis


def write_workbook(path: Path, df: pd.DataFrame, sheet_name: str = "L3产出1月") -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)


def test_load_and_clean_data_keeps_each_shift_as_cycle(tmp_path: Path) -> None:
    """每条班次记录 = 一次启停周期，不再按天汇总"""
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

    # 两条 E01 记录各自是一个独立的周期，"总计"行被过滤
    assert len(cycles) == 2

    # 第一条：白班
    row0 = cycles.iloc[0]
    assert row0["炉号"] == "E01"
    assert row0["班组"] == "白班"
    assert row0["反应时间"] == pytest.approx(9.2)    # "9..2" 修复
    assert row0["产量"] == pytest.approx(800)
    assert row0["产率"] == pytest.approx(800 / 9.2)
    assert row0["周期序号"] == 1

    # 第二条：夜班（班组=NaN，ffill 填充为"白班"）
    row1 = cycles.iloc[1]
    assert row1["炉号"] == "E01"
    assert row1["反应时间"] == pytest.approx(10)
    assert row1["空烧时间"] == pytest.approx(1.5)
    assert row1["产量"] == pytest.approx(1000)
    assert row1["产率"] == pytest.approx(1000 / 10)
    assert row1["周期序号"] == 2


def test_load_and_clean_data_reports_file_level_missing_columns(tmp_path: Path) -> None:
    workbook = tmp_path / "bad.xlsx"
    write_workbook(workbook, pd.DataFrame({"日期": [46023], "炉号": ["E01"]}))

    with pytest.raises(ValueError, match="必需列"):
        analysis.load_and_clean_data(workbook)


def _multi_format_source() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "生产日期": "2026-07-01",
                "班组": "白班张三",
                "炉号": "E01",
                "反应时间": 8,
                "故障时间": 0,
                "空烧时间": 0,
                "产量": 800,
                "源表小时产能": 100,
            },
            {
                "生产日期": "2026-07-01",
                "班组": "夜班李四",
                "炉号": "11A-01",
                "反应时间": 6,
                "故障时间": 1,
                "空烧时间": 0,
                "产量": 540,
                "源表小时产能": 90,
            },
        ]
    )


def test_spreadsheets_detect_header_rows_aliases_xlsm_and_ods(tmp_path: Path) -> None:
    source = _multi_format_source()
    xlsx = tmp_path / "metadata.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        source.to_excel(writer, sheet_name="L3数据", index=False, startrow=2)

    cycles = analysis.load_and_clean_data(xlsx, use_cache=False)
    assert len(cycles) == 2
    assert cycles.iloc[0]["来源行号"] == 4
    assert cycles.iloc[0]["反应时间"] == pytest.approx(8)

    xlsm = tmp_path / "metadata.xlsm"
    shutil.copyfile(xlsx, xlsm)
    assert len(analysis.load_and_clean_data(xlsm, use_cache=False)) == 2

    ods = tmp_path / "metadata.ods"
    with pd.ExcelWriter(ods, engine="odf") as writer:
        source.to_excel(writer, sheet_name="L3数据", index=False)
    assert len(analysis.load_and_clean_data(ods, use_cache=False)) == 2


@pytest.mark.parametrize(
    ("suffix", "delimiter", "encoding"),
    [
        (".tsv", "\t", "utf-8-sig"),
        (".txt", "|", "utf-8"),
        (".csv", ";", "gb18030"),
    ],
)
def test_delimited_formats_detect_delimiter_encoding_and_metadata_header(
    tmp_path: Path,
    suffix: str,
    delimiter: str,
    encoding: str,
) -> None:
    source = _multi_format_source()
    path = tmp_path / f"production{suffix}"
    body = "数据来源：生产现场\n导出时间：2026-07-19\n" + source.to_csv(index=False, sep=delimiter)
    path.write_bytes(body.encode(encoding))

    cycles = analysis.load_and_clean_data(path, use_cache=False)

    assert len(cycles) == 2
    assert set(cycles["生产线"]) == {"L3", "11A"}
    assert cycles.iloc[0]["来源行号"] == 4


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


def test_vectorized_date_cleaning_rejects_out_of_range_serials() -> None:
    values = analysis.convert_excel_dates(pd.Series([46023, "2026-01-02", 999_999_999]))

    assert values.iloc[0] == pd.Timestamp("2026-01-01")
    assert values.iloc[1] == pd.Timestamp("2026-01-02")
    assert pd.isna(values.iloc[2])


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


def test_legacy_summaries_use_only_paired_records_for_weighted_yield() -> None:
    cycles = pd.DataFrame(
        {
            "日期": pd.to_datetime(["2026-01-01"] * 4),
            "年月": ["2026-01"] * 4,
            "月份": [1] * 4,
            "生产线": ["L3"] * 4,
            "炉号": ["E01"] * 4,
            "产量": [100.0, 900.0, None, 50.0],
            "反应时间": [10.0, None, 90.0, 0.0],
            "故障时间": [0.0] * 4,
            "空烧时间": [0.0] * 4,
            "降清时间": [0.0] * 4,
            "周期序号": [1, 2, 3, 4],
        }
    )

    daily, _ = analysis.summary_by_day(cycles)
    furnace_month = analysis.monthly_furnace_average(cycles)

    assert daily.iloc[0]["总产量"] == pytest.approx(1050)
    assert daily.iloc[0]["平均产率"] == pytest.approx(10)
    assert furnace_month.iloc[0]["平均产率"] == pytest.approx(10)


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
