"""Astral-Toolkit 统一 OCR 模块"""

from .models import OcrQuad, OcrToken
from .engine import detect, recognize, read_line
from .runtime import (
    warmup,
    set_ocr_device,
    ocr_device,
    gpu_available,
    last_ocr_error,
)

__all__ = [
    "OcrToken",
    "recognize",
    "read_line",
    "OcrQuad",
    "detect",
    "warmup",
    "set_ocr_device",
    "ocr_device",
    "gpu_available",
    "last_ocr_error",
]
