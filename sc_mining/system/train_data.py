"""帮助改进识别：收集「一行字的小截图 + 正确答案」，攒够了发给作者训练认字模型（2026-10-27 老大定）

- 正确答案从哪来（玩家不用额外操作）：F8 认出的名字被汉化包纠正了（OCR 认成「微记」，汉化包里是「徽记」）——
  那一行字的小截图 + 汉化包里的名字就是一道错题；认对的也抽一成存（新模型不能只见过错题）
- 只存那一行字（几十像素高的一条），不存整屏、聊天、玩家名
- 攒到 BATCH 条打一个包发到 AT 服务器（和 F10 反馈同一个地址，类型 train）；每天最多 DAY_MAX 条，本地最多 MAX_LOCAL_MB
- 设置里「帮助改进识别」关掉就不存也不发；跑测试时（AT_FEEDBACK_OFF）不发
"""
import io
import json
import os
import random
import re
import threading
import time
import zipfile

BATCH = 25                  # 一条是 png + json 两个文件；服务器一包最多收 60 个文件（二审 2026-10-27：50 条一定被拒）
DAY_MAX = 300
MAX_LOCAL_MB = 30
PAD = 4                     # 小截图四周多留几个像素（字边缘别切掉）
POSITIVE_RATE = 0.1         # 认对的抽多少存
_lock = threading.Lock()
_sending = threading.Lock()
_gen = [0]                  # 每次清空 +1：清空前打好的包就不发了（复审 2026-10-27）


def _dir():
    from ..core import paths
    d = paths.USER / "train"
    d.mkdir(parents=True, exist_ok=True)
    return d


def enabled():
    from ..core import settings
    if settings.load().get("train_upload") is False:
        return False
    try:
        from ..update import update_check
        return not update_check.disabled("train")       # 远程开关：服务器满了 / 出问题时整体关掉
    except Exception:
        return True


def _today_count(d):
    day = time.strftime("%Y%m%d")
    f = d / f".count_{day}"
    for old in d.glob(".count_*"):                       # 以前的计数文件不留
        if old.name != f.name:
            old.unlink(missing_ok=True)
    try:
        return f, int(f.read_text(encoding="utf-8") or 0)
    except (OSError, ValueError):
        return f, 0


def _local_mb(d):
    return sum(p.stat().st_size for p in d.glob("*.png")) / 2 ** 20


def add_line(img, box, truth, ocr="", kind="f8", meta=None):
    """img：整张截图（PIL）；box：(x, y, w, h) 那一行字的位置；truth：正确答案；ocr：OCR 认成的。存了返回 True"""
    if not truth or not box or not enabled():
        return False
    if ocr and ocr.replace(" ", "") == truth.replace(" ", "") and random.random() > POSITIVE_RATE:
        return False                                      # 认对的只抽一部分
    x, y, w, h = (int(v) for v in box)
    if w < 8 or h < 6 or h > 120 or w > 2000:             # 不像一行字：不存
        return False
    W, H = img.size
    crop = img.crop((max(0, x - PAD), max(0, y - PAD), min(W, x + w + PAD), min(H, y + h + PAD)))
    with _lock:
        if not enabled():                                 # 拿到锁再看一次：关开关和清理也拿这把锁（二审 2026-10-27）
            return False
        d = _dir()
        cf, n = _today_count(d)
        if n >= DAY_MAX or _local_mb(d) > MAX_LOCAL_MB:
            return False
        stem = f"{time.strftime('%Y%m%d_%H%M%S')}_{kind}_{random.randrange(16 ** 6):06x}"
        try:
            crop.convert("RGB").save(d / f"{stem}.png", optimize=True)
            rec = {"img": f"{stem}.png", "truth": truth, "ocr": ocr, "kind": kind, "screen": [W, H], **(meta or {})}
            (d / f"{stem}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
            cf.write_text(str(n + 1), encoding="utf-8")
        except OSError:
            (d / f"{stem}.png").unlink(missing_ok=True)   # 没写全：别留孤儿图占额度
            return False
    maybe_send()
    return True


def pending():
    try:
        return sorted(_dir().glob("*.json"))
    except OSError:
        return []


def clear():
    """玩家关掉「帮助改进识别」：本地攒着没发的一起删掉"""
    with _lock:
        _gen[0] += 1
        try:
            for f in _dir().iterdir():
                if f.suffix in (".png", ".json"):
                    f.unlink(missing_ok=True)
        except OSError:
            pass


def _refused_today():
    return (_dir() / f".refused_{time.strftime('%Y%m%d')}").exists()


def maybe_send(force=False):
    """攒够 BATCH 条就在后台发一包（不挡识别）。服务器今天拒收过：今天不再发"""
    if os.environ.get("AT_FEEDBACK_OFF") or not enabled() or _refused_today():
        return
    if not force and len(pending()) < BATCH:
        return
    threading.Thread(target=_send_batch, daemon=True, name="train-up").start()


def _send_batch():
    import urllib.request
    from . import feedback_up as F
    from ..core.version import VERSION
    if not _sending.acquire(blocking=False):
        return
    try:
        b = io.BytesIO()
        sent = []
        with _lock:                                       # 打包时不让清空插进来
            gen = _gen[0]
            items = pending()[:BATCH]
            if not items:
                return
            with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
                for j in items:
                    png = j.with_suffix(".png")
                    if not png.exists():
                        j.unlink(missing_ok=True)
                        continue
                    z.write(png, f"train/{png.name}")
                    z.write(j, f"train/{j.name}")
                    sent.append(j)
        if not sent or not enabled() or _gen[0] != gen:   # 打包后玩家关了开关（清空过）：这包不发（复审）
            return
        req = urllib.request.Request(F.URL, data=b.getvalue(), method="POST", headers={
            "X-AT-Key": F.KEY, "X-AT-Version": VERSION, "X-AT-Kind": "train", "X-AT-Id": F.install_id(),
            "Content-Type": "application/zip", "User-Agent": f"AT/{VERSION}"})
        import urllib.error
        try:
            with urllib.request.urlopen(req, timeout=F.TIMEOUT) as r:
                ok = r.status == 200
        except urllib.error.HTTPError as e:
            ok = False
            if 400 <= e.code < 500:                       # 服务器不收（包不对 / 被关）：今天不再重发
                for old in _dir().glob(".refused_*"):
                    old.unlink(missing_ok=True)
                (_dir() / f".refused_{time.strftime('%Y%m%d')}").write_text(str(e.code), encoding="utf-8")
        except Exception:
            ok = False
        if ok:                                            # 服务器收到了才删本地的
            for j in sent:
                j.with_suffix(".png").unlink(missing_ok=True)
                j.unlink(missing_ok=True)
    finally:
        _sending.release()


def from_tooltip(img, tokens, raw, canon):
    """F8：认出的名字 raw=(中文, 英文) 被汉化包纠正成 canon=(中文, 英文) → 找到名字那几行，各存一道题"""
    try:
        for got, truth in zip(raw, canon):
            got, truth = (got or "").strip(), (truth or "").strip()
            if not got or not truth:
                continue
            from ..trade.names import split_bilingual
            if truth == (canon[0] or "").strip() and split_bilingual(got)[1]:
                continue                                  # 「中文English」连写的一行：答案只有中文一半，对不上图，不存（复审 2026-10-27）
            tok = next((k for k in tokens if k.text.strip() == got), None)
            if tok is not None:
                add_line(img, tok.box, truth, got, "f8")
    except Exception:
        pass
