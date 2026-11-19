"""地点补丁：把自己记的路标导出成固定格式的文件、把别人给的文件装进来（2026-11-19）

设计：docs/superpowers/specs/2026-11-14-nav-base-and-place-patch.md 第四～六节（老大 2026-11-14 定的格式）。

文件长这样（JSON，一份补丁一个文件）：
    {"格式": "AT 地点补丁 1", "游戏版本": "4.10.3", "日期": "2026-11-19", "AT 版本": "1.1.4", "作者": "…",
     "地点": [{"中文名": "…", "英文名": "", "所在": "站:rr_p2_l4", "坐标": [x, y, z]}, …]}
所在三种写法：「站:<站的编号>」「星球:<星球名>」「太空:<星系名>」。坐标单位千米；站里的点和这个站自带地点同一个坐标系
（太空里的站是星系坐标，跟着星球转的站 / 主城是星球坐标），和路标文件里存的一样。

规矩：只收这一种格式；多一项、少一项、认不出的站 / 星球 / 星系，都是整份不收，并说清是第几个地点、哪一项、为什么。
补丁只能加地点：不改、不删自带的地点，不碰设置、库存、自己的路标。别人的补丁和「我的路标」分开放（userdata/patches）。
"""

import json
import math
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..core.paths import USER, write_json

FORMAT_HEAD = "AT 地点补丁 "
FORMAT_VERSION = 1
FORMAT = f"{FORMAT_HEAD}{FORMAT_VERSION}"
HEAD_KEYS = ("格式", "游戏版本", "日期", "AT 版本", "作者")
PLACE_KEYS = ("中文名", "英文名", "所在", "坐标")
MAX_BYTES = 1_000_000  # 文件上限 1 MB
MAX_PLACES = 2000
MAX_NAME = 40
MAX_HEAD_TEXT = 60
SPACE_MAX_KM = (
    1e9  # 太空里的点：每个数的绝对值不超过这么多千米（已知星系都在几千万千米以内）
)
BODY_MIN, BODY_ABOVE_KM = (
    0.5,
    2000.0,
)  # 星球上的点：离球心不小于半径的一半、不高出地表这么多千米
SITE_SPAN_KM = 50.0  # 站里的点：离这个站已知的点不超过这么远
KINDS = ("站", "星球", "太空")

PATCH_DIR = USER / "patches"  # 一份补丁一个文件，原样保存；升级和普通卸载不动它
STATE = PATCH_DIR / "_state.json"  # 哪几份停用了

_CTRL = re.compile(
    r"[\x00-\x1f\x7f-\x9f\u2028\u2029\ud800-\udfff]"
)  # 换行、控制字符、落单的代理字符
# Windows 不让当文件名用的名字（带不带扩展名都不行）
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class PatchError(ValueError):
    """这份补丁不收：话是给玩家看的"""


# ---------------------------------------------------------------- 认得哪些站 / 星球 / 星系
class Known:
    """查「所在」认不认得用的：bodies = {星球名: 半径千米}，systems = 星系名，site(编号) → 这个站的坐标系和已知点"""

    def __init__(
        self,
        bodies: Dict[str, float],
        systems: Sequence[str],
        site: Callable[[str], Optional[Dict[str, Any]]],
    ):
        self.bodies = bodies
        self.systems = set(systems)
        self.site = site


def known() -> Known:
    """照现在的导航数据造一份 Known"""
    from .navigate import load
    from .transit import city_places

    data = load()
    bodies = {name: float(b.get("r") or 0) / 1000 for name, b in data["bodies"].items()}
    systems = {b.get("sys") for b in data["bodies"].values()} - {None, ""}
    by_site: Dict[str, List[Dict[str, Any]]] = {}
    for q in city_places():  # 站的「壳」：不看可见清单，没列出来的站也认
        if q.get("city"):
            by_site.setdefault(q["city"], []).append(q)
            if q.get("sys"):
                systems.add(q["sys"])

    def site(code: str) -> Optional[Dict[str, Any]]:
        pts = by_site.get(code)
        if not pts:
            return None
        q = pts[0]
        return {
            "space": bool(q.get("space")),
            "b": q["b"],
            "sys": q.get("sys") or "",
            "points": [(p["x"], p["y"], p["z"]) for p in pts],
        }

    return Known(bodies, sorted(systems), site)


