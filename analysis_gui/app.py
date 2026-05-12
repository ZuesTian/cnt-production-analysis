# -*- coding: utf-8 -*-
"""Application object and entrypoint for the Tk GUI."""

from __future__ import annotations

import sys
from pathlib import Path

import tkinter as tk

from .constants import APP_TITLE, BG
from .image_support import ImageTk, PIL_IMPORT_ERROR
from .layout import LayoutMixin
from .platform import enable_high_dpi_awareness
from .preview import PreviewMixin
from .state import AnalysisData, PreviewState, WorkState
from .utility import UtilityMixin
from .workflow import WorkflowMixin


class AnalysisApp(LayoutMixin, WorkflowMixin, PreviewMixin, UtilityMixin, tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self._init_ui_scaling()
        self.title(APP_TITLE)
        self._set_window_size(self, 1180, 760, 1060, 680)
        self.configure(bg=BG)

        # 状态管理（dataclass 分组）
        self._data = AnalysisData()
        self._preview = PreviewState()
        self._work = WorkState()

        self.output_paths: list[Path] = []
        self.preview_image: ImageTk.PhotoImage | None = None
        self.furnace_chart_var = tk.StringVar()
        self.furnace_chart_map: dict[str, Path] = {}
        self.last_scope_prefix = "全区"
        self.generated_chart_paths: dict[str, Path] = {}

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar(value="output")
        self.furnace_mode = tk.StringVar(value="all")
        self.selector_var = tk.StringVar()
        self.run_furnace_var = tk.BooleanVar(value=True)
        self.run_daily_var = tk.BooleanVar(value=True)
        self.run_monthly_var = tk.BooleanVar(value=True)
        self.run_furnace_daily_trend_var = tk.BooleanVar(value=False)
        self.run_anomaly_var = tk.BooleanVar(value=False)
        self.furnace_highlight_var = tk.StringVar()
        self.date_highlight_var = tk.StringVar()
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



def main() -> None:
    if PIL_IMPORT_ERROR is not None:
        print("缺少 Pillow 库，请运行：pip install Pillow")
        sys.exit(1)
    enable_high_dpi_awareness()
    app = AnalysisApp()
    app.mainloop()
