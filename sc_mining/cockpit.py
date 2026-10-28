"""看屏幕判断你是不是坐在驾驶位上开着飞船（双击 W 自动跑的第二道保险）

游戏日志不一定每次都记下「坐上驾驶位」，所以在双击 W、准备开始自动跑的那一下，截一张图看画面中间：
飞船通电时准星附近一定有飞行 HUD——速度读数「0 m/s」、过载「0.0 G」、「加力」等；走路时没有这些。
认到就不触发。飞船没通电时没有 HUD，但那时按 W 飞船也动不了，不会出事。
（取自你 2026-10-20 的 C8R 驾驶位截图和机库里走路的截图）
"""
import re
import threading
import time

REGION = (0.28, 0.32, 0.74, 0.64)          # 画面中间偏下：左、上、右、下（占屏幕比例）
UPSCALE = 1        # HUD 字够大：按原尺寸认（以前放大 2 倍再认，慢 2 倍多，认到的一样）
FLIGHT = [re.compile(r"m\s*[/l|]\s*[s5]\b", re.I),          # 速度单位 m/s（OCR 有时认成 m/5、mls）
          re.compile(r"^\s*-?\d+(?:[.,]\d)?\s*G\s*$"),     # 过载读数 0.0 G
          re.compile(r"加力|推力|燃料|耦合|雷达高度|速度指示|SCM|NAV\b")]

_engine_ready = threading.Event()


def warm_up():
    """后台先把识别模型加载好（第一次加载要几秒，别等到双击 W 时才加载）"""
    def run():
        try:
            from .trade.ocr import recognize
            from PIL import Image
            recognize(Image.new("RGB", (64, 32)))
        except Exception:
            pass
        _engine_ready.set()
    threading.Thread(target=run, daemon=True, name="cockpit-warmup").start()


def crop(img):
    from PIL import Image
    w, h = img.size
    l, t, r, b = REGION
    piece = img.crop((int(w * l), int(h * t), int(w * r), int(h * b)))
    if UPSCALE != 1:
        piece = piece.resize((piece.width * UPSCALE, piece.height * UPSCALE), Image.BILINEAR)
    return piece


def flight_hud(img=None):
    """返回 (是否看到飞行 HUD, 认到的那几个字)"""
    from .trade.ocr import recognize
    if img is None:                                  # 只截中间这一块，不截整个屏幕
        from .perf import grab_region
        piece = grab_region(REGION)
        if UPSCALE != 1:
            from PIL import Image
            piece = piece.resize((piece.width * UPSCALE, piece.height * UPSCALE), Image.BILINEAR)
    else:
        piece = crop(img)
    hits = []
    for tok in recognize(piece, native=True):
        t = tok.text.strip()
        if any(p.search(t) for p in FLIGHT):
            hits.append(t)
    return bool(hits), hits


_remote = {"fail": 0.0}


def ask_main(timeout=2.0):
    """问主程序「现在看得到飞行 HUD 吗」（主程序本来就加载着识别引擎；辅助进程不用再加载一份，省约 100 MB 内存）。
    主程序没开、没回应返回 None"""
    import json
    import urllib.request
    from urllib.parse import urlparse
    from .paths import USER
    try:
        url = (USER / "window_url.txt").read_text(encoding="utf-8").strip()
        u = urlparse(url)
        token = u.fragment.split("t=", 1)[-1] if "t=" in u.fragment else ""
        req = urllib.request.Request(f"{u.scheme}://{u.netloc}/api/cockpit_check", data=b"{}",
                                     headers={"Content-Type": "application/json", "X-Token": token})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
        if d.get("ok") and isinstance(d.get("data"), dict) and "flying" in d["data"]:
            return bool(d["data"]["flying"])
    except Exception:
        pass
    return None


def flying(timeout=2.0):
    """双击 W 时调用：看到飞行 HUD 返回 True；识别出错/超时当作没看到（日志那道保险还在）。
    先问主程序（2026-10-26）；主程序不在才自己加载引擎来认"""
    r = ask_main(timeout)
    if r is not None:
        return r
    if not _engine_ready.is_set():
        warm_up()
    if not _engine_ready.wait(timeout):
        return False
    try:
        return flight_hud()[0]
    except Exception:
        return False