# ---------------------------------------------------------------- 检查
def _text(value: Any, what: str, limit: int, empty_ok: bool = True) -> str:
    if not isinstance(value, str):
        raise PatchError(f"{what}不是文字")
    if _CTRL.search(value):
        raise PatchError(f"{what}里有换行或控制字符")
    if len(value) > limit:
        raise PatchError(f"{what}超过 {limit} 个字")
    if not empty_ok and not value.strip():
        raise PatchError(f"{what}是空的")
    return value


def _where(value: Any, kn: Known) -> tuple[str, str]:
    if not isinstance(value, str) or ":" not in value:
        raise PatchError("「所在」要写成「站:编号」「星球:名字」「太空:星系」其中一种")
    kind, _, name = value.partition(":")
    if kind not in KINDS or not name or _CTRL.search(name) or len(name) > MAX_HEAD_TEXT:
        raise PatchError("「所在」要写成「站:编号」「星球:名字」「太空:星系」其中一种")
    if kind == "站" and kn.site(name) is None:
        raise PatchError(f"「所在」里的站「{name}」AT 不认识")
    if kind == "星球" and name not in kn.bodies:
        raise PatchError(f"「所在」里的星球「{name}」AT 不认识")
    if kind == "太空" and name not in kn.systems:
        raise PatchError(f"「所在」里的星系「{name}」AT 不认识")
    return kind, name


def _xyz(value: Any, kind: str, name: str, kn: Known) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise PatchError("「坐标」要正好三个数")
    for v in value:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise PatchError("「坐标」里有不是数的东西")
        if (
            isinstance(v, int) and abs(v) > SPACE_MAX_KM
        ):  # 几百位的整数：先拦住，转成小数会出错
            raise PatchError("「坐标」太大，不像是这个星系里的位置")
        if not math.isfinite(v):
            raise PatchError("「坐标」里有不是数的东西")
    x, y, z = (float(v) for v in value)
    frame = kn.site(name) if kind == "站" else None
    if kind == "太空" or (frame and frame["space"]):
        if max(abs(x), abs(y), abs(z)) > SPACE_MAX_KM:
            raise PatchError("「坐标」太大，不像是这个星系里的位置")
    if kind == "星球" or (frame and not frame["space"]):
        r = kn.bodies.get(frame["b"] if frame else name) or 0.0
        d = math.sqrt(x * x + y * y + z * z)
        if r and not (r * BODY_MIN <= d <= r + BODY_ABOVE_KM):
            raise PatchError("「坐标」离这个星球太远或太深，不像是它上面的位置")
    if frame and min(math.dist((x, y, z), p) for p in frame["points"]) > SITE_SPAN_KM:
        raise PatchError(f"「坐标」离「{name}」这个站太远，不像是站里的位置")
    return x, y, z


def _bytes(raw: Any) -> bytes:
    if isinstance(raw, str):
        try:
            return raw.encode("utf-8")
        except UnicodeEncodeError:
            raise PatchError("读不出文件内容") from None
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    raise PatchError("读不出文件内容")


def check(raw: Any, kn: Optional[Known] = None) -> Dict[str, Any]:
    """raw：文件内容（字节或文字）→ 查过的补丁 {"head": {...}, "places": [{"zh","en","kind","name","xyz"}]}；不合格抛 PatchError"""
    raw = _bytes(raw)
    if len(raw) > MAX_BYTES:
        raise PatchError("文件超过 1 MB")
    try:
        obj = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, RecursionError):  # 不是 JSON、编码不对、套了几千层
        raise PatchError("这不是地点补丁文件（不是 JSON）") from None
    if not isinstance(obj, dict):
        raise PatchError("这不是地点补丁文件")
    fmt = obj.get("格式")
    if not isinstance(fmt, str) or not fmt.startswith(FORMAT_HEAD):
        raise PatchError("这不是地点补丁文件（没有「格式」那一行）")
    ver = fmt[len(FORMAT_HEAD) :]
    if not (ver.isascii() and ver.isdigit() and len(ver) <= 4 and ver[0] != "0"):
        raise PatchError("这份补丁的「格式」AT 不认识")
    if int(ver) > FORMAT_VERSION:
        raise PatchError("这份补丁是更新的格式，需要先更新 AT")
    if set(obj) != set(HEAD_KEYS) | {"地点"}:
        extra = sorted(set(obj) - set(HEAD_KEYS) - {"地点"})
        lost = [k for k in (*HEAD_KEYS, "地点") if k not in obj]
        raise PatchError(
            "文件开头的项目不对："
            + "；".join(
                s
                for s in (
                    "多了「" + "、".join(extra) + "」" if extra else "",
                    "少了「" + "、".join(lost) + "」" if lost else "",
                )
                if s
            )
        )
    head = {
        "格式": fmt,
        "游戏版本": _text(obj["游戏版本"], "「游戏版本」", MAX_HEAD_TEXT),
        "日期": _text(obj["日期"], "「日期」", MAX_HEAD_TEXT),
        "AT 版本": _text(obj["AT 版本"], "「AT 版本」", MAX_HEAD_TEXT),
        "作者": _text(obj["作者"], "「作者」", MAX_NAME),
    }
    rows = obj["地点"]
    if not isinstance(rows, list):
        raise PatchError("「地点」不是一张列表")
    if not rows:
        raise PatchError("这份补丁里一个地点都没有")
    if len(rows) > MAX_PLACES:
        raise PatchError(f"地点超过 {MAX_PLACES} 个")
    kn = kn or known()
    places = []
    for i, row in enumerate(rows, 1):
        try:
            if not isinstance(row, dict) or set(row) != set(PLACE_KEYS):
                raise PatchError("要正好「中文名、英文名、所在、坐标」四项")
            zh = _text(row["中文名"], "「中文名」", MAX_NAME)
            en = _text(row["英文名"], "「英文名」", MAX_NAME)
            if not zh.strip() and not en.strip():
                raise PatchError("中文名和英文名至少要有一个")
            kind, name = _where(row["所在"], kn)
            xyz = _xyz(row["坐标"], kind, name, kn)
        except PatchError as e:
            raise PatchError(f"第 {i} 个地点：{e}") from None
        places.append(
            {"zh": zh.strip(), "en": en.strip(), "kind": kind, "name": name, "xyz": xyz}
        )
    return {"head": head, "places": places}


