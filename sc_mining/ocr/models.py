"""OCR 视觉感知通用数据模型"""

from dataclasses import dataclass


@dataclass(frozen=True)
class OcrToken:
    """单行/词块 OCR 识别结果

    Attributes:
        text: 识别出的文本内容
        confidence: 置信度 (0.0 ~ 100.0)
        box: 矩形包围盒 (left, top, width, height)，以像素为单位
    """

    text: str
    confidence: float
    box: tuple[int, int, int, int]
