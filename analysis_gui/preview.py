# -*- coding: utf-8 -*-
"""Chart preview windows, inline viewers, and export actions."""

from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
from typing import Any

import pandas as pd
import tkinter as tk
from tkinter import messagebox, ttk

import analysis

from .constants import BG, PANEL
from .image_support import Image, ImageTk


class PreviewMixin:
    def populate_outputs(self, paths: list[Path]) -> None:
        self.output_tree.delete(*self.output_tree.get_children())
        for index, path in enumerate(paths):
            resolved = Path(path).resolve()
            tags = ("file", "odd") if index % 2 else ("file",)
            self.output_tree.insert("", tk.END, values=(resolved.name, str(resolved)), tags=tags)

    def add_output_path(self, path: Path) -> None:
        resolved = Path(path).resolve()
        if all(Path(existing).resolve() != resolved for existing in self.output_paths):
            self.output_paths.append(resolved)
            tags = ("file", "odd") if len(self.output_tree.get_children()) % 2 else ("file",)
            self.output_tree.insert("", tk.END, values=(resolved.name, str(resolved)), tags=tags)

    def _selectors_from_ui(self) -> list[str]:
        selectors = self._selected_furnaces_from_listbox()
        typed = self.selector_var.get().strip()
        if typed:
            selectors.append(typed)
        return selectors

    def _current_selected_scope(self) -> list[str] | None:
        if self._data.cycles is None:
            return self._data.selected_furnaces
        selectors = self._selectors_from_ui()
        if self.furnace_mode.get() == "all" and not selectors:
            return None
        selected = analysis.resolve_furnaces(self._data.cycles, selectors)
        if not selected:
            raise ValueError("当前炉号范围未匹配到任何数据")
        return selected

    def _current_scope_prefix(self) -> str:
        try:
            selected = self._current_selected_scope()
        except ValueError:
            return self.last_scope_prefix
        return analysis.scope_name(selected)

    def _cached_summary_for_scope(self, chart_type: str, selected: list[str] | None):
        prefix = analysis.scope_name(selected)
        start, end = self._current_date_range()
        start_text = start.strftime("%Y-%m-%d") if start is not None else ""
        end_text = end.strftime("%Y-%m-%d") if end is not None else ""
        cache_dates_match = (
            self._data.cache.get("start_date", "") == start_text
            and self._data.cache.get("end_date", "") == end_text
        )
        if prefix == self.last_scope_prefix and cache_dates_match:
            if chart_type == "daily" and self._data.daily_summary is not None:
                return self._data.daily_summary
            if chart_type == "monthly" and self._data.monthly_summary is not None:
                return self._data.monthly_summary
        if self._data.cycles is None:
            raise ValueError("请先加载数据或运行分析")
        cycles = self._filter_cycles_by_date(self._data.cycles)
        if chart_type == "daily":
            summary, _ = analysis.summary_by_day(cycles, selected)
            return summary
        if chart_type == "monthly":
            summary, _ = analysis.summary_by_month(cycles, selected)
            return summary
        raise ValueError(f"未知汇总类型：{chart_type}")

    def _preview_dir(self) -> Path:
        d = Path(self.output_var.get().strip() or "output") / ".preview"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def generate_scoped_chart(self, chart_type: str) -> Image.Image:
        if self._data.cycles is None:
            raise ValueError("请先加载数据或运行分析")
        selected = self._current_selected_scope()
        prefix = analysis.scope_name(selected)

        buf: io.BytesIO | None = None
        if chart_type == "daily":
            summary = self._cached_summary_for_scope("daily", selected)
            buf = analysis.plot_summary_trend(summary, "日期", f"{prefix}每日生产趋势")
        elif chart_type == "monthly":
            summary = self._cached_summary_for_scope("monthly", selected)
            buf = analysis.plot_summary_trend(summary, "年月", f"{prefix}每月生产趋势")
        elif chart_type == "furnace":
            buf = analysis.plot_furnace_stats_chart(self._filter_cycles_by_date(self._data.cycles), None, selected)
        elif chart_type == "cycle_distribution":
            buf = analysis.plot_cycle_time_distribution(self._filter_cycles_by_date(self._data.cycles), None, selected)
        elif chart_type == "cycle_heatmap":
            buf = analysis.plot_cycle_heatmap(self._filter_cycles_by_date(self._data.cycles), None, selected)
        elif chart_type == "yield_heatmap":
            buf = analysis.plot_yield_heatmap(self._filter_cycles_by_date(self._data.cycles), None, selected)
        elif chart_type == "yield_comparison":
            buf = analysis.plot_furnace_yield_comparison(self._filter_cycles_by_date(self._data.cycles), None, selected)
        elif chart_type == "daily_yield_comparison":
            buf = analysis.plot_daily_furnace_yield_comparison(self._filter_cycles_by_date(self._data.cycles), None, selected)
        elif chart_type == "yield_3d":
            hl_furnace = self.furnace_highlight_var.get().strip() or None
            hl_date_str = self.date_highlight_var.get().strip() or None
            hl_date = pd.Timestamp(hl_date_str) if hl_date_str else None
            buf = analysis.plot_3d_yield_comparison(
                self._filter_cycles_by_date(self._data.cycles), None, selected,
                highlight_furnace=hl_furnace, highlight_date=hl_date)
        else:
            raise ValueError(f"未知图表类型：{chart_type}")
        image = Image.open(buf)
        image.load()
        return image

    def _hide_yield_notebook(self) -> None:
        """隐藏产率对比 Notebook，恢复普通预览 Label"""
        if self.yield_notebook is not None and self.yield_notebook.winfo_exists():
            self.yield_notebook.grid_remove()
        self.preview_label.grid()

    def show_scoped_preview(self, chart_type: str) -> None:
        self._preview.chart_type = chart_type
        self._hide_yield_notebook()
        try:
            image = self.generate_scoped_chart(chart_type)
        except Exception as exc:
            messagebox.showerror("生成图片失败", str(exc))
            return
        prefix = self._current_scope_prefix()
        names = {
            "daily": "每日趋势图",
            "monthly": "每月趋势图",
            "furnace": "炉子级统计图",
            "fault_heatmap": "故障热力图",
        }
        self._preview.name = f"{names.get(chart_type, '预览图')}_{prefix}.png"
        self.preview_meta_var.set(f"{prefix} / {names.get(chart_type, '预览图')}")
        self.log(f"预览图片：{chart_type}")
        self._show_preview_pil_image(image)
        for tab_id in self.notebook.tabs():
            if "趋势图预览" in self.notebook.tab(tab_id, "text"):
                self.notebook.select(tab_id)
                break

    def show_preview(self, file_name: str) -> None:
        output_dir = Path(self.output_var.get().strip() or "output")
        path = output_dir / file_name
        if not path.exists():
            preview_path = output_dir / ".preview" / file_name
            if preview_path.exists():
                path = preview_path
        self.show_preview_path(path)

    def show_first_generated_preview(self, outputs: list[Path]) -> None:
        self._refresh_furnace_chart_list()
        preferred = ["每日趋势图", "炉子级统计图", "单炉", "故障热力图", "每月趋势图"]
        image_paths = [Path(path) for path in outputs if Path(path).suffix.lower() == ".png" and Path(path).exists()]
        for keyword in preferred:
            for path in image_paths:
                if keyword in path.name:
                    self.show_preview_path(path)
                    return
        if image_paths:
            self.show_preview_path(image_paths[0])

    def show_first_furnace_preview(self) -> None:
        output_dir = Path(self.output_var.get().strip() or "output")
        charts: list[Path] = []
        for chart_dir in output_dir.glob("单炉每日趋势图_*"):
            charts.extend(chart_dir.glob("*.png"))
        preview_dir = output_dir / ".preview"
        if preview_dir.exists():
            charts.extend(preview_dir.glob("*_每日趋势.png"))
        charts.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        if charts:
            self.show_preview_path(charts[0])
            return
        self.preview_label.configure(image="", text="未找到单炉每日趋势图")
        self.preview_meta_var.set("未找到单炉图表")
        self.preview_image = None

    class _PilLabel(ttk.Label):
        """可自适应缩放图片的 Label"""
        def __init__(self, parent):
            super().__init__(parent, background=PANEL, anchor="center")
            self._pil_image: Image.Image | None = None
            self._tk_image: ImageTk.PhotoImage | None = None
            self.bind("<Configure>", self._on_resize)

        def set_pil(self, image: Image.Image):
            self._pil_image = image
            self._rerender()

        def _on_resize(self, _event=None):
            if self._pil_image:
                rid = getattr(self, "_resize_id", None)
                if rid:
                    with contextlib.suppress(tk.TclError):
                        self.after_cancel(rid)
                self._resize_id = self.after(200, self._rerender)

        def _rerender(self):
            if not self._pil_image:
                return
            w = self.winfo_width()
            h = self.winfo_height()
            if w < 20:
                w = 860
            if h < 20:
                h = 500
            img = self._pil_image.copy()
            img.thumbnail((w - 10, h - 10), Image.LANCZOS)
            self._tk_image = ImageTk.PhotoImage(img)
            self.configure(image=self._tk_image, text="")

    def _show_yield_comparison_inline(self) -> None:
        """在预览区展示产率对比 Notebook（内嵌，不弹窗）"""
        if self._data.cycles is None:
            messagebox.showinfo("请先加载数据", "请先加载或分析数据。")
            return
        try:
            selected = self._current_selected_scope()
        except Exception as exc:
            messagebox.showerror("炉号范围错误", str(exc))
            return

        # 隐藏旧的预览 Label
        self.preview_label.grid_remove()
        if hasattr(self, "_preview_original"):
            self._preview.original = None

        if self.yield_notebook is not None and self.yield_notebook.winfo_exists():
            self.yield_notebook.destroy()

        # 创建产率对比 Notebook
        self.yield_notebook = nb = ttk.Notebook(self.preview_container)
        nb.grid(row=0, column=0, sticky="nsew")
        nb.bind("<<NotebookTabChanged>>", self._on_yield_tab_changed)
        self.preview_meta_var.set(f"{analysis.scope_name(selected)} / 产率对比")

        for tab_name, chart_type in [
            ("炉均产率", "yield_comparison"),
            ("每日产率", "daily_yield_comparison"),
            ("三维产率", "yield_3d"),
        ]:
            tab = ttk.Frame(nb, style="Panel.TFrame", padding=self._px(6))
            nb.add(tab, text=tab_name)
            tab.rowconfigure(0, weight=1)
            tab.columnconfigure(0, weight=1)
            viewer = self._PilLabel(tab)
            viewer.grid(row=0, column=0, sticky="nsew")
            tab.after(150, lambda v=viewer, ct=chart_type: self._load_yield_view(v, ct, selected))

    def _on_yield_tab_changed(self, _event=None) -> None:
        """产率对比 Tab 切换时，更新当前图表类型以支持数据导出"""
        nb = self.yield_notebook
        if nb is None:
            return
        tab_names = {0: "yield_comparison", 1: "daily_yield_comparison", 2: "yield_3d"}
        self._preview.yield_tab = tab_names.get(nb.index(nb.select()), "yield_comparison")

    def _load_yield_view(self, viewer, chart_type: str, selected):
        try:
            cyc = self._filter_cycles_by_date(self._data.cycles)
            if chart_type == "yield_comparison":
                buf = analysis.plot_furnace_yield_comparison(cyc, None, selected)
            elif chart_type == "daily_yield_comparison":
                buf = analysis.plot_daily_furnace_yield_comparison(cyc, None, selected)
            elif chart_type == "yield_3d":
                hl_f = self.furnace_highlight_var.get().strip() or None
                hl_d = self.date_highlight_var.get().strip() or None
                buf = analysis.plot_3d_yield_comparison(cyc, None, selected,
                                                        highlight_furnace=hl_f,
                                                        highlight_date=pd.Timestamp(hl_d) if hl_d else None)
            else:
                return
            viewer.set_pil(Image.open(buf))
        except Exception as e:
            viewer.configure(image="", text=f"生成失败: {e}")

    def show_ranking_window(self) -> None:
        """前后20%排名独立窗口 — 按指标分Tab展示"""
        rankings = self._data.cache.get("furnace_rankings", {})
        summary = rankings.get("前后20汇总")
        if summary is None or summary.empty:
            messagebox.showinfo("暂无数据", "请先运行分析（勾选「炉子级统计」），数据缓存在内存中。")
            return

        win = tk.Toplevel(self)
        win.transient(self)
        win.title("前后20% 炉号排名")
        self._set_window_size(win, 950, 580, 750, 420)
        win.configure(bg=BG)

        header = ttk.Frame(win, style="Header.TFrame", padding=self._pad(20, 14))
        header.pack(fill="x")
        ttk.Label(header, text=f"前后20% 炉号排名 — {len(summary)} 条记录",
                  style="HeaderTitle.TLabel").pack(anchor="w")

        notebook = ttk.Notebook(win)
        notebook.pack(fill="both", expand=True, padx=self._px(8), pady=self._px(8))

        display_cols = ["月份", "类型", "排名", "炉号", "生产线", "反应周期数", "数值"]
        metrics = sorted(summary["指标"].dropna().unique())

        for metric in metrics:
            sub = summary[summary["指标"] == metric]
            tab = ttk.Frame(notebook, style="Panel.TFrame", padding=self._px(8))
            notebook.add(tab, text=metric.replace("平均", ""))
            tab.rowconfigure(0, weight=1)
            tab.columnconfigure(0, weight=1)

            tree = ttk.Treeview(tab, columns=display_cols, show="headings")
            tree.heading("月份", text="月份")
            tree.heading("类型", text="类型")
            tree.heading("排名", text="排名")
            tree.heading("炉号", text="炉号")
            tree.heading("生产线", text="生产线")
            tree.heading("反应周期数", text="周期数")
            tree.heading("数值", text="数值")
            for col in display_cols:
                width = 75 if col in ("月份", "类型", "排名", "生产线") else 55 if col == "反应周期数" else 80
                tree.column(col, width=self._px(width), anchor="center")
            tree.column("炉号", width=self._px(70), anchor="center")
            tree.column("数值", width=self._px(90), anchor="center")

            for _, row in sub.iterrows():
                tag = "top" if str(row.get("类型", "")) == "前20%" else "bottom"
                tree.insert("", tk.END, values=[row.get(c, "") for c in display_cols], tags=(tag,))
            tree.tag_configure("top", background="#D4EDDA", foreground="#155724")
            tree.tag_configure("bottom", background="#F8D7DA", foreground="#721C24")
            tree.grid(row=0, column=0, sticky="nsew")
            scroll_y = ttk.Scrollbar(tab, orient="vertical", command=tree.yview)
            scroll_y.grid(row=0, column=1, sticky="ns")
            tree.configure(yscrollcommand=scroll_y.set)

        btn_row = ttk.Frame(win, style="Panel.TFrame", padding=self._px(14))
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="关闭", style="Ghost.TButton", command=win.destroy).pack(side="right")

    def show_fault_heatmap_preview(self) -> None:
        output_dir = Path(self.output_var.get().strip() or "output")
        heatmaps = sorted(
            list(output_dir.glob("故障热力图_*.png")) +
            list((output_dir / ".preview").glob("故障热力图_*.png"))
        )
        if heatmaps:
            self.show_preview_path(heatmaps[-1])
            return
        self.preview_label.configure(image="", text="未找到故障热力图")
        self.preview_image = None

    def show_fault_warning_window(self) -> None:
        """故障预警独立窗口：展示预警汇总和预警明细"""
        if not self.fault_warning_data:
            messagebox.showinfo("暂无数据", "请先运行分析（勾选「故障预警报告」），或加载已有数据。")
            return

        warnings, summary = self.fault_warning_data
        if warnings is None or warnings.empty:
            messagebox.showinfo("无预警", "当前数据未触发任何故障预警。")
            return

        win = tk.Toplevel(self)
        win.transient(self)
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.title("故障预警详情")
        self._set_window_size(win, 1050, 620, 800, 400)
        win.configure(bg=BG)

        # 标题
        header = ttk.Frame(win, style="Header.TFrame", padding=self._pad(20, 14))
        header.pack(fill="x")
        serious_count = int((warnings["预警级别"] == "严重").sum())
        ttk.Label(header, text=f"故障预警报告 — 共 {len(warnings)} 条预警（严重 {serious_count} 条）",
                  style="HeaderTitle.TLabel").pack(anchor="w")

        content = ttk.Frame(win, style="TFrame", padding=self._px(14))
        content.pack(fill="both", expand=True)
        content.rowconfigure(1, weight=1)
        content.columnconfigure(0, weight=1)

        # 上半部分：预警汇总
        sum_frame = ttk.Frame(content, style="Panel.TFrame", padding=self._px(10))
        sum_frame.grid(row=0, column=0, sticky="ew", pady=self._pad(0, 10))
        ttk.Label(sum_frame, text="预警汇总", style="Section.TLabel").pack(anchor="w", pady=self._pad(0, 6))

        sum_tree = ttk.Treeview(sum_frame, columns=list(summary.columns), show="headings", height=5)
        for col in summary.columns:
            sum_tree.heading(col, text=col)
            sum_tree.column(col, width=self._px(min(160, max(80, len(str(col)) * 16))), anchor="center")
        for _, row in summary.iterrows():
            values = list(row)
            tag = "critical" if row.get("预警级别") == "严重" else ""
            sum_tree.insert("", tk.END, values=values, tags=(tag,))
        sum_tree.tag_configure("critical", background="#FFD6D6", foreground="#8B0000")
        sum_tree.pack(fill="x")
        sum_scroll = ttk.Scrollbar(sum_frame, orient="vertical", command=sum_tree.yview)
        sum_tree.configure(yscrollcommand=sum_scroll.set)

        # 下半部分：预警明细
        detail_frame = ttk.Frame(content, style="Panel.TFrame", padding=self._px(10))
        detail_frame.grid(row=1, column=0, sticky="nsew")
        detail_frame.rowconfigure(0, weight=0)
        detail_frame.rowconfigure(1, weight=1)
        detail_frame.columnconfigure(0, weight=1)
        ttk.Label(detail_frame, text="预警明细", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=self._pad(0, 6))

        show_cols = ["预警级别", "预警类型", "日期", "年月", "生产线", "炉号", "故障时间", "阈值数值", "阈值单位", "说明"]
        detail_tree = ttk.Treeview(detail_frame, columns=show_cols, show="headings")
        col_widths = {"预警级别": 70, "预警类型": 140, "日期": 100, "年月": 70, "生产线": 50,
                      "炉号": 70, "故障时间": 80, "阈值数值": 65, "阈值单位": 55, "说明": 360}
        for col in show_cols:
            detail_tree.heading(col, text=col)
            detail_tree.column(col, width=self._px(col_widths.get(col, 100)), anchor="center" if col != "说明" else "w")
        for _, row in warnings.iterrows():
            tag = "critical" if row["预警级别"] == "严重" else "warning"
            detail_tree.insert("", tk.END, values=[row.get(c, "") for c in show_cols], tags=(tag,))
        detail_tree.tag_configure("critical", background="#FFD6D6", foreground="#8B0000")
        detail_tree.tag_configure("warning", background="#FFF3CD", foreground="#856404")
        detail_tree.grid(row=1, column=0, sticky="nsew")
        detail_scroll_y = ttk.Scrollbar(detail_frame, orient="vertical", command=detail_tree.yview)
        detail_scroll_y.grid(row=1, column=1, sticky="ns")
        detail_scroll_x = ttk.Scrollbar(detail_frame, orient="horizontal", command=detail_tree.xview)
        detail_scroll_x.grid(row=2, column=0, sticky="ew")
        detail_tree.configure(yscrollcommand=detail_scroll_y.set, xscrollcommand=detail_scroll_x.set)

        # 底部按钮
        btn_row = ttk.Frame(win, style="Panel.TFrame", padding=self._px(14))
        btn_row.pack(fill="x")
        if self.fault_warning_path and self.fault_warning_path.exists():
            ttk.Button(btn_row, text="打开 Excel 文件", style="Ghost.TButton",
                       command=lambda: os.startfile(str(self.fault_warning_path.resolve()))).pack(side="left")
        ttk.Button(btn_row, text="关闭", style="Ghost.TButton", command=win.destroy).pack(side="right")

    def _export_cached_reports(self) -> None:
        """将缓存的分析结果统一写入磁盘（Excel 报表）"""
        cache = self._data.cache
        if not cache:
            messagebox.showinfo("暂无缓存", "请先运行分析（勾选分析项后点击「运行分析」）。")
            return

        output_dir = Path(self.output_var.get().strip() or "output")
        output_dir.mkdir(parents=True, exist_ok=True)
        analysis.OUTPUT_DIR = output_dir
        prefix = cache.get("scope_prefix", "全区")
        selected = cache.get("selected")
        exported: list[Path] = []

        try:
            if "furnace_data" in cache:
                path = output_dir / f"炉子级统计_{prefix}.xlsx"
                with pd.ExcelWriter(path, engine="openpyxl") as writer:
                    analysis.write_dataframe(writer, cache["furnace_data"].sort_values(["日期", "生产线", "炉号", "周期序号"]), "反应周期明细")
                    analysis.write_dataframe(writer, cache["furnace_monthly_avg"], "月度炉子平均")
                    analysis.write_dataframe(writer, cache["furnace_region_avg"], f"{prefix}各月平均")
                    rankings = cache.get("furnace_rankings", {})
                    analysis.write_dataframe(writer, rankings.get("前后20汇总", pd.DataFrame()), "前后20汇总")
                    for name, result in rankings.items():
                        if name == "前后20汇总":
                            continue
                        analysis.write_dataframe(writer, result, name)
                analysis.autosize_workbook(path)
                exported.append(path)
                self.log(f"  已导出：{path.name}")

            if "daily_summary" in cache:
                path = output_dir / ("每日汇总.xlsx" if prefix == "全区" else f"每日汇总_{prefix}.xlsx")
                with pd.ExcelWriter(path, engine="openpyxl") as writer:
                    analysis.write_dataframe(writer, cache["daily_summary"], f"{prefix}每日汇总")
                    analysis.write_dataframe(writer, cache.get("daily_line", cache["daily_summary"]), "生产线每日汇总")
                    if "daily_line" in cache:
                        for line in sorted(cache["daily_line"]["生产线"].unique()):
                            analysis.write_dataframe(writer, cache["daily_line"][cache["daily_line"]["生产线"] == line], f"{line}每日汇总")
                analysis.autosize_workbook(path)
                exported.append(path)
                self.log(f"  已导出：{path.name}")

            if "monthly_summary" in cache:
                path = output_dir / ("每月汇总.xlsx" if prefix == "全区" else f"每月汇总_{prefix}.xlsx")
                with pd.ExcelWriter(path, engine="openpyxl") as writer:
                    analysis.write_dataframe(writer, cache["monthly_summary"], f"{prefix}每月汇总")
                    analysis.write_dataframe(writer, cache.get("monthly_line", cache["monthly_summary"]), "生产线每月汇总")
                    if "monthly_line" in cache:
                        for line in sorted(cache["monthly_line"]["生产线"].unique()):
                            analysis.write_dataframe(writer, cache["monthly_line"][cache["monthly_line"]["生产线"] == line], f"{line}每月汇总")
                analysis.autosize_workbook(path)
                exported.append(path)
                self.log(f"  已导出：{path.name}")

            if "trend_data" in cache:
                path = output_dir / f"单炉每日趋势数据_{prefix}.xlsx"
                with pd.ExcelWriter(path, engine="openpyxl") as writer:
                    analysis.write_dataframe(writer, cache["trend_data"], "单炉每日明细")
                    analysis.write_dataframe(writer, cache.get("trend_summary", cache["trend_data"]), "单炉汇总")
                analysis.autosize_workbook(path)
                exported.append(path)
                self.log(f"  已导出：{path.name}")

            if "anomalies" in cache:
                path = output_dir / f"异常检测报告_{prefix}.xlsx"
                anomalies = cache["anomalies"]
                by_furnace = (
                    anomalies.groupby(["生产线", "炉号"], as_index=False)
                    .agg(异常次数=("日期", "count"), 最大偏差σ=("偏差σ", "max"), 最低产率=("产率", "min"))
                    .sort_values(["异常次数", "最大偏差σ"], ascending=[False, False])
                    if not anomalies.empty
                    else pd.DataFrame(columns=["生产线", "炉号", "异常次数", "最大偏差σ", "最低产率"])
                )
                with pd.ExcelWriter(path, engine="openpyxl") as writer:
                    analysis.write_dataframe(writer, anomalies, "异常周期明细")
                    analysis.write_dataframe(writer, by_furnace, "炉号异常汇总")
                analysis.autosize_workbook(path)
                exported.append(path)
                self.log(f"  已导出：{path.name}")

            if "fault_ranking" in cache:
                path = output_dir / f"故障分析_{prefix}.xlsx"
                with pd.ExcelWriter(path, engine="openpyxl") as writer:
                    analysis.write_dataframe(writer, cache["fault_ranking"], "故障炉号排名")
                    analysis.write_dataframe(writer, cache.get("fault_weekday", pd.DataFrame()), "故障星期分布")
                analysis.autosize_workbook(path)
                exported.append(path)
                self.log(f"  已导出：{path.name}")

            if "fault_warnings" in cache:
                path = output_dir / f"故障预警_{prefix}.xlsx"
                with pd.ExcelWriter(path, engine="openpyxl") as writer:
                    analysis.write_dataframe(writer, cache["fault_warnings"], "故障预警明细")
                    analysis.write_dataframe(writer, cache["fault_warning_summary"], "预警汇总")
                analysis.autosize_workbook(path)
                exported.append(path)
                self.fault_warning_path = path
                self.log(f"  已导出：{path.name}")

        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))
            return

        if exported:
            self.output_paths = [Path(p) for p in exported]
            self.populate_outputs(self.output_paths)
            self.log(f"导出完成！共 {len(exported)} 个文件 → {output_dir}")
            messagebox.showinfo("导出完成", f"已导出 {len(exported)} 个报表文件到：\n{output_dir}")
        else:
            messagebox.showinfo("无数据", "缓存中没有可导出的数据。")

    def _preview_single_furnace(self) -> None:
        """左侧面板按钮：选中炉子后实时生成单炉趋势图并在预览区显示"""
        selected = self._selected_furnaces_from_listbox()
        if not selected:
            messagebox.showinfo("请选择炉号", "请先在炉号列表中选中要预览的炉子（可多选）。")
            return
        if self._data.cycles is None:
            try:
                self._work.pending_input, self._work.pending_output = self._read_paths_from_ui()
                self._data.cycles = analysis.load_and_clean_data(self._work.pending_input)
                self._data.loaded_input = self._work.pending_input
            except Exception as exc:
                messagebox.showerror("数据加载失败", str(exc))
                return

        first_image: Image.Image | None = None
        try:
            scoped_cycles = self._filter_cycles_by_date(self._data.cycles)
        except Exception as exc:
            messagebox.showerror("日期范围错误", str(exc))
            return
        for furnace in selected:
            furnace_data = scoped_cycles[scoped_cycles["炉号"] == furnace]
            if furnace_data.empty:
                self.log(f"  警告：炉号 {furnace} 无数据，跳过")
                continue
            buf = analysis.plot_single_furnace_daily_trend(furnace_data)  # 纯内存，不写盘
            image = Image.open(buf)
            image.load()
            if first_image is None:
                first_image = image
                self._preview.name = furnace

        if first_image:
            self._show_preview_pil_image(first_image)
            for tab_id in self.notebook.tabs():
                if "趋势图预览" in self.notebook.tab(tab_id, "text"):
                    self.notebook.select(tab_id)
                    break
        else:
            messagebox.showwarning("无数据", "选中的炉子没有有效数据。")

    def _refresh_furnace_chart_list(self) -> None:
        """扫描输出目录和预览目录，填充单炉趋势图下拉列表"""
        output_dir = Path(self.output_var.get().strip() or "output")
        # 扫描旧目录结构 + 新 .preview 目录
        png_paths: list[Path] = []
        for chart_dir in output_dir.glob("单炉每日趋势图_*"):
            png_paths.extend(chart_dir.glob("*.png"))
        preview_dir = output_dir / ".preview"
        if preview_dir.exists():
            png_paths.extend(preview_dir.glob("*_每日趋势.png"))
        png_paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        current = self.furnace_chart_var.get()
        self.furnace_chart_map.clear()
        seen: set[str] = set()
        names: list[str] = []
        for png_path in png_paths:
            furnace_name = png_path.stem.replace("_每日趋势", "").replace("_", " ")
            if furnace_name in seen:
                continue
            seen.add(furnace_name)
            self.furnace_chart_map[furnace_name] = png_path
            names.append(furnace_name)
        if hasattr(self, "furnace_chart_combo"):
            self.furnace_chart_combo["values"] = names
            if names:
                self.furnace_chart_combo.set(current if current in self.furnace_chart_map else names[0])
            else:
                self.furnace_chart_combo.set("")
        if names:
            self._show_selected_furnace_chart()

    def _on_furnace_chart_select(self, _event: object = None) -> None:
        """下拉框选择事件：选中即预览"""
        self._show_selected_furnace_chart()

    def _show_selected_furnace_chart(self) -> None:
        """显示当前下拉框选中的单炉趋势图"""
        name = self.furnace_chart_var.get()
        if name and name in self.furnace_chart_map:
            self.show_preview_path(self.furnace_chart_map[name])
        else:
            self.preview_label.configure(image="", text="请先运行单炉每日趋势图分析，然后点击刷新列表")
            self.preview_meta_var.set("未选择单炉图表")

    def _show_preview_pil_image(self, image: Image.Image) -> None:
        self._hide_yield_notebook()
        self._preview.original = image
        self._preview.path = None
        self._render_preview_image()

    def show_preview_path(self, path: Path) -> None:
        self._hide_yield_notebook()
        if not path.exists():
            self.preview_label.configure(image="", text=f"未找到 {path.name}")
            self.preview_meta_var.set("图片不存在")
            self.preview_image = None
            self._preview.original = None
            return

        try:
            self._preview.original = Image.open(path)
            self._preview.path = path
            self._preview.name = path.name
            self.preview_meta_var.set(path.name)
            self._render_preview_image()
        except Exception as exc:
            self.preview_image = None
            self._preview.original = None
            self.preview_meta_var.set("预览失败")
            self.preview_label.configure(image="", text=f"预览失败：{exc}")

    def _export_chart_data(self) -> None:
        """将当前预览图表的原始数据导出为 Excel"""
        chart_type = self._preview.chart_type
        if self.yield_notebook is not None and self.yield_notebook.winfo_ismapped():
            chart_type = self._preview.yield_tab
        if chart_type is None:
            messagebox.showinfo("暂无数据", "请先点击上方按钮生成预览图。")
            return

        output_dir = Path(self.output_var.get().strip() or "output")
        output_dir.mkdir(parents=True, exist_ok=True)
        analysis.OUTPUT_DIR = output_dir
        selected = self._current_selected_scope()
        cyc = self._filter_cycles_by_date(self._data.cycles)
        data_name_map = {
            "daily": ("summary_by_day", "每日汇总数据"),
            "monthly": ("summary_by_month", "每月汇总数据"),
            "furnace": ("monthly_furnace_average", "炉子月度平均"),
            "cycle_distribution": ("detect_cycle_boundaries", "周期分布数据"),
            "cycle_heatmap": ("raw_cycle_data", "周期热力图数据"),
            "yield_heatmap": ("raw_cycle_data", "产率热力图数据"),
            "yield_comparison": ("raw_yield_comparison", "炉均产率对比数据"),
            "daily_yield_comparison": ("raw_daily_yield_comparison", "每日产率对比数据"),
            "yield_3d": ("raw_3d_yield_data", "三维产率数据"),
        }

        info = data_name_map.get(chart_type, (None, "图表数据"))
        name = info[1]

        try:
            if chart_type in ("daily", "monthly"):
                data, _ = analysis.summary_by_day(cyc, selected) if chart_type == "daily" else analysis.summary_by_month(cyc, selected)
            elif chart_type == "furnace":
                data = analysis.monthly_furnace_average(analysis.select_cycles(cyc, selected))
            elif chart_type == "cycle_distribution":
                data = analysis.detect_cycle_boundaries(analysis.select_cycles(cyc, selected))
            elif chart_type in ("cycle_heatmap", "yield_heatmap"):
                value_col = "反应时间" if chart_type == "cycle_heatmap" else "产率"
                data = analysis.select_cycles(cyc, selected).pivot_table(
                    index="炉号", columns="日期", values=value_col, aggfunc="mean")
            elif chart_type == "yield_comparison":
                data = analysis.select_cycles(cyc, selected).groupby("炉号")["产率"].mean().sort_values().to_frame("平均产率")
            elif chart_type in ("daily_yield_comparison", "yield_3d"):
                data = analysis.select_cycles(cyc, selected).pivot_table(
                    index="日期", columns="炉号", values="产率", aggfunc="mean")
            else:
                data = analysis.select_cycles(cyc, selected)
                name = "周期明细数据"
        except Exception as e:
            messagebox.showerror("数据生成失败", str(e))
            return

        if data is None or (hasattr(data, "empty") and data.empty):
            messagebox.showinfo("无数据", "当前图表没有可导出的数据。")
            return

        path = output_dir / f"{analysis.scope_name(selected)}_{name}.xlsx"
        analysis.OUTPUT_DIR = output_dir
        try:
            if isinstance(data, pd.DataFrame):
                data.to_excel(path, index=True)
                analysis.autosize_workbook(path)
            else:
                raise TypeError("数据格式错误")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))
            return

        self.add_output_path(path)
        self.log(f"已导出图表数据：{path}")
        messagebox.showinfo("导出完成", f"{name} 已保存：\n{path}")

    def export_current_preview_image(self) -> None:
        if self._preview.original is None:
            messagebox.showinfo("暂无图片", "请先点击上方按钮生成预览图。")
            return
        output_dir = Path(self.output_var.get().strip() or "output")
        output_dir.mkdir(parents=True, exist_ok=True)
        file_name = self._preview.name or "当前预览图.png"
        path = output_dir / analysis.safe_file_part(file_name)
        if path.suffix.lower() != ".png":
            path = path.with_suffix(".png")
        try:
            self._preview.original.save(path)
        except Exception as exc:
            messagebox.showerror("导出图片失败", str(exc))
            return
        self.add_output_path(path)
        self.log(f"已导出图片：{path}")
        messagebox.showinfo("导出完成", f"图片已保存：\n{path}")

    def _on_preview_resize(self, _event: object = None) -> None:
        """窗口尺寸变化时，延迟重绘预览图（防抖300ms）"""
        if self._preview.original is None:
            return
        if self._preview.resize_after_id:
            self.after_cancel(self._preview.resize_after_id)
        self._preview.resize_after_id = self.after(300, self._render_preview_image)

    def _render_preview_image(self) -> None:
        """根据当前容器尺寸重新缩放预览图片（窗口resize时自动调用）"""
        if self._preview.original is None:
            return
        self.update_idletasks()
        image = self._preview.original.copy()
        parent = self.preview_label.master
        container_w = parent.winfo_width() if parent.winfo_width() > 10 else 860
        container_h = parent.winfo_height() if parent.winfo_height() > 10 else 560
        max_w = max(self._px(240), container_w - self._px(20))
        max_h = max(self._px(240), container_h - self._px(20))
        image.thumbnail((max_w, max_h), Image.LANCZOS)
        if self.preview_image is not None:
            del self.preview_image
        self.preview_image = ImageTk.PhotoImage(image)
        self.preview_label.configure(image=self.preview_image, text="")