# ---------------------------------------------------------------- 导出
def export(
    waypoints: Sequence[Dict[str, Any]],
    author: str = "",
    *,
    game_version: str,
    at_version: str,
    date: str,
) -> Dict[str, Any]:
    """自己的路标（路标文件里的行）→ 补丁内容。名字只有英文字母数字的放「英文名」，其余放「中文名」"""
    places = []
    for w in waypoints:
        name = str(w.get("n") or "").strip()
        if not name:
            continue
        if w.get("city"):
            where = "站:" + w["city"]
        elif w.get("space"):
            where = "太空:" + str(w.get("sys") or str(w.get("b", "")).lstrip("@"))
        else:
            where = "星球:" + w["b"]
        ascii_only = all(ord(c) < 128 for c in name)
        places.append(
            {
                "中文名": "" if ascii_only else name,
                "英文名": name if ascii_only else "",
                "所在": where,
                "坐标": [float(w["x"]), float(w["y"]), float(w["z"])],
            }
        )
    return {
        "格式": FORMAT,
        "游戏版本": game_version,
        "日期": date,
        "AT 版本": at_version,
        "作者": author.strip(),
        "地点": places,
    }


def dumps(patch: Dict[str, Any]) -> str:
    """补丁内容 → 文件里的文字：文件头一项一行，地点一个一行，记事本打开看得清"""

    def j(v: Any) -> str:
        return json.dumps(v, ensure_ascii=False)

    head = ",\n".join(f" {j(k)}: {j(patch[k])}" for k in HEAD_KEYS)
    rows = ",\n".join("  " + j(p) for p in patch["地点"])
    return "{\n" + head + ',\n "地点": [\n' + rows + "\n ]\n}\n"


# ---------------------------------------------------------------- 装上的补丁（userdata/patches）
def _disabled() -> set[str]:
    try:
        return set(json.loads(STATE.read_text(encoding="utf-8")).get("disabled") or [])
    except (OSError, ValueError, AttributeError):
        return set()


def _files() -> List[Path]:
    try:
        return sorted(p for p in PATCH_DIR.glob("*.json") if p.name != STATE.name)
    except OSError:
        return []


def _safe_name(name: str) -> str:
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", Path(name or "").stem).strip(" ._")
    stem = _CTRL.sub("_", stem)[:60].strip(" ._") or "补丁"
    return "补丁_" + stem if stem.split(".")[0].upper() in _RESERVED else stem


def install(raw: Any, filename: str = "", kn: Optional[Known] = None) -> Dict[str, Any]:
    """查一遍，合格就原样存进 userdata/patches（重名的后面加序号）；不合格抛 PatchError，什么都不存"""
    data = _bytes(raw)
    patch = check(data, kn)
    stem = _safe_name(filename)
    path = PATCH_DIR / f"{stem}.json"
    try:
        PATCH_DIR.mkdir(parents=True, exist_ok=True)
        n = 2
        while True:
            if path.name != STATE.name:
                try:
                    with open(
                        path, "xb"
                    ) as f:  # 只新建：已经有同名的就换下一个名字，绝不盖掉
                        f.write(data)
                    break
                except FileExistsError:
                    pass
            path = PATCH_DIR / f"{stem}_{n}.json"
            n += 1
    except OSError as e:
        raise PatchError(f"补丁存不进去：{e}") from None
    finally:
        _cache["key"] = None
    return {"file": path.name, "count": len(patch["places"]), **patch["head"]}


