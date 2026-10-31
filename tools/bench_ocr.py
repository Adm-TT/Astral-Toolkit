"""识别测速（2026-10-25 优化前后对比用，不打包）：用本机样本量 F8、扫描面板、右上角读位置各要多少毫秒

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
    from sc_mining.core import perf
    from sc_mining.tasks import hover as S
    from sc_mining.ocr import recognize
    from sc_mining.mining import screen
    from sc_mining.navigation import displayinfo

    out = [
        f"## {time.strftime('%F %T')} 版本 {__import__('sc_mining.core.version', fromlist=['VERSION']).VERSION}"
    ]
    t = time.perf_counter()
    perf.rapidocr()
    out.append(
        f"- 识别引擎加载：{(time.perf_counter() - t) * 1000:.0f} ms（{perf.ocr_device()}，显卡部分 {','.join(perf.GPU_PARTS) or '无'}）"
    )
    samples = sorted((ROOT / "测试数据" / "识别样本").glob("*.png"))[:3] or [
        ROOT / "tests" / "samples" / "scan1.png"
    ]
    for p in samples:
        img = Image.open(p).convert("RGB")
        W, H = img.size
        l, tp, r, b = S.HOVER_REGION  # noqa: E741
        crop = img.crop((int(W * l), int(H * tp), int(W * r), int(H * b)))
        med, best = _ms(lambda: recognize(crop, urgent=True))
        out.append(
            f"- F8 中间区域识别（{p.name} {W}×{H}）：中位 {med:.0f} ms，最快 {best:.0f} ms"
        )
        med, best = _ms(lambda: recognize(img, urgent=True), n=max(2, N // 2))
        out.append(f"- F8 整屏识别（{p.name}）：中位 {med:.0f} ms，最快 {best:.0f} ms")
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
