"""版本号比较（从 update/upgrade.py 拆出，只依赖 core.version.VERSION）"""

import re

from ..core.version import VERSION


def ver(text):
    """只取 x.y.z 三元组；清单、包名、旧逻辑在用。"""
    m = re.match(r"^\s*(\d+)\.(\d+)\.(\d+)", str(text or ""))
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def current():
    return ver(VERSION)


def vkey(text):
    """可比较大小的版本号（semver 规则）：x.y.z-beta.N 比同号 x.y.z 旧，beta.10 比 beta.9 新；认不出的最小。"""
    m = re.match(r"^\s*v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?", str(text or ""))
    if not m:
        return (0, 0, 0, 0, ())
    pre = m.group(4)
    parts = (
        tuple((0, int(x), "") if x.isdigit() else (1, 0, x) for x in pre.split("."))
        if pre
        else ()
    )
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), 0 if pre else 1, parts)


def current_key():
    return vkey(VERSION)
