# -*- coding: utf-8 -*-
"""Optional Pillow imports used by the GUI preview code."""

try:
    from PIL import Image, ImageTk
except ImportError as exc:
    Image = None
    ImageTk = None
    PIL_IMPORT_ERROR = exc
else:
    PIL_IMPORT_ERROR = None
