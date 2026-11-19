"""地点补丁的几个用例：把自己的路标导出成补丁文件、装别人给的补丁、看装了哪些、停用 / 删除（2026-11-19）

规则都在 navigation/patches.py；这里只管取数、存文件、把「不收」的原因交给页面。
"""

import subprocess
import time

from ..system import WIN, _desktop, _version


def _reveal(path):
    """在文件夹里选中导出的文件"""
    if WIN:
        try:
            subprocess.Popen(["explorer", "/select,", str(path)])
        except Exception:
            pass


def _game_version():
    from ...mining.data import GAME_VERSION

    return GAME_VERSION


def patch_export(names=None, author=""):
    """我的路标 → 补丁文件，存到桌面并在文件夹里选中。names：要导出的路标名，不给就是全部"""
    from ...navigation import patches as P
    from ...navigation.waypoints import _waypoints_strict

    try:
        rows = _waypoints_strict()
    except RuntimeError as e:
        return {"error": str(e)}
    if names:
        want = set(names)
        rows = [w for w in rows if w.get("n") in want]
    if not rows:
        return {"error": "没有可以导出的路标"}
    author = str(author or "").strip()
    patch = P.export(
        rows,
        author,
        game_version=_game_version(),
        at_version=_version(),
        date=time.strftime("%Y-%m-%d"),
    )
    text = P.dumps(patch)
    try:  # 自己导出的也照导入的规矩查一遍：导出来的文件别人一定装得上
        P.check(text)
    except P.PatchError as e:
        return {"error": f"导不出来：{e}"}
    out = _desktop() / time.strftime("AT地点补丁_%Y%m%d_%H%M%S.json")
    out.write_text(text, encoding="utf-8")
    _reveal(out)
    return {"path": str(out), "count": len(patch["地点"])}


def patch_import(text="", name=""):
    """装一份补丁：text = 文件内容，name = 文件名。不合格不装，error 里说明是第几个地点、哪一项、为什么"""
    from ...navigation import patches as P

    try:
        info = P.install(text or "", name)
    except P.PatchError as e:
        return {"error": f"这份补丁不收：{e}"}
    return {
        "file": info["file"],
        "count": info["count"],
        "author": info["作者"],
        "game_version": info["游戏版本"],
        "stale": info["游戏版本"] != _game_version(),
    }


def patch_list():
    """装着的补丁"""
    from ...navigation import patches as P

    return {
        "rows": [
            {
                "file": r["file"],
                "author": r.get("作者", ""),
                "date": r.get("日期", ""),
                "game_version": r.get("游戏版本", ""),
                "at_version": r.get("AT 版本", ""),
                "count": r["count"],
                "enabled": r["enabled"],
                "stale": r["stale"],
                "error": r["error"],
            }
            for r in P.installed(_game_version())
        ]
    }


def patch_toggle(file="", on=True):
    """整份停用 / 启用"""
    from ...navigation import patches as P

    if not P.set_enabled(str(file), bool(on)):
        return {"error": "没有这份补丁"}
    return {"file": file, "enabled": bool(on)}


def patch_delete(file=""):
    """整份删掉。正在导航去它里面的点：这一趟照常走完，之后搜不到了"""
    from ...navigation import patches as P

    if not P.remove(str(file)):
        return {"error": "没有这份补丁"}
    return {"file": file}
