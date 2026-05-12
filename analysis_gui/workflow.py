# -*- coding: utf-8 -*-
"""Data loading, filtering, and background analysis workflow for the GUI."""

from __future__ import annotations

import contextlib
import queue
import threading
import traceback
from pathlib import Path
from typing import Any

import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox

import analysis

from .state import QueueWriter


class WorkflowMixin:
    def choose_input(self) -> None:
        path = filedialog.askopenfilename(
            title="选择生产数据文件",
            filetypes=[
                ("生产数据", "*.xlsx *.xls *.csv"),
                ("Excel 文件", "*.xlsx *.xls"),
                ("CSV 文件", "*.csv"),
                ("所有文件", "*.*"),
            ],
        )
        if path:
            self.input_var.set(path)
            self._data.cycles = None
            self._data.loaded_input = None
            self._reset_analysis_cache()
            self._reset_stats()

    def choose_output(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_var.set(path)

    def _reset_stats(self) -> None:
        self.stat_cycles.set("-")
        self.stat_furnaces.set("-")
        self.stat_dates.set("-")
        self.stat_lines.set("-")
        self.stat_yield.set("-")
        self.furnace_listbox.delete(0, tk.END)
        self.available_dates = []
        if hasattr(self, "start_date_combo"):
            self.start_date_combo["values"] = []
            self.end_date_combo["values"] = []
        self.start_date_var.set("")
        self.end_date_var.set("")
        self._update_selection_label()

    def _reset_analysis_cache(self) -> None:
        self.generated_chart_paths.clear()
        self._data.selected_furnaces = None
        self._data.daily_summary = None
        self._data.monthly_summary = None
        self._data.trend_data = None
        self._data.cache.clear()
        self.preview_meta_var.set("尚未生成预览")

    def _populate_date_controls(self, cycles) -> None:
        self.available_dates = [pd.Timestamp(value).strftime("%Y-%m-%d") for value in sorted(cycles["日期"].dropna().unique())]
        if not self.available_dates:
            return
        if hasattr(self, "start_date_combo"):
            self.start_date_combo["values"] = self.available_dates
            self.end_date_combo["values"] = self.available_dates
        self.start_date_var.set(self.available_dates[0])
        self.end_date_var.set(self.available_dates[-1])
        self.date_preset_var.set("全部")

    def _apply_date_preset(self) -> None:
        if not self.available_dates:
            return
        preset = self.date_preset_var.get()
        end = pd.Timestamp(self.available_dates[-1])
        if preset == "全部":
            start = pd.Timestamp(self.available_dates[0])
        elif preset == "近7天":
            start = end - pd.Timedelta(days=6)
        elif preset == "近30天":
            start = end - pd.Timedelta(days=29)
        elif preset == "近90天":
            start = end - pd.Timedelta(days=89)
        else:
            return
        available = pd.to_datetime(pd.Series(self.available_dates))
        valid = available[available >= start]
        self.start_date_var.set(valid.iloc[0].strftime("%Y-%m-%d") if not valid.empty else self.available_dates[0])
        self.end_date_var.set(end.strftime("%Y-%m-%d"))

    def _parse_date_text(self, text: str, label: str) -> pd.Timestamp | None:
        if not text:
            return None
        parsed = pd.to_datetime(text, errors="coerce")
        if pd.isna(parsed):
            raise ValueError(f"{label}格式无效：{text}，请使用 YYYY-MM-DD 或从下拉列表选择")
        return pd.Timestamp(parsed).normalize()

    def _current_date_range(self) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
        start_ts = self._parse_date_text(self.start_date_var.get().strip(), "开始日期")
        end_ts = self._parse_date_text(self.end_date_var.get().strip(), "结束日期")
        if start_ts is not None and end_ts is not None and start_ts > end_ts:
            raise ValueError("开始日期不能晚于结束日期")
        return start_ts, end_ts

    def _filter_cycles_by_date(self, cycles):
        start, end = self._current_date_range()
        filtered = cycles
        if start is not None:
            filtered = filtered[filtered["日期"] >= start]
        if end is not None:
            filtered = filtered[filtered["日期"] <= end]
        if filtered.empty:
            raise ValueError("当前日期范围内没有数据")
        return filtered.copy()

    def _selected_furnaces_from_listbox(self) -> list[str]:
        return [self.furnace_listbox.get(index) for index in self.furnace_listbox.curselection()]

    def _all_furnaces_from_listbox(self) -> list[str]:
        return [self.furnace_listbox.get(index) for index in range(self.furnace_listbox.size())]

    def _update_selection_label(self) -> None:
        count = len(self._selected_furnaces_from_listbox()) if hasattr(self, "furnace_listbox") else 0
        if count > 0:
            self.furnace_mode.set("custom")
        mode = "全区" if self.furnace_mode.get() == "all" else "自选"
        self.selection_count_var.set(f"{mode} / 已选 {count} 个炉号")

    def match_furnace_selector(self) -> None:
        text = self.selector_var.get().strip()
        if not text:
            messagebox.showinfo("请输入炉号", "请输入炉号或前缀后再匹配。")
            return

        furnaces = self._all_furnaces_from_listbox()
        if not furnaces:
            messagebox.showinfo("请先加载数据", "请先点击“加载数据 / 刷新炉号”，再匹配炉号。")
            return

        matched: list[str] = []
        unmatched: list[str] = []
        for raw_part in text.split(","):
            part = raw_part.strip()
            if not part:
                continue
            part_upper = part.upper()
            exact = [furnace for furnace in furnaces if furnace.upper() == part_upper]
            prefix = [furnace for furnace in furnaces if furnace.upper().startswith(part_upper)]
            contains = [furnace for furnace in furnaces if part_upper in furnace.upper()]
            candidates = exact or prefix or contains
            if candidates:
                matched.extend(candidates)
            else:
                unmatched.append(part)

        matched = list(dict.fromkeys(matched))
        if not matched:
            messagebox.showwarning("未匹配到炉号", f"未匹配到：{', '.join(unmatched) if unmatched else text}")
            return

        self.furnace_listbox.selection_clear(0, tk.END)
        first_index: int | None = None
        matched_set = set(matched)
        for index, furnace in enumerate(furnaces):
            if furnace in matched_set:
                self.furnace_listbox.selection_set(index)
                if first_index is None:
                    first_index = index
        if first_index is not None:
            self.furnace_listbox.see(first_index)

        self.furnace_mode.set("custom")
        self._update_selection_label()
        if unmatched:
            messagebox.showwarning("部分未匹配", f"已匹配 {len(matched)} 个炉号；未匹配：{', '.join(unmatched)}")
        else:
            self.log(f"已匹配 {len(matched)} 个炉号：{', '.join(matched[:20])}{' ...' if len(matched) > 20 else ''}")

    def select_all_furnaces(self) -> None:
        self.furnace_mode.set("custom")
        self.furnace_listbox.select_set(0, tk.END)
        self._update_selection_label()

    def clear_furnace_selection(self) -> None:
        self.furnace_listbox.selection_clear(0, tk.END)
        self.selector_var.set("")
        self._update_selection_label()

    def set_busy(self, busy: bool, status: str = "") -> None:
        if busy:
            self.status_var.set(status or "处理中...")
            self.progress_var.set(12)
        else:
            self.status_var.set(status or "就绪")
            self.progress_var.set(0 if not status else 100)

    def load_data_async(self) -> None:
        if self._is_busy():
            return
        try:
            self._work.pending_input, self._work.pending_output = self._read_paths_from_ui()
        except Exception as exc:
            messagebox.showerror("路径错误", str(exc))
            return
        self.log_clear()
        self._start_worker(self._worker_load_data, "正在加载数据...")

    def run_analysis_async(self) -> None:
        if self._is_busy():
            return
        if not any([
            self.run_furnace_var.get(),
            self.run_daily_var.get(),
            self.run_monthly_var.get(),
            self.run_furnace_daily_trend_var.get(),
            self.run_anomaly_var.get(),
        ]):
            messagebox.showwarning("请选择分析内容", "至少勾选一项分析内容。")
            return
        try:
            self._work.pending_input, self._work.pending_output = self._read_paths_from_ui()
            self._work.pending_options = self._collect_run_options()
        except Exception as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        self._reset_analysis_cache()
        self.log_clear()
        self._start_worker(self._worker_run_analysis, "正在运行分析...")

    def _start_worker(self, target, status: str) -> None:
        self.set_busy(True, status)
        self._work.thread = threading.Thread(target=target, daemon=True)
        self._work.thread.start()

    def _is_busy(self) -> bool:
        if self._work.thread and self._work.thread.is_alive():
            messagebox.showinfo("正在处理", "当前任务还在运行，请等待完成。")
            return True
        return False

    def _read_paths_from_ui(self) -> tuple[Path, Path]:
        input_text = self.input_var.get().strip()
        if not input_text:
            raise ValueError("请选择输入数据文件")
        input_path = analysis.find_input_file(input_text)

        output_path = Path(self.output_var.get().strip() or "output")
        output_path.mkdir(parents=True, exist_ok=True)
        analysis.OUTPUT_DIR = output_path
        return input_path, output_path

    def _collect_run_options(self) -> dict[str, Any]:
        selectors = self._selected_furnaces_from_listbox()
        typed = self.selector_var.get().strip()
        if typed:
            selectors.append(typed)

        is_custom = self.furnace_mode.get() == "custom" or len(selectors) > 0
        if is_custom and not selectors:
            raise ValueError("自选炉子模式下，请选择炉号或输入炉号/前缀。")
        start_date, end_date = self._current_date_range()

        return {
            "furnace_mode": self.furnace_mode.get(),
            "selectors": selectors,
            "start_date": start_date.strftime("%Y-%m-%d") if start_date is not None else "",
            "end_date": end_date.strftime("%Y-%m-%d") if end_date is not None else "",
            "run_furnace": self.run_furnace_var.get(),
            "run_daily": self.run_daily_var.get(),
            "run_monthly": self.run_monthly_var.get(),
            "run_furnace_daily_trend": self.run_furnace_daily_trend_var.get(),
            "run_anomaly": self.run_anomaly_var.get(),
        }

    def _ensure_data_loaded(self, input_path: Path) -> None:
        if self._data.cycles is None or self._data.loaded_input != input_path:
            self._data.cycles = analysis.load_and_clean_data(input_path)
            self._data.loaded_input = input_path
            self._work.queue.put(("loaded", self._data.cycles))

    def _worker_load_data(self) -> None:
        writer = QueueWriter(self._work.queue)
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                input_path = self._work.pending_input
                output_path = self._work.pending_output
                if input_path is None or output_path is None:
                    raise ValueError("缺少输入或输出路径")
                analysis.OUTPUT_DIR = output_path
                self._data.cycles = analysis.load_and_clean_data(input_path)
                self._data.loaded_input = input_path
            writer.flush()
            self._work.queue.put(("loaded", self._data.cycles))
            self._work.queue.put(("done", []))
        except Exception as exc:
            writer.flush()
            self._work.queue.put(("error", self._format_error(exc)))

    def _worker_run_analysis(self) -> None:
        writer = QueueWriter(self._work.queue)
        cache: dict[str, Any] = {}
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                input_path = self._work.pending_input
                output_path = self._work.pending_output
                if input_path is None or output_path is None:
                    raise ValueError("缺少输入或输出路径")
                analysis.OUTPUT_DIR = output_path
                self._ensure_data_loaded(input_path)
                options = self._work.pending_options
                cycles_for_analysis = self._data.cycles
                start_date = pd.to_datetime(options.get("start_date"), errors="coerce") if options.get("start_date") else pd.NaT
                end_date = pd.to_datetime(options.get("end_date"), errors="coerce") if options.get("end_date") else pd.NaT
                if pd.notna(start_date):
                    cycles_for_analysis = cycles_for_analysis[cycles_for_analysis["日期"] >= pd.Timestamp(start_date).normalize()]
                if pd.notna(end_date):
                    cycles_for_analysis = cycles_for_analysis[cycles_for_analysis["日期"] <= pd.Timestamp(end_date).normalize()]
                if cycles_for_analysis.empty:
                    raise ValueError("当前日期范围内没有数据")
                actual_start = cycles_for_analysis["日期"].min().date()
                actual_end = cycles_for_analysis["日期"].max().date()
                print(f"日期范围：{actual_start} ~ {actual_end}，有效记录 {len(cycles_for_analysis)} 条")
                selectors = options.get("selectors", [])
                if options.get("furnace_mode") == "all" and not selectors:
                    selected = None
                else:
                    selected = analysis.resolve_furnaces(self._data.cycles, selectors)
                    if not selected:
                        raise ValueError("未匹配到任何炉号")
                scope_prefix = analysis.scope_name(selected)
                scope_detail = "全区" if selected is None else f"{len(selected)} 个炉号：{', '.join(selected[:30])}{' ...' if len(selected) > 30 else ''}"
                scope_detail += f"，日期 {actual_start}~{actual_end}"
                print(f"分析范围：{scope_prefix}（{scope_detail}）")
                print("分析结果暂存内存，点击「导出报表」保存文件。")
                self._work.queue.put(("scope", scope_prefix))
                cache["scope_prefix"] = scope_prefix
                cache["selected"] = selected
                cache["scope_detail"] = scope_detail
                cache["start_date"] = str(actual_start)
                cache["end_date"] = str(actual_end)
                cyc = cycles_for_analysis

                if options.get("run_furnace"):
                    data = analysis.select_cycles(cyc, selected)
                    cache["furnace_data"] = data
                    cache["furnace_monthly_avg"] = analysis.monthly_furnace_average(data)
                    cache["furnace_region_avg"] = analysis.region_monthly_average(data)
                    cache["furnace_rankings"] = analysis.rank_monthly_top_bottom(cache["furnace_monthly_avg"])
                    self._work.queue.put(("progress", 42))

                if options.get("run_daily"):
                    cache["daily_summary"], cache["daily_line"] = analysis.summary_by_day(cyc, selected)
                    self._work.queue.put(("progress", 68))

                if options.get("run_monthly"):
                    cache["monthly_summary"], cache["monthly_line"] = analysis.summary_by_month(cyc, selected)
                    self._work.queue.put(("progress", 76))

                if options.get("run_furnace_daily_trend"):
                    cache["trend_data"] = analysis.furnace_daily_trend_data(cyc, selected)
                    cache["trend_summary"] = analysis.furnace_daily_trend_summary(cache["trend_data"])
                    self._work.queue.put(("progress", 86))

                if options.get("run_anomaly"):
                    cache["anomalies"] = analysis.detect_anomalies(
                        analysis.select_cycles(cyc, selected))
                    self._work.queue.put(("progress", 92))

            writer.flush()
            self._work.queue.put(("analysis_cache", cache))
            self._work.queue.put(("done", []))
        except Exception as exc:
            writer.flush()
            self._work.queue.put(("error", self._format_error(exc)))

    def _format_error(self, exc: Exception) -> str:
        return f"{exc}\n\n{traceback.format_exc(limit=6)}"

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self._work.queue.get_nowait()
                if event == "log":
                    self.log(payload)
                elif event == "loaded":
                    self._on_loaded(payload)
                elif event == "progress":
                    self.progress_var.set(float(payload))
                elif event == "scope":
                    self.last_scope_prefix = str(payload)
                elif event == "analysis_cache":
                    self._on_analysis_cache(payload)
                elif event == "done":
                    self._on_done(payload)
                elif event == "error":
                    self._on_error(payload)
        except queue.Empty:
            pass
        self.after(120, self._poll_events)

    def _on_loaded(self, cycles) -> None:
        self._data.cycles = cycles
        furnaces = sorted(cycles["炉号"].dropna().unique())
        self.furnace_listbox.delete(0, tk.END)
        for furnace in furnaces:
            self.furnace_listbox.insert(tk.END, furnace)

        self.stat_cycles.set(f"{len(cycles):,}")
        self.stat_furnaces.set(f"{len(furnaces):,}")
        self.stat_dates.set(f"{cycles['日期'].min().date()} 至 {cycles['日期'].max().date()}")
        self.stat_lines.set(" / ".join(sorted(cycles["生产线"].dropna().unique())))
        total_time = cycles["反应时间"].sum()
        total_output = cycles["产量"].sum()
        self.stat_yield.set(f"{total_output / total_time:.1f} kg/h" if total_time else "-")
        self._populate_date_controls(cycles)
        self._update_selection_label()
        self.progress_var.set(max(self.progress_var.get(), 35))
        self._refresh_furnace_chart_list()

    def _on_analysis_cache(self, cache: dict[str, Any]) -> None:
        self.last_scope_prefix = cache.get("scope_prefix", self.last_scope_prefix)
        self._data.selected_furnaces = cache.get("selected")
        self._data.daily_summary = cache.get("daily_summary")
        self._data.monthly_summary = cache.get("monthly_summary")
        self._data.trend_data = cache.get("trend_data")
        self._data.cache = cache
        # 更新概览面板的统计数字（反映过滤后的数据）
        if "furnace_data" in cache:
            fd = cache["furnace_data"]
            self.stat_cycles.set(f"{len(fd):,}")
        if "daily_summary" in cache:
            ds = cache["daily_summary"]
            total_time = ds["总反应时间"].sum()
            total_output = ds["总产量"].sum()
            self.stat_yield.set(f"{total_output / total_time:.1f} kg/h" if total_time else "-")
        self._refresh_furnace_chart_list()

    def _on_done(self, outputs: list[Path]) -> None:
        cache = self._data.cache
        self.output_tree.delete(*self.output_tree.get_children())
        items = []
        if "furnace_data" in cache:
            n = len(cache["furnace_data"])
            items.append((f"炉子级统计 ({n} 条)", "内存缓存"))
        if "daily_summary" in cache:
            items.append((f"每日汇总 ({len(cache['daily_summary'])} 天)", "内存缓存"))
        if "monthly_summary" in cache:
            items.append((f"每月汇总 ({len(cache['monthly_summary'])} 月)", "内存缓存"))
        if "trend_data" in cache:
            items.append((f"单炉趋势数据 ({len(cache['trend_data'])} 条)", "内存缓存"))
        if "anomalies" in cache:
            items.append((f"异常检测 ({len(cache['anomalies'])} 条)", "内存缓存"))
        if items:
            for index, (name, status) in enumerate(items):
                tags = ("cache", "odd") if index % 2 else ("cache",)
                self.output_tree.insert("", tk.END, values=(name, status), tags=tags)
            self.log(f"分析完成，{len(items)} 项结果已缓存。点击「导出报表」保存文件。")
            self.notebook.select(self.output_tab)
        elif outputs:
            self.output_paths = [Path(path) for path in outputs]
            self.populate_outputs(self.output_paths)
        else:
            self.log("数据加载完成。")
        self.set_busy(False, "完成")

    def _on_error(self, message: str) -> None:
        self.set_busy(False, "失败")
        self._data.clear()
        self._preview.clear()
        self.preview_label.configure(image="", text="运行分析后点击上方按钮预览趋势图\n单个炉子图表请在左侧选中炉号后点击「预览单炉趋势」")
        self.preview_label.grid()
        if self.yield_notebook is not None:
            self.yield_notebook.destroy()
            self.yield_notebook = None
        self.log(message)
        messagebox.showerror("运行失败", message.splitlines()[0] if message else "运行失败")

