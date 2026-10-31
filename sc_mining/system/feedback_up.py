"""问题反馈自动发给作者（2026-10-27 老大定：按了就自动发，设置页能关）。

F10 / 「报告问题」存好的反馈文件夹 → 截图转成 JPG 重新打包（29 MB 左右 → 两三 MB）→ POST 到 AT 服务器。
发成功写 .sent；没发成的留 .pending，下次启动再发。服务器只收 zip、≤20 MB、每个 IP 每分钟 6 次。
"""
import io
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile

URL = "https://api.astral-trade.com/feedback"
KEY = "atfb-7Qm2xV9pL4"            # 不是保密用的，只挡乱扫的机器人（和服务器 feedback_rx.py 一致）
TIMEOUT = 60
MAX_BYTES = 18 * 1024 * 1024
RETRY_DAYS = 14
RETRY_MAX = 5
IMG = (".png", ".jpg", ".jpeg")
TXT = (".txt", ".json", ".log")
_lock = threading.Lock()


def enabled():
    from ..core import settings
    from ..update import update_check
    if os.environ.get("AT_FEEDBACK_OFF"):                   # 跑测试时关掉（不能往服务器发假反馈）
        return False
    if settings.load().get("feedback_upload") is False:
        return False
    try:
        return not update_check.disabled("feedback")      # 远程开关：服务器出问题时能整体关掉
    except Exception:
        return True


def install_id():
    """匿名编号（随机生成，只用来区分同一台电脑发的几条反馈）"""
    from ..core import paths
    p = paths.USER / "install_id.txt"
    try:
        v = p.read_text(encoding="utf-8").strip()
        if len(v) == 12 and all(c in "0123456789abcdef" for c in v):
            return v
    except OSError:
        pass
    v = uuid.uuid4().hex[:12]
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(v, encoding="utf-8")
    except OSError:
        pass
    return v


def _jpg(path, quality):
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert("RGB")
        b = io.BytesIO()
        im.save(b, "JPEG", quality=quality, optimize=True)
        return b.getvalue()


def pack(d, quality=82):
    """反馈文件夹 → 要上传的 zip（字节）。图片都转 JPG；太大时先降画质，再从最旧的采矿助手截图开始丢"""
    files = sorted(f for f in d.iterdir() if f.is_file() and f.suffix.lower() in IMG + TXT)
    drop = [f for f in files if f.name.startswith(("live_", "miss_", "hover_"))]
    for q in (quality, 65, 50):
        keep = list(files)
        while True:
            b = io.BytesIO()
            with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
                for f in keep:
                    if f.suffix.lower() in IMG:
                        try:
                            z.writestr(f"{d.name}/{f.stem}.jpg", _jpg(f, q))
                        except Exception:
                            continue
                    else:
                        z.write(f, f"{d.name}/{f.name}")
            data = b.getvalue()
            if len(data) <= MAX_BYTES:
                return data
            gone = next((f for f in drop if f in keep), None)
            if gone is None:
                break
            keep.remove(gone)
    return None


def _drop_pending(d):
    try:
        (d / ".pending").unlink(missing_ok=True)
    except OSError:
        pass


def send(d, kind="auto"):
    """发一个反馈文件夹。返回 (成功?, 说明, 没发成的话下次启动会不会再发)。不抛异常"""
    try:
        return _send(d, kind)
    except Exception as e:                             # 打包时文件被清空、不可读等：留着下次再试
        return False, f"打包失败（{type(e).__name__}）", (d / ".pending").exists()


def _send(d, kind):
    from ..core.version import VERSION
    with _lock:
        if (d / ".sent").exists():
            return True, "已发送", False
        if not enabled():                              # 玩家刚关掉自动发送：排着队的也不发（Codex 2026-10-27）
            return False, "自动发送已关闭", False
        if not d.is_dir():
            return False, "反馈已删除", False
        data = pack(d)
        if data is None:
            _drop_pending(d)
            return False, "反馈太大", False
        if not enabled():                              # 打包要零点几秒：发之前再查一次
            return False, "自动发送已关闭", False
        req = urllib.request.Request(URL, data=data, method="POST", headers={
            "X-AT-Key": KEY, "X-AT-Version": VERSION, "X-AT-Kind": kind, "X-AT-Id": install_id(),
            "Content-Type": "application/zip", "User-Agent": f"AT/{VERSION}"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                ok = r.status == 200
        except urllib.error.HTTPError as e:
            if e.code in (400, 403, 413):              # 服务器不收这一条：不再重试
                _drop_pending(d)
                return False, f"服务器不收（{e.code}）", False
            return False, f"服务器忙（{e.code}）", True
        except Exception as e:
            return False, f"连不上服务器（{type(e).__name__}）", True
        if not ok:
            return False, "服务器没收到", True
        try:                                           # 服务器已经收到：本地记不下也算发成（最多下次重复发一次）
            (d / ".sent").write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
        except OSError:
            pass
        _drop_pending(d)
        return True, "已发送", False


def mark_pending(d):
    try:
        (d / ".pending").write_text("", encoding="utf-8")
    except OSError:
        pass


def retry_pending(fb_dir):
    """启动时：把上次没发成的补发（只发最近 14 天、最多 5 条）"""
    if not enabled() or not fb_dir.exists():
        return 0
    cut = time.time() - RETRY_DAYS * 86400
    todo = []
    for p in fb_dir.glob("*/.pending"):
        try:
            if p.stat().st_mtime > cut:
                todo.append(p.parent)
        except OSError:
            pass
    todo = sorted(todo, key=lambda d: d.name)[-RETRY_MAX:]
    n = 0
    for d in todo:
        if not enabled():                              # 补发途中玩家关掉了：后面的不发
            break
        ok, _, _ = send(d, d.name.rsplit("_", 1)[-1])   # send 不抛异常：一条失败不影响后面的
        n += ok
    return n
