"""问题反馈收集、截图与诊断日志打包及用户隐私脱敏"""

import json
import re
import shutil
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from ...app import bus
from .common import WIN, _FB_LAST, _engines, _hud, _note_hud


def _fb_dir():
    from ...core import paths

    d = paths.USER / "feedback"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _scrub(text):
    """反馈包里的文字去掉个人信息：AT、数据、userdata、用户主目录、临时文件夹换成占位符，别的 C:\\Users\\<名字> 也抹掉，
    网址里的口令（#t= / ?token= / X-Token）换掉。S5 审查 2026-10-31：日志尾巴原样进反馈包、默认自动上传，会带出 Windows 用户名"""
    from ...core import paths

    forms = []
    for p, tag in (
        (paths.USER, "<USERDATA>"),
        (paths.DATA, "<DATA>"),
        (paths.ROOT, "<AT>"),
        (tempfile.gettempdir(), "<TEMP>"),
        (Path.home(), "<HOME>"),
    ):
        try:
            raw = {str(p), str(Path(p).resolve())}
        except Exception:
            continue
        for s in raw:
            if len(s) > 3:  # 别把「C:\」这种盘符根换掉
                forms += [
                    (f, tag) for f in {s, s.replace("\\", "/"), s.replace("\\", "\\\\")}
                ]
    for f, tag in sorted(
        forms, key=lambda x: -len(x[0])
    ):  # 长的先换：userdata 在 AT 文件夹里面
        text = re.sub(re.escape(f), lambda _m, tag=tag: tag, text, flags=re.I)
    text = re.sub(
        r"(?i)\b([A-Z]:(?:\\{1,2}|/)Users(?:\\{1,2}|/))(?:\\u[0-9a-f]{4}|[^\\/\r\n\t\"'<>|])+",
        r"\1<user>",
        text,
    )  # \uXXXX：中文用户名被转义写进日志
    text = re.sub(r"([#?&](?:t|token)=)[A-Za-z0-9_\-]{8,}", r"\1<token>", text)
    return re.sub(
        r"(?i)(X-Token[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9_\-]{8,}", r"\1<token>", text
    )


