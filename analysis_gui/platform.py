# -*- coding: utf-8 -*-
"""Platform-specific GUI setup."""

from __future__ import annotations

import contextlib
import ctypes
import sys


def enable_high_dpi_awareness() -> None:
    """Ask Windows to give Tk real DPI information before the root window exists."""
    if sys.platform != "win32":
        return

    with contextlib.suppress(Exception):
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    with contextlib.suppress(Exception):
        ctypes.windll.user32.SetProcessDPIAware()
