"""OCR 视觉感知通用数据模型"""

from dataclasses import dataclass
from typing import Any, NamedTuple


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


class OcrQuad(NamedTuple):
    """检测 + 识别的一行（ocr.detect 给的）：四个角点、文字、把握。
    给要看斜度的地方用（采矿扫描面板：驾驶位转头看时面板是斜的，按框上沿的斜率摆正）——OcrToken 只留了取整的正框，
    看不出斜。是元组，照旧可以 for quad, text, conf in …（2026-11-09 取代 raw_detector 交出去的引擎原始格式）

    Attributes:
        quad: 四个角点 [[x, y] × 4]（左上、右上、右下、左下，浮点），按送进去的那张图的像素
        text: 认出的文字（原样，不去空格）
        conf: 把握，0~1（引擎原值；OcrToken.confidence 是乘了 100 的）
    """

    quad: Any
    text: str
    conf: Any
