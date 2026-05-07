# -*- coding: utf-8 -*-
"""
碳纳米管生产数据分析系统 GUI

运行：
    python gui_app.py
"""

from __future__ import annotations

import contextlib
import ctypes
import io
import os
import queue
import sys
import threading
import traceback
from pathlib import Path
from typing import Any

import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageTk
except ImportError as exc:
    Image = None
    ImageTk = None
    PIL_IMPORT_ERROR = exc
else:
    PIL_IMPORT_ERROR = None

import analysis


APP_TITLE = "碳纳米管生产数据分析系统"
BG = "#EEF3F7"
PANEL = "#FFFFFF"
PANEL_ALT = "#F7FAFC"
TEXT = "#1F2A33"
MUTED = "#6B7785"
ACCENT = "#277C73"
ACCENT_DARK = "#1E625B"
BORDER = "#D7E1E8"
HEADER = "#17384A"
ROW_ALT = "#F5F8FA"
WARNING = "#B25E00"
DANGER = "#B42318"
BASE_DPI = 96
BASE_TK_SCALING = BASE_DPI / 72


def _enable_high_dpi_awareness() -> None:
    """Ask Windows to give Tk real DPI information before the root window exists."""
    if sys.platform != "win32":
        return

    with contextlib.suppress(Exception):
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    with contextlib.suppress(Exception):
        ctypes.windll.user32.SetProcessDPIAware()


class QueueWriter:
    def __init__(self, event_queue: queue.Queue[tuple[str, Any]]) -> None:
        self.event_queue = event_queue
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self.event_queue.put(("log", line))
        return len(text)

    def flush(self) -> None:
        if self._buffer.strip():
            self.event_queue.put(("log", self._buffer.strip()))
        self._buffer = ""


class AnalysisApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self._init_ui_scaling()
        self.title(APP_TITLE)
        self._set_window_size(self, 1180, 760, 1060, 680)
        self.configure(bg=BG)

        self.event_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cycles = None
        self.loaded_input: Path | None = None
        self.output_paths: list[Path] = []
        self.preview_image: ImageTk.PhotoImage | None = None
        self._preview_original: Image.Image | None = None
        self._preview_path: Path | None = None
        self.current_preview_name: str | None = None
        self._resize_after_id: str | None = None
        self.furnace_chart_var = tk.StringVar()
        self.furnace_chart_map: dict[str, Path] = {}
        self.last_scope_prefix = "全区"
        self.generated_chart_paths: dict[str, Path] = {}
        self.cached_selected_furnaces: list[str] | None = None
        self.cached_daily_summary = None
        self.cached_monthly_summary = None
        self.cached_trend_data = None
        self.fault_warning_data: tuple[Any, Any] | None = None
        self.fault_warning_path: Path | None = None
        self.analysis_cache: dict[str, Any] = {}
        self.pending_input: Path | None = None
        self.pending_output: Path | None = None
        self.pending_options: dict[str, Any] = {}

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar(value="output")
        self.furnace_mode = tk.StringVar(value="all")
        self.selector_var = tk.StringVar()
        self.run_furnace_var = tk.BooleanVar(value=True)
        self.run_daily_var = tk.BooleanVar(value=True)
        self.run_monthly_var = tk.BooleanVar(value=True)
        self.run_furnace_daily_trend_var = tk.BooleanVar(value=False)
        self.run_anomaly_var = tk.BooleanVar(value=False)
        self.run_fault_analysis_var = tk.BooleanVar(value=False)
        self.run_fault_warning_var = tk.BooleanVar(value=True)
        self.date_preset_var = tk.StringVar(value="全部")
        self.start_date_var = tk.StringVar()
        self.end_date_var = tk.StringVar()
        self.available_dates: list[str] = []
        self.status_var = tk.StringVar(value="就绪")
        self.preview_meta_var = tk.StringVar(value="尚未生成预览")
        self.progress_var = tk.DoubleVar(value=0)

        self.stat_cycles = tk.StringVar(value="-")
        self.stat_furnaces = tk.StringVar(value="-")
        self.stat_dates = tk.StringVar(value="-")
        self.stat_lines = tk.StringVar(value="-")
        self.stat_yield = tk.StringVar(value="-")
        self.selection_count_var = tk.StringVar(value="已选 0 个炉号")

        self._configure_styles()
        self._set_default_input()
        self._build_layout()
        self._poll_events()

    def _init_ui_scaling(self) -> None:
        try:
            tk_scaling = float(self.tk.call("tk", "scaling"))
        except (tk.TclError, ValueError):
            tk_scaling = BASE_TK_SCALING
        self.ui_scale = max(1.0, tk_scaling / BASE_TK_SCALING)

    def _px(self, value: int | float) -> int:
        if value == 0:
            return 0
        return max(1, int(round(value * self.ui_scale)))

    def _pad(self, *values: int | float) -> tuple[int, ...]:
        return tuple(self._px(value) for value in values)

    def _fit_to_screen(self, width: int, height: int, margin: int) -> tuple[int, int]:
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        margin_px = self._px(margin)
        return (
            min(self._px(width), max(1, screen_w - margin_px)),
            min(self._px(height), max(1, screen_h - margin_px)),
        )

    def _set_window_size(
        self,
        window: tk.Tk | tk.Toplevel,
        width: int,
        height: int,
        min_width: int,
        min_height: int,
    ) -> None:
        target_w, target_h = self._fit_to_screen(width, height, 80)
        min_w, min_h = self._fit_to_screen(min_width, min_height, 120)
        window.geometry(f"{target_w}x{target_h}")
        window.minsize(min(min_w, target_w), min(min_h, target_h))

    def _sync_canvas_window(self, canvas: tk.Canvas, window_id: int, inner: ttk.Frame) -> None:
        inner.update_idletasks()
        width = max(1, canvas.winfo_width())
        height = max(canvas.winfo_height(), inner.winfo_reqheight(), 1)
        canvas.itemconfigure(window_id, width=width, height=height)
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        base_font = ("Microsoft YaHei UI", 10)
        small_font = ("Microsoft YaHei UI", 9)
        title_font = ("Microsoft YaHei UI", 16, "bold")
        section_font = ("Microsoft YaHei UI", 11, "bold")

        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL, relief="flat")
        style.configure("Card.TFrame", background=PANEL, relief="solid", borderwidth=self._px(1))
        style.configure("Soft.TFrame", background=PANEL_ALT, relief="flat")
        style.configure("Header.TFrame", background=HEADER)
        style.configure("Toolbar.TFrame", background=PANEL)

        style.configure("TLabel", background=BG, foreground=TEXT, font=base_font)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT, font=base_font)
        style.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=small_font)
        style.configure("SoftMuted.TLabel", background=PANEL_ALT, foreground=MUTED, font=small_font)
        style.configure("HeaderTitle.TLabel", background=HEADER, foreground="#FFFFFF", font=title_font)
        style.configure("HeaderSub.TLabel", background=HEADER, foreground="#D7E7EF", font=small_font)
        style.configure("Section.TLabel", background=PANEL, foreground=TEXT, font=section_font)
        style.configure("StatValue.TLabel", background=PANEL, foreground=ACCENT_DARK, font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("StatName.TLabel", background=PANEL, foreground=MUTED, font=small_font)
        style.configure("Preview.TLabel", background=PANEL_ALT, foreground=MUTED, font=("Microsoft YaHei UI", 11), justify="center")
        style.configure("Status.TLabel", background=PANEL, foreground=ACCENT_DARK, font=small_font)

        style.configure("TCheckbutton", background=PANEL, foreground=TEXT, font=base_font)
        style.configure("TRadiobutton", background=PANEL, foreground=TEXT, font=base_font)
        style.map("TCheckbutton", background=[("active", PANEL)], foreground=[("disabled", MUTED)])
        style.map("TRadiobutton", background=[("active", PANEL)], foreground=[("disabled", MUTED)])

        style.configure("TButton", font=base_font, padding=self._pad(11, 7), relief="flat")
        style.configure("Accent.TButton", background=ACCENT, foreground="#FFFFFF", bordercolor=ACCENT, focusthickness=0)
        style.map("Accent.TButton", background=[("active", ACCENT_DARK), ("pressed", ACCENT_DARK), ("disabled", "#A9B7C0")])
        style.configure("Primary.TButton", background=ACCENT, foreground="#FFFFFF", bordercolor=ACCENT, padding=self._pad(14, 9), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Primary.TButton", background=[("active", ACCENT_DARK), ("pressed", ACCENT_DARK), ("disabled", "#A9B7C0")])
        style.configure("Ghost.TButton", background=PANEL, foreground=TEXT, bordercolor=BORDER)
        style.map("Ghost.TButton", background=[("active", "#EDF4F7"), ("pressed", "#E5EEF2")])
        style.configure("Subtle.TButton", background="#EDF4F7", foreground=ACCENT_DARK, bordercolor="#C5D8DF")
        style.map("Subtle.TButton", background=[("active", "#DDECEF"), ("pressed", "#D3E5E9")])

        style.configure("TEntry", fieldbackground="#FFFFFF", bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=self._px(7))
        style.configure("TCombobox", fieldbackground="#FFFFFF", bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=self._px(5))
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor="#DDE6ED", bordercolor="#DDE6ED", lightcolor=ACCENT, darkcolor=ACCENT)
        style.configure("Treeview", font=small_font, rowheight=self._px(30), background="#FFFFFF", fieldbackground="#FFFFFF", foreground=TEXT, borderwidth=0)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"), background="#E6EFF4", foreground=TEXT, relief="flat", padding=self._pad(6, 5))
        style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#FFFFFF")])
        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=self._pad(0, 0, 0, 0))
        style.configure("TNotebook.Tab", font=base_font, padding=self._pad(16, 8), background="#DFE9EF")
        style.map("TNotebook.Tab", background=[("selected", PANEL), ("active", "#EEF4F7")], foreground=[("selected", TEXT), ("active", TEXT)])

    def _set_default_input(self) -> None:
        try:
            path = analysis.find_input_file()
        except Exception:
            return
        self.input_var.set(str(path.resolve()))

    def _build_layout(self) -> None:
        header = ttk.Frame(self, style="Header.TFrame", padding=self._pad(24, 14))
        header.pack(fill="x")
        ttk.Label(header, text=APP_TITLE, style="HeaderTitle.TLabel").pack(anchor="w")
        ttk.Label(header, text="导入生产数据，生成炉子级统计、每日/月汇总、趋势图和故障预警", style="HeaderSub.TLabel").pack(anchor="w", pady=self._pad(4, 0))

        main = ttk.Frame(self, padding=self._px(14))
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=0, minsize=self._px(410))  # left canvas
        main.columnconfigure(1, weight=0)                # left scrollbar
        main.columnconfigure(2, weight=1)                # right canvas (expands)
        main.columnconfigure(3, weight=0)                # right scrollbar
        main.rowconfigure(0, weight=1)

        # 左侧面板用 Canvas 包裹，支持滚动（小分辨率适配）
        left_canvas = tk.Canvas(main, bg=PANEL, highlightthickness=0, width=self._px(410))
        left_scrollbar = ttk.Scrollbar(main, orient="vertical", command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scrollbar.set)
        left_canvas.grid(row=0, column=0, sticky="nsew", padx=self._pad(0, 12))
        left_scrollbar.grid(row=0, column=1, sticky="ns")

        left = ttk.Frame(left_canvas, style="Panel.TFrame", padding=self._px(14))
        self._left_canvas = left_canvas
        self._left_window = left_canvas.create_window((0, 0), window=left, anchor="nw", tags=("inner",))
        # 鼠标滚轮绑定
        def _on_left_scroll(event):
            left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        left_canvas.bind("<Enter>", lambda _: left_canvas.bind_all("<MouseWheel>", _on_left_scroll))
        left_canvas.bind("<Leave>", lambda _: left_canvas.unbind_all("<MouseWheel>"))
        # 确保内部 frame 的宽高跟随 canvas，内容超出时仍可滚动
        left.bind("<Configure>", lambda _: self.after_idle(lambda: self._sync_canvas_window(left_canvas, self._left_window, left)))
        left_canvas.bind("<Configure>", lambda _: self.after_idle(lambda: self._sync_canvas_window(left_canvas, self._left_window, left)))

        # 右侧面板也用 Canvas 包裹，支持滚动
        right_canvas = tk.Canvas(main, bg=BG, highlightthickness=0)
        right_scrollbar = ttk.Scrollbar(main, orient="vertical", command=right_canvas.yview)
        right_canvas.configure(yscrollcommand=right_scrollbar.set)
        right_canvas.grid(row=0, column=2, sticky="nsew")
        right_scrollbar.grid(row=0, column=3, sticky="ns")

        right = ttk.Frame(right_canvas, style="TFrame")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        self._right_canvas = right_canvas
        self._right_window = right_canvas.create_window((0, 0), window=right, anchor="nw", tags=("right_inner",))
        def _on_right_scroll(event):
            right_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        right_canvas.bind("<Enter>", lambda _: right_canvas.bind_all("<MouseWheel>", _on_right_scroll))
        right_canvas.bind("<Leave>", lambda _: right_canvas.unbind_all("<MouseWheel>"))
        right.bind("<Configure>", lambda _: self.after_idle(lambda: self._sync_canvas_window(right_canvas, self._right_window, right)))
        right_canvas.bind("<Configure>", lambda _: self.after_idle(lambda: self._sync_canvas_window(right_canvas, self._right_window, right)))

        self._build_left_panel(left)
        self._build_overview_panel(right)
        self._build_result_panel(right)

    def _section(self, parent: ttk.Frame, title: str, subtitle: str = "", *, fill: str = "x", expand: bool = False) -> ttk.Frame:
        outer = ttk.Frame(parent, style="Card.TFrame", padding=self._pad(12, 10))
        outer.pack(fill=fill, expand=expand, pady=self._pad(0, 10))
        ttk.Label(outer, text=title, style="Section.TLabel").pack(anchor="w")
        if subtitle:
            ttk.Label(outer, text=subtitle, style="Muted.TLabel").pack(anchor="w", pady=self._pad(2, 8))
        body = ttk.Frame(outer, style="Panel.TFrame")
        body.pack(fill="both" if fill == "both" else "x", expand=expand, pady=self._pad(0 if subtitle else 8, 0))
        return body

    def _build_left_panel(self, parent: ttk.Frame) -> None:
        source = self._section(parent, "数据源", "选择原始数据文件和报表输出位置")
        file_row = ttk.Frame(source, style="Panel.TFrame")
        file_row.pack(fill="x", pady=self._pad(0, 8))
        file_row.columnconfigure(0, weight=1)
        ttk.Entry(file_row, textvariable=self.input_var).grid(row=0, column=0, sticky="ew", padx=self._pad(0, 8))
        ttk.Button(file_row, text="浏览", style="Subtle.TButton", command=self.choose_input).grid(row=0, column=1)

        output_row = ttk.Frame(source, style="Panel.TFrame")
        output_row.pack(fill="x", pady=self._pad(0, 10))
        output_row.columnconfigure(0, weight=1)
        ttk.Entry(output_row, textvariable=self.output_var).grid(row=0, column=0, sticky="ew", padx=self._pad(0, 8))
        ttk.Button(output_row, text="输出目录", style="Subtle.TButton", command=self.choose_output).grid(row=0, column=1)

        ttk.Button(source, text="加载数据 / 刷新炉号", style="Primary.TButton", command=self.load_data_async).pack(fill="x")

        checks = self._section(parent, "分析内容")
        check_items = [
            ("炉子级统计", self.run_furnace_var),
            ("每日汇总", self.run_daily_var),
            ("每月汇总", self.run_monthly_var),
            ("单炉每日趋势数据", self.run_furnace_daily_trend_var),
            ("低产率异常检测报告", self.run_anomaly_var),
            ("故障分析 + 故障热力图", self.run_fault_analysis_var),
            ("故障预警报告", self.run_fault_warning_var),
        ]
        for index, (text, variable) in enumerate(check_items):
            row = index // 2
            col = index % 2
            ttk.Checkbutton(checks, text=text, variable=variable).grid(row=row, column=col, sticky="w", pady=self._px(3), padx=self._pad(0, 12))
        checks.columnconfigure((0, 1), weight=1)

        date_box = self._section(parent, "日期范围", "可选全部、最近时间段或手动指定起止日期")
        date_box.columnconfigure(1, weight=1)
        date_box.columnconfigure(3, weight=1)
        ttk.Label(date_box, text="快捷", style="Muted.TLabel").grid(row=0, column=0, sticky="w", pady=self._pad(0, 6))
        self.date_preset_combo = ttk.Combobox(
            date_box,
            textvariable=self.date_preset_var,
            state="readonly",
            width=10,
            values=["全部", "近7天", "近30天", "近90天", "自定义"],
        )
        self.date_preset_combo.grid(row=0, column=1, sticky="ew", padx=self._pad(8, 0), pady=self._pad(0, 6))
        self.date_preset_combo.bind("<<ComboboxSelected>>", lambda _: self._apply_date_preset())
        ttk.Label(date_box, text="开始", style="Muted.TLabel").grid(row=1, column=0, sticky="w")
        self.start_date_combo = ttk.Combobox(date_box, textvariable=self.start_date_var, width=12)
        self.start_date_combo.grid(row=1, column=1, sticky="ew", padx=self._pad(8, 8))
        ttk.Label(date_box, text="结束", style="Muted.TLabel").grid(row=1, column=2, sticky="w")
        self.end_date_combo = ttk.Combobox(date_box, textvariable=self.end_date_var, width=12)
        self.end_date_combo.grid(row=1, column=3, sticky="ew", padx=self._pad(8, 0))
        self.start_date_combo.bind("<<ComboboxSelected>>", lambda _: self.date_preset_var.set("自定义"))
        self.end_date_combo.bind("<<ComboboxSelected>>", lambda _: self.date_preset_var.set("自定义"))

        furnace_section = self._section(parent, "炉号范围", "支持精确炉号、前缀和包含匹配", fill="both", expand=True)
        mode_row = ttk.Frame(furnace_section, style="Panel.TFrame")
        mode_row.pack(fill="x")
        ttk.Radiobutton(mode_row, text="全区炉子", value="all", variable=self.furnace_mode, command=self._update_selection_label).pack(side="left")
        ttk.Radiobutton(mode_row, text="自选炉子 / 前缀匹配", value="custom", variable=self.furnace_mode, command=self._update_selection_label).pack(side="left", padx=self._pad(16, 0))

        ttk.Label(furnace_section, text="多个炉号用逗号分隔，例如 E 或 E01,F01", style="Muted.TLabel").pack(anchor="w", pady=self._pad(9, 4))
        selector_row = ttk.Frame(furnace_section, style="Panel.TFrame")
        selector_row.pack(fill="x")
        selector_row.columnconfigure(0, weight=1)
        self.selector_entry = ttk.Entry(selector_row, textvariable=self.selector_var)
        self.selector_entry.grid(row=0, column=0, sticky="ew", padx=self._pad(0, 8))
        self.selector_entry.bind("<Return>", lambda _: self.match_furnace_selector())
        ttk.Button(selector_row, text="匹配", style="Subtle.TButton", command=self.match_furnace_selector).grid(row=0, column=1)

        list_header = ttk.Frame(furnace_section, style="Panel.TFrame")
        list_header.pack(fill="x", pady=self._pad(12, 4))
        ttk.Label(list_header, text="可用炉号", style="Panel.TLabel").pack(side="left")
        ttk.Label(list_header, textvariable=self.selection_count_var, style="Status.TLabel").pack(side="right")

        list_frame = tk.Frame(furnace_section, bg=PANEL, highlightbackground=BORDER, highlightthickness=self._px(1))
        list_frame.pack(fill="both", expand=True, pady=self._pad(0, 8))
        self.furnace_listbox = tk.Listbox(
            list_frame,
            selectmode=tk.EXTENDED,
            height=10,
            borderwidth=0,
            highlightthickness=0,
            activestyle="none",
            font=("Microsoft YaHei UI", 10),
            foreground=TEXT,
            background="#FFFFFF",
            selectbackground=ACCENT,
            selectforeground="#FFFFFF",
        )
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.furnace_listbox.yview)
        self.furnace_listbox.configure(yscrollcommand=scrollbar.set)
        self.furnace_listbox.pack(side="left", fill="both", expand=True, padx=self._px(4), pady=self._px(4))
        scrollbar.pack(side="right", fill="y")
        self.furnace_listbox.bind("<<ListboxSelect>>", lambda _: self._update_selection_label())

        actions = ttk.Frame(furnace_section, style="Panel.TFrame")
        actions.pack(fill="x")
        ttk.Button(actions, text="全选", style="Ghost.TButton", command=self.select_all_furnaces).pack(side="left")
        ttk.Button(actions, text="清空", style="Ghost.TButton", command=self.clear_furnace_selection).pack(side="left", padx=self._pad(8, 0))
        ttk.Button(actions, text="预览单炉趋势", style="Subtle.TButton", command=self._preview_single_furnace).pack(side="right")

        run_box = ttk.Frame(parent, style="Panel.TFrame")
        run_box.pack(fill="x")
        ttk.Button(run_box, text="运行分析", style="Primary.TButton", command=self.run_analysis_async).pack(fill="x")
        export_btn = ttk.Frame(run_box, style="Panel.TFrame")
        export_btn.pack(fill="x", pady=self._pad(8, 0))
        ttk.Button(export_btn, text="导出报表", style="Subtle.TButton", command=self._export_cached_reports).pack(side="left", fill="x", expand=True)
        ttk.Button(export_btn, text="打开输出目录", style="Ghost.TButton", command=self.open_output_dir).pack(side="left", fill="x", expand=True, padx=self._pad(8, 0))

    def _build_overview_panel(self, parent: ttk.Frame) -> None:
        overview = ttk.Frame(parent, style="Panel.TFrame", padding=self._pad(14, 12))
        overview.grid(row=0, column=0, sticky="ew", pady=self._pad(0, 12))
        overview.columnconfigure((0, 1, 2, 3, 4), weight=1)

        stats = [
            ("反应周期", self.stat_cycles),
            ("炉号数量", self.stat_furnaces),
            ("日期范围", self.stat_dates),
            ("平均产率 (kg/h)", self.stat_yield),
            ("生产线", self.stat_lines),
        ]
        for index, (name, variable) in enumerate(stats):
            cell = ttk.Frame(overview, style="Card.TFrame", padding=self._pad(12, 9))
            cell.grid(row=0, column=index, sticky="ew", padx=self._pad(0 if index == 0 else 10, 0))
            ttk.Label(cell, textvariable=variable, style="StatValue.TLabel").pack(anchor="w")
            ttk.Label(cell, text=name, style="StatName.TLabel").pack(anchor="w", pady=self._pad(3, 0))

        status_row = ttk.Frame(overview, style="Panel.TFrame")
        status_row.grid(row=1, column=0, columnspan=5, sticky="ew", pady=self._pad(12, 0))
        status_row.columnconfigure(1, weight=1)
        ttk.Label(status_row, text="状态", style="Panel.TLabel").grid(row=0, column=0, sticky="w", padx=self._pad(0, 12))
        ttk.Progressbar(status_row, variable=self.progress_var, mode="determinate", maximum=100).grid(row=0, column=1, sticky="ew")
        ttk.Label(status_row, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=2, sticky="e", padx=self._pad(12, 0))

    def _build_result_panel(self, parent: ttk.Frame) -> None:
        self.notebook = notebook = ttk.Notebook(parent)
        notebook.grid(row=1, column=0, sticky="nsew")

        output_tab = ttk.Frame(notebook, style="Panel.TFrame", padding=self._px(14))
        log_tab = ttk.Frame(notebook, style="Panel.TFrame", padding=self._px(14))
        self.preview_tab = preview_tab = ttk.Frame(notebook, style="Panel.TFrame", padding=self._px(14))
        preview_tab.bind("<Configure>", self._on_preview_resize)
        notebook.add(output_tab, text="输出文件")
        notebook.add(log_tab, text="运行日志")
        notebook.add(preview_tab, text="趋势图预览")

        output_tab.rowconfigure(1, weight=1)
        output_tab.columnconfigure(0, weight=1)
        output_head = ttk.Frame(output_tab, style="Panel.TFrame")
        output_head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=self._pad(0, 8))
        ttk.Label(output_head, text="分析结果", style="Section.TLabel").pack(side="left")
        ttk.Label(output_head, text="运行分析后先缓存，点击导出报表再写入文件", style="Muted.TLabel").pack(side="right")

        self.output_tree = ttk.Treeview(output_tab, columns=("name", "path"), show="headings", height=12)
        self.output_tree.heading("name", text="文件")
        self.output_tree.heading("path", text="状态 / 路径")
        self.output_tree.column("name", width=self._px(210), anchor="w")
        self.output_tree.column("path", width=self._px(520), anchor="w")
        self.output_tree.grid(row=1, column=0, sticky="nsew")
        self.output_tree.tag_configure("odd", background=ROW_ALT)
        self.output_tree.tag_configure("cache", foreground=ACCENT_DARK)
        self.output_tree.tag_configure("file", foreground=TEXT)
        self.output_tree.bind("<Double-1>", lambda _: self.open_selected_output())
        output_scroll = ttk.Scrollbar(output_tab, orient="vertical", command=self.output_tree.yview)
        self.output_tree.configure(yscrollcommand=output_scroll.set)
        output_scroll.grid(row=1, column=1, sticky="ns")

        output_buttons = ttk.Frame(output_tab, style="Panel.TFrame")
        output_buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=self._pad(12, 0))
        ttk.Button(output_buttons, text="打开选中文件", style="Ghost.TButton", command=self.open_selected_output).pack(side="left")
        ttk.Button(output_buttons, text="查看故障预警", style="Subtle.TButton", command=self.show_fault_warning_window).pack(side="left", padx=self._pad(8, 0))
        ttk.Button(output_buttons, text="打开输出目录", style="Ghost.TButton", command=self.open_output_dir).pack(side="left", padx=self._pad(8, 0))

        log_tab.rowconfigure(0, weight=1)
        log_tab.columnconfigure(0, weight=1)
        self.log_text = tk.Text(
            log_tab,
            wrap="word",
            borderwidth=0,
            highlightbackground=BORDER,
            highlightthickness=self._px(1),
            font=("Consolas", 10),
            foreground=TEXT,
            background="#FBFCFD",
            insertbackground=TEXT,
        )
        log_scroll = ttk.Scrollbar(log_tab, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll.grid(row=0, column=1, sticky="ns")

        preview_tab.rowconfigure(1, weight=1)
        preview_tab.columnconfigure(0, weight=1)

        switch = ttk.Frame(preview_tab, style="Toolbar.TFrame")
        switch.grid(row=0, column=0, sticky="ew", pady=self._pad(0, 10))
        chart_buttons = ttk.Frame(switch, style="Toolbar.TFrame")
        chart_buttons.pack(fill="x")
        ttk.Button(chart_buttons, text="炉子级统计图", style="Ghost.TButton", command=lambda: self.show_scoped_preview("furnace")).pack(side="left")
        ttk.Button(chart_buttons, text="每日趋势图", style="Ghost.TButton", command=lambda: self.show_scoped_preview("daily")).pack(side="left", padx=self._pad(8, 0))
        ttk.Button(chart_buttons, text="每月趋势图", style="Ghost.TButton", command=lambda: self.show_scoped_preview("monthly")).pack(side="left", padx=self._pad(8, 0))
        ttk.Button(chart_buttons, text="故障热力图", style="Ghost.TButton", command=lambda: self.show_scoped_preview("fault_heatmap")).pack(side="left", padx=self._pad(8, 0))
        ttk.Button(chart_buttons, text="前后20%排名", style="Ghost.TButton", command=self.show_ranking_window).pack(side="left", padx=self._pad(8, 0))
        ttk.Button(chart_buttons, text="导出当前图片", style="Accent.TButton", command=self.export_current_preview_image).pack(side="right")
        ttk.Label(chart_buttons, textvariable=self.preview_meta_var, style="Status.TLabel").pack(side="right", padx=self._pad(0, 12))

        furnace_tools = ttk.Frame(switch, style="Toolbar.TFrame")
        furnace_tools.pack(fill="x", pady=self._pad(8, 0))
        ttk.Label(furnace_tools, text="单炉图表", style="Muted.TLabel").pack(side="left")
        self.furnace_chart_combo = ttk.Combobox(furnace_tools, textvariable=self.furnace_chart_var, state="readonly", width=26)
        self.furnace_chart_combo.pack(side="left", padx=self._pad(8, 6))
        self.furnace_chart_combo.bind("<<ComboboxSelected>>", self._on_furnace_chart_select)
        ttk.Button(furnace_tools, text="显示单炉图", style="Subtle.TButton", command=self._show_selected_furnace_chart).pack(side="left")
        ttk.Button(furnace_tools, text="输出目录", style="Ghost.TButton", command=self.open_output_dir).pack(side="right")

        preview_surface = ttk.Frame(preview_tab, style="Soft.TFrame", padding=self._px(10))
        preview_surface.grid(row=1, column=0, sticky="nsew")
        preview_surface.rowconfigure(0, weight=1)
        preview_surface.columnconfigure(0, weight=1)
        self.preview_label = ttk.Label(preview_surface, text="运行分析后点击上方按钮预览趋势图\n单个炉子图表请在左侧选中炉号后点击「预览单炉趋势」", style="Preview.TLabel", anchor="center")
        self.preview_label.grid(row=0, column=0, sticky="nsew")

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
            self.cycles = None
            self.loaded_input = None
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
        self.cached_selected_furnaces = None
        self.cached_daily_summary = None
        self.cached_monthly_summary = None
        self.cached_trend_data = None
        self.fault_warning_data = None
        self.fault_warning_path = None
        self.analysis_cache.clear()
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
            self.pending_input, self.pending_output = self._read_paths_from_ui()
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
            self.run_fault_analysis_var.get(),
            self.run_fault_warning_var.get(),
        ]):
            messagebox.showwarning("请选择分析内容", "至少勾选一项分析内容。")
            return
        try:
            self.pending_input, self.pending_output = self._read_paths_from_ui()
            self.pending_options = self._collect_run_options()
        except Exception as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        self._reset_analysis_cache()
        self.log_clear()
        self._start_worker(self._worker_run_analysis, "正在运行分析...")

    def _start_worker(self, target, status: str) -> None:
        self.set_busy(True, status)
        self.worker = threading.Thread(target=target, daemon=True)
        self.worker.start()

    def _is_busy(self) -> bool:
        if self.worker and self.worker.is_alive():
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
            "run_fault_analysis": self.run_fault_analysis_var.get(),
            "run_fault_warning": self.run_fault_warning_var.get(),
        }

    def _ensure_data_loaded(self, input_path: Path) -> None:
        if self.cycles is None or self.loaded_input != input_path:
            self.cycles = analysis.load_and_clean_data(input_path)
            self.loaded_input = input_path
            self.event_queue.put(("loaded", self.cycles))

    def _worker_load_data(self) -> None:
        writer = QueueWriter(self.event_queue)
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                input_path = self.pending_input
                output_path = self.pending_output
                if input_path is None or output_path is None:
                    raise ValueError("缺少输入或输出路径")
                analysis.OUTPUT_DIR = output_path
                self.cycles = analysis.load_and_clean_data(input_path)
                self.loaded_input = input_path
            writer.flush()
            self.event_queue.put(("loaded", self.cycles))
            self.event_queue.put(("done", []))
        except Exception as exc:
            writer.flush()
            self.event_queue.put(("error", self._format_error(exc)))

    def _worker_run_analysis(self) -> None:
        writer = QueueWriter(self.event_queue)
        cache: dict[str, Any] = {}
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                input_path = self.pending_input
                output_path = self.pending_output
                if input_path is None or output_path is None:
                    raise ValueError("缺少输入或输出路径")
                analysis.OUTPUT_DIR = output_path
                self._ensure_data_loaded(input_path)
                options = self.pending_options
                cycles_for_analysis = self.cycles
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
                    selected = analysis.resolve_furnaces(self.cycles, selectors)
                    if not selected:
                        raise ValueError("未匹配到任何炉号")
                scope_prefix = analysis.scope_name(selected)
                scope_detail = "全区" if selected is None else f"{len(selected)} 个炉号：{', '.join(selected[:30])}{' ...' if len(selected) > 30 else ''}"
                scope_detail += f"，日期 {actual_start}~{actual_end}"
                print(f"分析范围：{scope_prefix}（{scope_detail}）")
                print("分析结果暂存内存，点击「导出报表」保存文件。")
                self.event_queue.put(("scope", scope_prefix))
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
                    self.event_queue.put(("progress", 42))

                if options.get("run_daily"):
                    cache["daily_summary"], cache["daily_line"] = analysis.summary_by_day(cyc, selected)
                    self.event_queue.put(("progress", 68))

                if options.get("run_monthly"):
                    cache["monthly_summary"], cache["monthly_line"] = analysis.summary_by_month(cyc, selected)
                    self.event_queue.put(("progress", 76))

                if options.get("run_furnace_daily_trend"):
                    cache["trend_data"] = analysis.furnace_daily_trend_data(cyc, selected)
                    cache["trend_summary"] = analysis.furnace_daily_trend_summary(cache["trend_data"])
                    self.event_queue.put(("progress", 86))

                if options.get("run_anomaly"):
                    cache["anomalies"] = analysis.detect_anomalies(
                        analysis.select_cycles(cyc, selected))
                    self.event_queue.put(("progress", 92))

                if options.get("run_fault_analysis"):
                    cache["fault_ranking"] = analysis.fault_ranking(cyc, selected)
                    cache["fault_weekday"] = analysis.fault_weekday_distribution(cyc, selected)
                    self.event_queue.put(("progress", 96))

                if options.get("run_fault_warning"):
                    cache["fault_warnings"], cache["fault_warning_summary"] = analysis.detect_fault_warnings(cyc, selected)
                    self.event_queue.put(("progress", 98))

            writer.flush()
            self.event_queue.put(("analysis_cache", cache))
            self.event_queue.put(("done", []))
        except Exception as exc:
            writer.flush()
            self.event_queue.put(("error", self._format_error(exc)))

    def _format_error(self, exc: Exception) -> str:
        return f"{exc}\n\n{traceback.format_exc(limit=6)}"

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.event_queue.get_nowait()
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
        self.cycles = cycles
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
        self.cached_selected_furnaces = cache.get("selected")
        self.cached_daily_summary = cache.get("daily_summary")
        self.cached_monthly_summary = cache.get("monthly_summary")
        self.cached_trend_data = cache.get("trend_data")
        self.analysis_cache = cache
        # 更新概览面板的统计数字（反映过滤后的数据）
        if "furnace_data" in cache:
            fd = cache["furnace_data"]
            self.stat_cycles.set(f"{len(fd):,}")
        if "daily_summary" in cache:
            ds = cache["daily_summary"]
            total_time = ds["总反应时间"].sum()
            total_output = ds["总产量"].sum()
            self.stat_yield.set(f"{total_output / total_time:.1f} kg/h" if total_time else "-")
        if "fault_warnings" in cache:
            self.fault_warning_data = (cache["fault_warnings"], cache["fault_warning_summary"])
            self.show_fault_warning_window()
        self._refresh_furnace_chart_list()

    def _on_done(self, outputs: list[Path]) -> None:
        cache = getattr(self, "analysis_cache", {})
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
        if "fault_ranking" in cache:
            items.append((f"故障分析 ({len(cache['fault_ranking'])} 炉)", "内存缓存"))
        if "fault_warnings" in cache:
            items.append((f"故障预警 ({len(cache['fault_warnings'])} 条)", "内存缓存"))
        if items:
            for index, (name, status) in enumerate(items):
                tags = ("cache", "odd") if index % 2 else ("cache",)
                self.output_tree.insert("", tk.END, values=(name, status), tags=tags)
            self.log(f"分析完成，{len(items)} 项结果已缓存。点击「导出报表」保存文件。")
            self.notebook.select(0)  # 自动切换到「输出文件」Tab
        elif outputs:
            self.output_paths = [Path(path) for path in outputs]
            self.populate_outputs(self.output_paths)
        else:
            self.log("数据加载完成。")
        self.set_busy(False, "完成")

    def _on_error(self, message: str) -> None:
        self.set_busy(False, "失败")
        self.log(message)
        messagebox.showerror("运行失败", message.splitlines()[0] if message else "运行失败")

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
        if self.cycles is None:
            return self.cached_selected_furnaces
        selectors = self._selectors_from_ui()
        if self.furnace_mode.get() == "all" and not selectors:
            return None
        selected = analysis.resolve_furnaces(self.cycles, selectors)
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
            self.analysis_cache.get("start_date", "") == start_text
            and self.analysis_cache.get("end_date", "") == end_text
        )
        if prefix == self.last_scope_prefix and cache_dates_match:
            if chart_type == "daily" and self.cached_daily_summary is not None:
                return self.cached_daily_summary
            if chart_type == "monthly" and self.cached_monthly_summary is not None:
                return self.cached_monthly_summary
        if self.cycles is None:
            raise ValueError("请先加载数据或运行分析")
        cycles = self._filter_cycles_by_date(self.cycles)
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
        if self.cycles is None:
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
            buf = analysis.plot_furnace_stats_chart(self._filter_cycles_by_date(self.cycles), None, selected)
        elif chart_type == "fault_heatmap":
            buf = analysis.plot_fault_heatmap(self._filter_cycles_by_date(self.cycles), None, selected)
        else:
            raise ValueError(f"未知图表类型：{chart_type}")
        image = Image.open(buf)
        image.load()
        return image

    def show_scoped_preview(self, chart_type: str) -> None:
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
        self.current_preview_name = f"{names.get(chart_type, '预览图')}_{prefix}.png"
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

    def show_ranking_window(self) -> None:
        """前后20%排名独立窗口 — 按指标分Tab展示"""
        cache = getattr(self, "analysis_cache", {})
        rankings = cache.get("furnace_rankings", {})
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
        cache = getattr(self, "analysis_cache", None)
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
        if self.cycles is None:
            try:
                self.pending_input, self.pending_output = self._read_paths_from_ui()
                self.cycles = analysis.load_and_clean_data(self.pending_input)
                self.loaded_input = self.pending_input
            except Exception as exc:
                messagebox.showerror("数据加载失败", str(exc))
                return

        first_image: Image.Image | None = None
        try:
            scoped_cycles = self._filter_cycles_by_date(self.cycles)
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
                self.current_preview_name = furnace

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
        self._preview_original = image
        self._preview_path = None
        self._render_preview_image()

    def show_preview_path(self, path: Path) -> None:
        if not path.exists():
            self.preview_label.configure(image="", text=f"未找到 {path.name}")
            self.preview_meta_var.set("图片不存在")
            self.preview_image = None
            self._preview_original = None
            return

        try:
            self._preview_original = Image.open(path)
            self._preview_path = path
            self.current_preview_name = path.name
            self.preview_meta_var.set(path.name)
            self._render_preview_image()
        except Exception as exc:
            self.preview_image = None
            self._preview_original = None
            self.preview_meta_var.set("预览失败")
            self.preview_label.configure(image="", text=f"预览失败：{exc}")

    def export_current_preview_image(self) -> None:
        if self._preview_original is None:
            messagebox.showinfo("暂无图片", "请先点击上方按钮生成预览图。")
            return
        output_dir = Path(self.output_var.get().strip() or "output")
        output_dir.mkdir(parents=True, exist_ok=True)
        file_name = self.current_preview_name or "当前预览图.png"
        path = output_dir / analysis.safe_file_part(file_name)
        if path.suffix.lower() != ".png":
            path = path.with_suffix(".png")
        try:
            self._preview_original.save(path)
        except Exception as exc:
            messagebox.showerror("导出图片失败", str(exc))
            return
        self.add_output_path(path)
        self.log(f"已导出图片：{path}")
        messagebox.showinfo("导出完成", f"图片已保存：\n{path}")

    def _on_preview_resize(self, _event: object = None) -> None:
        """窗口尺寸变化时，延迟重绘预览图（防抖300ms）"""
        if self._preview_original is None:
            return
        if self._resize_after_id:
            self.after_cancel(self._resize_after_id)
        self._resize_after_id = self.after(300, self._render_preview_image)

    def _render_preview_image(self) -> None:
        """根据当前容器尺寸重新缩放预览图片（窗口resize时自动调用）"""
        if self._preview_original is None:
            return
        self.update_idletasks()
        image = self._preview_original.copy()
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

    def log(self, message: str) -> None:
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)

    def log_clear(self) -> None:
        self.log_text.delete("1.0", tk.END)

    def open_output_dir(self) -> None:
        path = Path(self.output_var.get().strip() or "output")
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path.resolve()))

    def open_selected_output(self) -> None:
        selected = self.output_tree.selection()
        if not selected:
            messagebox.showinfo("未选择文件", "请先在输出文件列表中选择一个文件。")
            return
        values = self.output_tree.item(selected[0], "values")
        if not values:
            return
        if values[1] == "内存缓存":
            messagebox.showinfo("尚未导出", "该结果当前只在内存中，请点击左侧“导出报表”后再打开文件。")
            return
        path = Path(values[1])
        if not path.exists():
            messagebox.showwarning("文件不存在", f"找不到文件：{path}")
            return
        os.startfile(str(path))


def main() -> None:
    if PIL_IMPORT_ERROR is not None:
        print("缺少 Pillow 库，请运行：pip install Pillow")
        sys.exit(1)
    _enable_high_dpi_awareness()
    app = AnalysisApp()
    app.mainloop()


if __name__ == "__main__":
    main()