def feedback_report(kind="auto", note="", img=None):
    """一键反馈：现在的整屏截图 + 最近几帧采矿助手截图 + OCR 原文 + 当时显示的结果 + 日志尾巴，打成一个文件夹和 zip
    放在 userdata\\feedback\\。kind：scan（矿物认错）/ signal（信号不对）/ item（F8 认错）/ auto"""
    from ...core import paths
    from ...mining import screen
    from ...mining.screen import grab
    from .about import _version
    from .settings import HOTKEYS
    from .status import _desktop  # noqa: F401

    stamp = time.strftime("%Y%m%d_%H%M%S")
    kind = kind if kind in ("scan", "signal", "item", "auto") else "auto"
    d = _fb_dir() / f"{stamp}_{kind}"
    d.mkdir(parents=True, exist_ok=True)
    try:
        img = img or grab()
        img.save(d / "屏幕.png")
    except Exception as e:
        (d / "截图失败.txt").write_text(_scrub(str(e)), encoding="utf-8")
    # 最近几帧采矿助手截图和 F8 截图（本来就只留最近 20 张）
    for sub, n in (
        ("live", 5),
        ("hover", 2),
        ("miss", 3),
    ):  # miss：采矿助手看到面板却没出结果时自动留的图
        src = paths.SHOTS / sub
        if src.exists():
            for f in sorted(src.glob("*.*"), key=lambda f: f.stat().st_mtime)[-n:]:
                try:
                    shutil.copy(f, d / f"{sub}_{f.name}")
                except OSError:
                    pass

    from .. import hover as _hv, navigation as _nv

    m = _engines()
    last_hover = _hv._last_hover
    live_running = m.live.running()
    live_paused = getattr(m.live, "paused", False)
    where_now = _nv._WHERE.get("v")
    nav_label = m.nav.target_label()
    nav_space = m.nav.space_mode

    fb_sig = _FB_LAST["sig"]
    fb_scan = _FB_LAST["scan"]

    info = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "version": _version(),
        "kind": kind,
        "note": note or "",
        "screen": [img.width, img.height] if img else None,
        "ocr_scan_lines": screen.LAST_RAW.get("scan"),
        "ocr_bag_lines": screen.LAST_RAW.get("bag"),
        "ocr_age_s": round(time.time() - screen.LAST_RAW.get("t", 0))
        if screen.LAST_RAW.get("t")
        else None,
        "shown_signal": fb_sig,
        "shown_scan": fb_scan,
        "hover": {k: v for k, v in last_hover.items() if k != "img"},
        "hud": dict(getattr(_hud(), "sections", {}) or {}),
        "live": live_running,
        "live_paused": live_paused,
        "where_now": where_now,
        "nav": nav_label,
        "nav_space": nav_space,
    }
    try:
        from ...core import settings

        cfg = settings.load()
        info["settings"] = {
            k: cfg.get(k)
            for k in (
                "mining_ship",
                "mining_loadouts",
                "admin",
                *(n for n, _, _ in HOTKEYS),
            )
        }
    except Exception:
        pass
    (d / "情况.json").write_text(
        _scrub(json.dumps(info, ensure_ascii=False, indent=1, default=str)),
        encoding="utf-8",
    )
    for name in (
        "live_log.txt",
        "trade_log.txt",
        "nav_log.txt",
        "app_log.txt",
        "crash_log.txt",
        "crash_log_ocr.txt",
    ):
        p = paths.LOGS / name
        if p.exists():
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[
                    -150:
                ]
                (d / name).write_text(
                    _scrub("\n".join(lines)), encoding="utf-8"
                )  # 抹掉用户名、口令再进反馈包
            except OSError:
                pass
    (d / "说明.txt").write_text(
        f"AT 问题反馈 {info['time']}（{kind}）\n{note or '（无备注）'}\n\n"
        "屏幕.png = 按下反馈键时的截图；live_*.png = 采矿助手最近几帧；情况.json = 当时的识别文字和显示结果。\n"
        "自动发送开着时已发给作者；关着时将此文件夹（或同名 zip）发给作者即可。截图中可能有游戏聊天框。",
        encoding="utf-8",
    )
    zp = d.with_suffix(".zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in d.iterdir():
            z.write(f, f"{d.name}/{f.name}")
    from ...system import feedback_up

    upload = feedback_up.enabled()
    hm = f"{stamp[-6:-4]}:{stamp[-4:-2]}:{stamp[-2:]}"
    try:
        _note_hud(
            "反馈",
            f"📝 已保存问题反馈（{hm}）\n"
            + ("正在发送给作者…" if upload else "可在设置页「问题反馈」导出"),
            6,
        )
    except Exception:
        pass
    if upload:  # 存好就自动发给作者（后台，不卡游戏）
        feedback_up.mark_pending(d)

        def _up():
            ok, why, again = feedback_up.send(d, kind)
            try:
                _note_hud(
                    "反馈",
                    f"📝 问题反馈（{hm}）"
                    + (
                        "已发送给作者"
                        if ok
                        else f"未发送：{why}\n"
                        + (
                            "下次启动自动重发"
                            if again
                            else "可在设置页「问题反馈」导出"
                        )
                    ),
                    6,
                )
            except Exception:
                pass
            bus.publish(
                "feedback",
                {
                    "path": str(zp),
                    "kind": kind,
                    "at": info["time"],
                    "sent": ok,
                    "why": why,
                },
            )

        threading.Thread(target=_up, daemon=True, name="feedback-up").start()
    bus.publish("feedback", {"path": str(zp), "kind": kind, "at": info["time"]})
    return {
        "path": str(zp),
        "dir": str(d),
        "kb": round(zp.stat().st_size / 1024),
        "count": len(list(_fb_dir().glob("*.zip"))),
        "upload": upload,
    }


def feedback_list():
    rows = []
    for z in sorted(
        _fb_dir().glob("*.zip"), key=lambda f: f.stat().st_mtime, reverse=True
    )[:30]:
        d = z.with_suffix("")
        note = ""
        try:
            note = json.loads((d / "情况.json").read_text(encoding="utf-8")).get(
                "note", ""
            )
        except Exception:
            pass
        rows.append(
            {
                "name": z.stem,
                "kb": round(z.stat().st_size / 1024),
                "note": note,
                "sent": (d / ".sent").exists(),
                "at": time.strftime("%m-%d %H:%M", time.localtime(z.stat().st_mtime)),
            }
        )
    return rows


def feedback_export():
    """把所有反馈 zip 再打成一个包放到桌面，并在文件夹里选中"""
    from .status import _desktop

    zs = sorted(_fb_dir().glob("*.zip"))
    if not zs:
        return {"error": "暂无反馈记录"}
    out = _desktop() / time.strftime("AT问题反馈_%Y%m%d_%H%M%S.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for f in zs:
            z.write(f, f.name)
    if WIN:
        try:
            import subprocess

            subprocess.Popen(["explorer", "/select,", str(out)])
        except Exception:
            pass
    return {"path": str(out), "files": len(zs), "kb": round(out.stat().st_size / 1024)}


def feedback_clear():
    n = 0
    for f in list(_fb_dir().iterdir()):
        try:
            shutil.rmtree(f) if f.is_dir() else f.unlink()
            n += 1
        except OSError:
            pass
    return {"removed": n}
