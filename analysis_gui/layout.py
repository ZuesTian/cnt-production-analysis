# -*- coding: utf-8 -*-
"""Tk layout and style construction for the analysis GUI."""

from __future__ import annotations

from pathlib import Path

import tkinter as tk
from tkinter import ttk

from .constants import (
    ACCENT,
    ACCENT_DARK,
    BASE_TK_SCALING,
    BG,
    BORDER,
    DANGER,
    HEADER,
    MUTED,
    PANEL,
    PANEL_ALT,
    ROW_ALT,
    TEXT,
    WARNING,
)


class LayoutMixin:
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
        title_font = ("Microsoft YaHei UI", 17, "bold")
        section_font = ("Microsoft YaHei UI", 11, "bold")

        self.option_add("*Font", base_font)
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL, relief="flat")
        style.configure("Card.TFrame", background=PANEL, relief="solid", borderwidth=self._px(1))
        style.configure("StatCard.TFrame", background=PANEL, relief="solid", borderwidth=self._px(1))
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

        style.configure("TButton", font=base_font, padding=self._pad(11, 7), relief="flat", focusthickness=0)
        style.configure("Accent.TButton", background=ACCENT, foreground="#FFFFFF", bordercolor=ACCENT, focusthickness=0)
        style.map("Accent.TButton", background=[("active", ACCENT_DARK), ("pressed", ACCENT_DARK), ("disabled", "#A9B7C0")])
        style.configure("Primary.TButton", background=ACCENT, foreground="#FFFFFF", bordercolor=ACCENT, padding=self._pad(14, 9), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Primary.TButton", background=[("active", ACCENT_DARK), ("pressed", ACCENT_DARK), ("disabled", "#A9B7C0")])
        style.configure("Ghost.TButton", background=PANEL, foreground=TEXT, bordercolor=BORDER)
        style.map("Ghost.TButton", background=[("active", "#EEF4F7"), ("pressed", "#E6EEF2")])
        style.configure("Subtle.TButton", background="#EAF3F2", foreground=ACCENT_DARK, bordercolor="#BDD6D4")
        style.map("Subtle.TButton", background=[("active", "#DCEDEB"), ("pressed", "#D0E4E1")])

        style.configure("TEntry", fieldbackground="#FFFFFF", bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=self._px(8))
        style.configure("TCombobox", fieldbackground="#FFFFFF", bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=self._px(6))
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor="#E5ECF2", bordercolor="#E5ECF2", lightcolor=ACCENT, darkcolor=ACCENT)
        style.configure("Treeview", font=small_font, rowheight=self._px(31), background="#FFFFFF", fieldbackground="#FFFFFF", foreground=TEXT, borderwidth=0)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"), background="#E8F0F4", foreground=TEXT, relief="flat", padding=self._pad(7, 6))
        style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#FFFFFF")])
        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=self._pad(0, 0, 0, 0))
        style.configure("TNotebook.Tab", font=base_font, padding=self._pad(16, 8), background="#E3EBF1")
        style.map("TNotebook.Tab", background=[("selected", PANEL), ("active", "#EEF4F7")], foreground=[("selected", ACCENT_DARK), ("active", TEXT)])

    def _set_default_input(self) -> None:
        try:
            path = analysis.find_input_file()
        except Exception:
            return
        self.input_var.set(str(path.resolve()))

    def _build_layout(self) -> None:
        header = ttk.Frame(self, style="Header.TFrame", padding=self._pad(26, 16))
        header.pack(fill="x")
        ttk.Label(header, text=APP_TITLE, style="HeaderTitle.TLabel").pack(anchor="w")
        ttk.Label(header, text="导入生产数据，生成炉子级统计、每日/月汇总、趋势图和故障预警", style="HeaderSub.TLabel").pack(anchor="w", pady=self._pad(4, 0))

        main = ttk.Frame(self, padding=self._px(16))
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

    def _section(self, parent: ttk.Frame, title: str, subtitle: str = "", *, fill: str = "x", expand: bool = False, foldable: bool = False) -> ttk.Frame:
        outer = ttk.Frame(parent, style="Card.TFrame", padding=self._pad(13, 11))
        outer.pack(fill=fill, expand=expand, pady=self._pad(0, 11))
        header = ttk.Frame(outer, style="Panel.TFrame")
        header.pack(fill="x")
        label_text = f"▾ {title}" if foldable else title
        title_label = ttk.Label(header, text=label_text, style="Section.TLabel")
        title_label.pack(side="left")
        body = ttk.Frame(outer, style="Panel.TFrame")
        body.pack(fill="both" if fill == "both" else "x", expand=expand, pady=self._pad(0 if subtitle else 8, 0))
        if subtitle:
            subtitle_label = ttk.Label(outer, text=subtitle, style="Muted.TLabel", wraplength=self._px(350))
            subtitle_label.pack(anchor="w", pady=self._pad(2, 9))
        if foldable:
            def _toggle():
                if body.winfo_ismapped():
                    body.pack_forget()
                    title_label.configure(text=f"▸ {title}")
                    if subtitle:
                        subtitle_label.pack_forget()
                else:
                    body.pack(fill="both" if fill == "both" else "x", expand=expand, pady=self._pad(0 if subtitle else 8, 0), after=header)
                    title_label.configure(text=f"▾ {title}")
                    if subtitle:
                        subtitle_label.pack(anchor="w", pady=self._pad(2, 9), after=header)
            title_label.bind("<Button-1>", lambda _: _toggle())
        return body

    def _build_left_panel(self, parent: ttk.Frame) -> None:
        source = self._section(parent, "数据源", "选择原始数据文件和报表输出位置")
        file_row = ttk.Frame(source, style="Panel.TFrame")
        file_row.pack(fill="x", pady=self._pad(0, 8))
        file_row.columnconfigure(0, weight=1)
        ttk.Entry(file_row, textvariable=self.input_var).grid(row=0, column=0, sticky="ew", padx=self._pad(0, 8))
        ttk.Button(file_row, text="📂 浏览", style="Subtle.TButton", command=self.choose_input).grid(row=0, column=1)

        output_row = ttk.Frame(source, style="Panel.TFrame")
        output_row.pack(fill="x", pady=self._pad(0, 10))
        output_row.columnconfigure(0, weight=1)
        ttk.Entry(output_row, textvariable=self.output_var).grid(row=0, column=0, sticky="ew", padx=self._pad(0, 8))
        ttk.Button(output_row, text="输出目录", style="Subtle.TButton", command=self.choose_output).grid(row=0, column=1)

        ttk.Button(source, text="📊 加载数据 / 刷新炉号", style="Primary.TButton", command=self.load_data_async).pack(fill="x")

        checks = self._section(parent, "分析内容", foldable=True)
        check_items = [
            ("炉子级统计", self.run_furnace_var),
            ("每日汇总", self.run_daily_var),
            ("每月汇总", self.run_monthly_var),
            ("单炉每日趋势数据", self.run_furnace_daily_trend_var),
            ("低产率异常检测报告", self.run_anomaly_var),
        ]
        for index, (text, variable) in enumerate(check_items):
            row = index // 2
            col = index % 2
            ttk.Checkbutton(checks, text=text, variable=variable).grid(row=row, column=col, sticky="w", pady=self._px(3), padx=self._pad(0, 12))
        checks.columnconfigure((0, 1), weight=1)

        date_box = self._section(parent, "日期范围", "可选全部、最近时间段或手动指定起止日期", foldable=True)
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
        ttk.Button(actions, text="🔍 预览单炉趋势", style="Subtle.TButton", command=self._preview_single_furnace).pack(side="right")

        run_box = ttk.Frame(parent, style="Panel.TFrame")
        run_box.pack(fill="x")
        ttk.Button(run_box, text="▶️ 运行分析", style="Primary.TButton", command=self.run_analysis_async).pack(fill="x")
        export_btn = ttk.Frame(run_box, style="Panel.TFrame")
        export_btn.pack(fill="x", pady=self._pad(8, 0))
        ttk.Button(export_btn, text="💾 导出报表", style="Subtle.TButton", command=self._export_cached_reports).pack(side="left", fill="x", expand=True)
        ttk.Button(export_btn, text="打开输出目录", style="Ghost.TButton", command=self.open_output_dir).pack(side="left", fill="x", expand=True, padx=self._pad(8, 0))

    def _build_overview_panel(self, parent: ttk.Frame) -> None:
        overview = ttk.Frame(parent, style="Panel.TFrame", padding=self._pad(14, 12))
        overview.grid(row=0, column=0, sticky="ew", pady=self._pad(0, 12))
        overview.columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="stat")

        stats = [
            ("反应周期", self.stat_cycles),
            ("炉号数量", self.stat_furnaces),
            ("日期范围", self.stat_dates),
            ("平均产率 (kg/h)", self.stat_yield),
            ("生产线", self.stat_lines),
        ]
        for index, (name, variable) in enumerate(stats):
            cell = ttk.Frame(overview, style="StatCard.TFrame", padding=self._pad(12, 9))
            cell.grid(row=0, column=index, sticky="nsew", padx=self._pad(0 if index == 0 else 10, 0))
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
        self.output_tab = output_tab
        preview_tab.bind("<Configure>", self._on_preview_resize)
        notebook.add(preview_tab, text="趋势图预览")
        notebook.add(log_tab, text="运行日志")
        notebook.add(output_tab, text="输出文件")

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
        chart_buttons.columnconfigure(6, weight=1)
        chart_defs = [
            ("每日趋势图", lambda: self.show_scoped_preview("daily")),
            ("每月趋势图", lambda: self.show_scoped_preview("monthly")),
            ("炉子级统计", lambda: self.show_scoped_preview("furnace")),
            ("周期分布", lambda: self.show_scoped_preview("cycle_distribution")),
            ("周期热力图", lambda: self.show_scoped_preview("cycle_heatmap")),
            ("产率热力图", lambda: self.show_scoped_preview("yield_heatmap")),
            ("产率对比", self._show_yield_comparison_inline),
            ("前后20%排名", self.show_ranking_window),
        ]
        for col, (text, command) in enumerate(chart_defs):
            ttk.Button(chart_buttons, text=text, style="Ghost.TButton", command=command).pack(
                side="left",
                padx=self._pad(0 if col == 0 else 6, 0),
            )
        ttk.Label(chart_buttons, textvariable=self.preview_meta_var, style="Status.TLabel").pack(side="right", padx=self._pad(12, 12))
        ttk.Button(chart_buttons, text="导出图表数据", style="Accent.TButton", command=self._export_chart_data).pack(side="right")
        ttk.Button(chart_buttons, text="导出当前图片", style="Accent.TButton", command=self.export_current_preview_image).pack(side="right")

        furnace_tools = ttk.Frame(switch, style="Toolbar.TFrame")
        furnace_tools.pack(fill="x", pady=self._pad(8, 0))
        furnace_tools.columnconfigure(1, weight=1)
        ttk.Label(furnace_tools, text="单炉图表", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.furnace_chart_combo = ttk.Combobox(furnace_tools, textvariable=self.furnace_chart_var, state="readonly", width=26)
        self.furnace_chart_combo.grid(row=0, column=1, sticky="ew", padx=self._pad(8, 6))
        self.furnace_chart_combo.bind("<<ComboboxSelected>>", self._on_furnace_chart_select)
        ttk.Button(furnace_tools, text="显示单炉图", style="Subtle.TButton", command=self._show_selected_furnace_chart).grid(row=0, column=2, sticky="w")
        ttk.Label(furnace_tools, text="高亮炉号", style="Muted.TLabel").grid(row=0, column=3, sticky="w", padx=self._pad(14, 0))
        ttk.Entry(furnace_tools, textvariable=self.furnace_highlight_var, width=7).grid(row=0, column=4, sticky="w", padx=self._pad(4, 0))
        ttk.Label(furnace_tools, text="高亮日期", style="Muted.TLabel").grid(row=0, column=5, sticky="w", padx=self._pad(6, 0))
        ttk.Entry(furnace_tools, textvariable=self.date_highlight_var, width=10).grid(row=0, column=6, sticky="w", padx=self._pad(4, 0))
        ttk.Button(furnace_tools, text="输出目录", style="Ghost.TButton", command=self.open_output_dir).grid(row=0, column=7, sticky="e", padx=self._pad(10, 0))

        self.preview_container = ttk.Frame(preview_tab, style="Soft.TFrame")
        self.preview_container.grid(row=1, column=0, sticky="nsew")
        self.preview_container.rowconfigure(0, weight=1)
        self.preview_container.columnconfigure(0, weight=1)

        self.preview_label = ttk.Label(self.preview_container, text="运行分析后点击上方按钮预览趋势图\n单个炉子图表请在左侧选中炉号后点击「预览单炉趋势」", style="Preview.TLabel", anchor="center")
        self.preview_label.grid(row=0, column=0, sticky="nsew")

        # 产率对比内嵌 Notebook（懒加载）
        self.yield_notebook: ttk.Notebook | None = None