def installed(
    game_version: str = "", kn: Optional[Known] = None
) -> List[Dict[str, Any]]:
    """装着的补丁：[{"file","作者","日期","游戏版本","AT 版本","count","enabled","stale","error"}]；
    stale = 记的时候的游戏版本和现在不一样（位置可能变了）；文件后来被改坏了的带 error、不生效"""
    off = _disabled()
    kn = kn or known()
    out = []
    for p in _files():
        row: Dict[str, Any] = {"file": p.name, "enabled": p.name not in off}
        try:
            patch = check(p.read_bytes(), kn)
            row.update(
                {k: patch["head"][k] for k in ("作者", "日期", "游戏版本", "AT 版本")},
                count=len(patch["places"]),
                stale=bool(game_version and patch["head"]["游戏版本"] != game_version),
                error="",
            )
        except (PatchError, OSError) as e:
            row.update(count=0, stale=False, error=str(e), enabled=False)
        out.append(row)
    return out


def set_enabled(file: str, on: bool) -> bool:
    """整份停用 / 启用；没有这份返回 False"""
    if file not in {p.name for p in _files()}:
        return False
    off = _disabled()
    (off.discard if on else off.add)(file)
    PATCH_DIR.mkdir(parents=True, exist_ok=True)
    write_json(STATE, {"disabled": sorted(off)}, indent=1)
    _cache["key"] = None
    return True


def remove(file: str) -> bool:
    """整份删掉（玩家在列表里点的删除）；没有这份返回 False"""
    for p in _files():
        if p.name == file:
            p.unlink()
            off = _disabled()
            if file in off:
                off.discard(file)
                write_json(STATE, {"disabled": sorted(off)}, indent=1)
            _cache["key"] = None
            return True
    return False


# ---------------------------------------------------------------- 给搜索 / 导航用的点
_cache: Dict[str, Any] = {"key": None, "rows": []}


def _row(
    place: Dict[str, Any], file: str, i: int, author: str, kn: Known
) -> Dict[str, Any]:
    zh, en = place["zh"], place["en"]
    row: Dict[str, Any] = {
        "n": f"{zh}（{en}）" if zh and en else zh or en,
        "t": "Waypoint",
        "x": place["xyz"][0],
        "y": place["xyz"][1],
        "z": place["xyz"][2],
        "qt": 0,
        "id": f"patch:{file}:{i}",  # 和自己的路标、别的补丁里同名的点分得开
        "patch": {"file": file, "author": author},
    }
    frame = kn.site(place["name"]) if place["kind"] == "站" else None
    if place["kind"] == "太空" or (frame and frame["space"]):
        sysname = frame["sys"] if frame else place["name"]
        row.update(b="@" + sysname, sys=sysname, space=True)
    else:
        row["b"] = frame["b"] if frame else place["name"]
    if frame:
        row["city"] = place["name"]
    return row


def points() -> List[Dict[str, Any]]:
    """启用着的补丁里的点，长得和路标一样（t="Waypoint"，多一项 patch = 来自哪份、作者）。
    站里的点补上站名、站的「上」和区域，按站内方式带路。文件没变就用上次读的"""
    files = _files()
    off = _disabled()
    try:
        key = tuple((p.name, p.stat().st_mtime_ns, p.name in off) for p in files)
    except OSError:
        key = (time.time(),)
    if _cache["key"] == key:
        return _cache["rows"]
    rows: List[Dict[str, Any]] = []
    if files:
        from .transit import site_area_at
        from .waypoints import _with_site

        kn = known()
        for p in files:
            if p.name in off:
                continue
            try:
                patch = check(p.read_bytes(), kn)
            except (PatchError, OSError):
                continue  # 后来被改坏的文件：不生效，列表里会写原因
            for i, place in enumerate(patch["places"]):
                row = _row(place, p.name, i, patch["head"]["作者"], kn)
                if row.get("city"):
                    area = site_area_at(row["city"], place["xyz"])
                    if area:
                        row["area_id"] = area
                    row = _with_site(row)
                rows.append(row)
    _cache.update(key=key, rows=rows)
    return rows
