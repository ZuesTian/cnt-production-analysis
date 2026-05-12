# -*- coding: utf-8 -*-
"""State containers shared by the Tk application."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .image_support import Image


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


@dataclass
class AnalysisData:
    """集中管理分析数据和缓存"""
    cycles: pd.DataFrame | None = None
    loaded_input: Path | None = None
    selected_furnaces: list[str] | None = None
    daily_summary: pd.DataFrame | None = None
    monthly_summary: pd.DataFrame | None = None
    trend_data: pd.DataFrame | None = None
    cache: dict[str, Any] = field(default_factory=dict)

    def clear(self) -> None:
        self.cycles = None
        self.loaded_input = None
        self.selected_furnaces = None
        self.daily_summary = None
        self.monthly_summary = None
        self.trend_data = None
        self.cache.clear()


@dataclass
class PreviewState:
    """集中管理预览状态"""
    original: Image.Image | None = None
    path: Path | None = None
    name: str | None = None
    chart_type: str | None = None
    yield_tab: str = "yield_comparison"
    resize_after_id: str | None = None

    def clear(self) -> None:
        self.original = None
        self.path = None
        self.name = None
        self.chart_type = None


@dataclass
class WorkState:
    """集中管理后台任务状态"""
    queue: queue.Queue[tuple[str, Any]] = field(default_factory=queue.Queue)
    thread: threading.Thread | None = None
    pending_input: Path | None = None
    pending_output: Path | None = None
    pending_options: dict[str, Any] = field(default_factory=dict)
