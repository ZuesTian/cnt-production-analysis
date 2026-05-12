# -*- coding: utf-8 -*-
"""Small GUI utility actions."""

from __future__ import annotations

import os
from pathlib import Path

import tkinter as tk
from tkinter import messagebox


class UtilityMixin:
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


