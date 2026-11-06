"""实时截图预览缓存：更新最新画面截图、节流推送和取缩略图 / 大图，从 app/bus.py 拆来。"""

import io
import threading
import time

from . import bus

_preview_thumb_bytes = None
_preview_full_bytes = None
_preview_meta = {}
_last_preview_t = 0.0
_preview_lock = threading.Lock()


def update_preview(img, source="live", force=False):
    """更新最新画面截图缓存，并向前端推送通知（节流保护，最高 2 次/秒）"""
    global _last_preview_t, _preview_thumb_bytes, _preview_full_bytes, _preview_meta
    now = time.time()
    if not force and now - _last_preview_t < 0.5:
        return
    with _preview_lock:
        if not force and now - _last_preview_t < 0.5:
            return
        _last_preview_t = now
        try:
            w, h = img.size
            # 缩略图（针对右下角预览区域，宽度限制在 360px）
            tw = min(360, w)
            th = max(1, int(h * (tw / w)))
            thumb = img.resize((tw, th))
            if thumb.mode != "RGB":
                thumb = thumb.convert("RGB")
            bio = io.BytesIO()
            thumb.save(bio, format="JPEG", quality=75)
            _preview_thumb_bytes = bio.getvalue()

            # 大图缓存（用于点击弹出放大，最大宽 1280px）
            fw = min(1280, w)
            fh = max(1, int(h * (fw / w)))
            fimg = img if fw >= w else img.resize((fw, fh))
            if fimg.mode != "RGB":
                fimg = fimg.convert("RGB")
            bio_full = io.BytesIO()
            fimg.save(bio_full, format="JPEG", quality=80)
            _preview_full_bytes = bio_full.getvalue()

            _preview_meta = {
                "t": now,
                "time_str": time.strftime("%H:%M:%S"),
                "w": w,
                "h": h,
                "source": source,
                "bytes": len(_preview_thumb_bytes),
            }
        except Exception as e:
            bus.runtime_log(f"截图预览处理异常: {e}", tag="SYS", level="WARN")
            return
    bus.publish("runtime_preview", _preview_meta)


def get_preview_bytes(full=False):
    """获取最新截图的二进制数据与元数据"""
    with _preview_lock:
        return (_preview_full_bytes if full else _preview_thumb_bytes), dict(
            _preview_meta
        )
