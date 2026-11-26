"""目标清单本身的存取：userdata/goals.json 的读、写、加、改、删（2026-11-26 从 crafting/goals.py 搬出来，只搬家）

改写都在 _LOCK 里读-改-写；外面照旧经 crafting.goals 用这些名字（goals.py 转出去）。"""

import json
import time
import uuid

from ..core.paths import USER
from .goal_needs import _source, _title

FILE = USER / "goals.json"
MAX_TIMES = 99


# ---------------------------------------------------------------- 存取


def load():
    """目标表（查询用：读不到就当没有）"""
    try:
        return _load_strict()
    except RuntimeError:
        return []


def _load_strict():
    """目标表（改写前用）：文件读不到或坏了就抛错，别当成空表（细查 2026-10-28：否则接着加一个目标会把整份覆盖掉）"""
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except OSError as e:
        raise RuntimeError(f"目标文件暂时读不到：{e}")
    except ValueError as e:
        raise RuntimeError(f"目标文件损坏（userdata 里的 goals.json）：{e}")
    return (
        [
            g
            for g in data
            if isinstance(g, dict) and g.get("kind") in ("wikelo", "craft")
        ]
        if isinstance(data, list)
        else []
    )


def save(goals):
    from ..core.paths import write_json

    write_json(FILE, goals, indent=1)


def add(kind, ref, times=1):
    if kind not in ("wikelo", "craft"):
        raise ValueError("目标仅支持维科洛兑换或制造")
    src = _source(kind, ref)
    if not src:
        raise ValueError("未找到此兑换或蓝图")
    with _LOCK:
        return _add(kind, ref, times, src)


def _add(kind, ref, times, src):
    goals = _load_strict()
    for g in goals:  # 同一个目标再加一次：次数 +1
        if g["kind"] == kind and g["ref"] == ref:
            g["times"] = min(MAX_TIMES, g["times"] + max(1, int(times)))
            save(goals)
            return goals
    goals.append(
        {
            "id": uuid.uuid4().hex[:10],
            "kind": kind,
            "ref": ref,
            "times": max(1, min(MAX_TIMES, int(times))),
            "title": _title(kind, src),
            "at": time.time(),
        }
    )
    save(goals)
    return goals


_LOCK = __import__(
    "threading"
).RLock()  # 读-改-写连在一起（审查 2026-10-28：两个请求同时改会丢一个）


def update(gid, times=None, move=0, remove=False):
    with _LOCK:
        return _update(gid, times, move, remove)


def _update(gid, times=None, move=0, remove=False):
    goals = _load_strict()
    i = next((n for n, g in enumerate(goals) if g["id"] == gid), None)
    if i is None:
        raise ValueError("未找到此目标")
    if remove:
        goals.pop(i)
    else:
        if times is not None:
            goals[i]["times"] = max(1, min(MAX_TIMES, int(times)))
        if move:
            j = max(0, min(len(goals) - 1, i + (1 if move > 0 else -1)))
            goals[i], goals[j] = goals[j], goals[i]
    save(goals)
    return goals
