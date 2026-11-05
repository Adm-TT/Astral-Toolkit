"""识别测速（2026-10-25 优化前后对比用，不打包）：用本机样本量 F8、扫描面板、右上角读位置各要多少毫秒

F8 按 inspector.HEIGHT_STAGES 的高度阶段分别量（2026-11-04 标题带方案）：标题带 24%~36%（native=True，
新方案主路径）→ 说明框带 24%~70% → 旧全高中间条带 0~100%（对比基线），宽度统一取中间 30%~70%；
最后再量一次整屏。没有测速样本时退回扫描样本，再没有就跳过这几项。
用法（项目根目录）：
  .venv\\Scripts\\python.exe -X utf8 tools\\bench_ocr.py            显卡（默认设置）
  set DUBHE_OCR_CPU=1 后再跑一次 = 纯 CPU
结果追加到 测试数据\\识别测速.md。只在本机跑，不上传图片
"""

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from PIL import Image  # noqa: E402

N = int(os.environ.get("BENCH_N", "5"))
# HEIGHT_STAGES 各阶段在报告里的名字（title / body / full，见 astral_toolkit/trade/inspector.py）
STAGE_TITLES = {
    "title": "标题带（新方案主路径）",
    "body": "说明框带",
    "full": "旧全高中间条带（对比基线）",
}


def _ms(fn, n=N):
    fn()  # 第一次不算（预热）
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t) * 1000)
    ts.sort()
    return ts[len(ts) // 2], ts[0]


def main():
    # 高度阶段级联：顺序就是测量的顺序（title → body → full）；宽度条带也从这里取
    from astral_toolkit.trade.inspector import HEIGHT_STAGES, HOVER_REGIONS
    from astral_toolkit.ocr import recognize, warmup, ocr_device
    from astral_toolkit.ocr import runtime as OR
    from astral_toolkit.mining import screen
    from astral_toolkit.navigation import displayinfo

    out = [
        f"## {time.strftime('%F %T')} 版本 {__import__('astral_toolkit.core.version', fromlist=['VERSION']).VERSION}"
    ]
    t = time.perf_counter()
    warmup()
    out.append(
        f"- 识别引擎加载：{(time.perf_counter() - t) * 1000:.0f} ms（{ocr_device()}，显卡部分 {','.join(OR.GPU_PARTS) or '无'}）"
    )
    samples = sorted((ROOT / "测试数据" / "识别样本").glob("*.png"))[:3]
    if not samples:
        # 没有专门的测速样本：退回扫描样本；再没有就跳过 F8 / 扫描面板，别崩
        fallback = ROOT / "tests" / "samples" / "scan1.png"
        samples = [fallback] if fallback.exists() else []
    if not samples:
        out.append(
            "- 没有 F8 测速样本（测试数据/识别样本 和 tests/samples/scan1.png 都不在），跳过 F8 / 扫描面板测速"
        )
    # 宽度统一取中间条带 30%~70%，高度按 HEIGHT_STAGES 分档
    band = HOVER_REGIONS["中间"]
    for p in samples:
        img = Image.open(p).convert("RGB")
        W, H = img.size
        for top, bottom, stage, native in HEIGHT_STAGES:
            crop = img.crop(
                (
                    int(W * band[0]),
                    int(H * top),
                    int(W * band[2]),
                    int(H * bottom),
                )
            )
            med, best = _ms(lambda: recognize(crop, urgent=True, native=native))
            out.append(
                f"- F8 {STAGE_TITLES.get(stage, stage)}：{p.name} {W}×{H}，"
                f"宽 {band[0]:.0%}~{band[2]:.0%} × 屏高 {top:.0%}~{bottom:.0%}，native={native}，"
                f"中位 {med:.0f} ms，最快 {best:.0f} ms"
            )
        med, best = _ms(lambda: recognize(img, urgent=True), n=max(2, N // 2))
        out.append(
            f"- F8 整屏识别（{p.name} {W}×{H}）：中位 {med:.0f} ms，最快 {best:.0f} ms"
        )
        screen.PANEL_CACHE.update(win=None)
        med, best = _ms(
            lambda: (screen.PANEL_CACHE.update(win=None), screen.analyse(img))
        )
        out.append(
            f"- 扫描面板·第一帧（整片找，{p.name}）：中位 {med:.0f} ms，最快 {best:.0f} ms"
        )
        med, best = _ms(lambda: screen.analyse(img))
        out.append(
            f"- 扫描面板·后续帧（只读上次位置）：中位 {med:.0f} ms，最快 {best:.0f} ms，路径 {screen.LAST_PATH['path']}"
        )
    di = ROOT / "tests" / "samples" / "displayinfo.png"
    if di.exists() and hasattr(displayinfo, "read"):
        img = Image.open(di).convert("RGB")
        try:
            med, best = _ms(lambda: displayinfo.read(img))
            out.append(
                f"- 右上角读位置（displayinfo.png）：中位 {med:.0f} ms，最快 {best:.0f} ms"
            )
        except Exception as e:
            out.append(f"- 右上角读位置：出错 {e}")
    text = "\n".join(out)
    print(text)
    f = ROOT / "测试数据" / "识别测速.md"
    f.parent.mkdir(exist_ok=True)
    with open(f, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(text + "\n\n")


if __name__ == "__main__":
    main()
