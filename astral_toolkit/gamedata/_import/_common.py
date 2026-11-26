"""各段导入共用的小工具：取源、列值清洗（_txt/_s/_num/_int/_lst）、坐标和逐条变换（_xyz/_rows）"""

from typing import Any

from .._sources import SourceBytes


def _d(sources: dict[str, SourceBytes], name: str, default: Any) -> Any:
    s = sources.get(name)
    return default if s is None or s.data is None else s.data


def _txt(v: Any) -> str | None:
    """可空文本列：字符串原样、其它（含 None）存 NULL——读端还原 dict 时 None 和 '' 分得开（批 3 要求）；
    类型不对也只是这一列为 NULL，不让整库建不出来"""
    return v if isinstance(v, str) else None


def _s(v: Any) -> str:
    """要算折叠键 / 不可空的地方：不是字符串当空串"""
    return v if isinstance(v, str) else ""


def _num(v: Any) -> int | float | None:
    """数值列：int / float（不含 bool）原样（int 就存 int，列不声明类型时 SQLite 也保留），其它 None"""
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _int(v: Any) -> int | None:
    """整数列：int（不含 bool）或整数值的 float，其它 None"""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None


def _lst(v: Any) -> list:
    return v if isinstance(v, list) else []


def _xyz(r):
    import math

    v = (float(r["x"]), float(r["y"]), float(r["z"]))
    if not all(math.isfinite(x) for x in v):
        raise ValueError("坐标不是有限数")
    return v


def _rows(raw, fn):
    """逐条变换，坏的跳过：返回 [(源下标, 变换结果)]"""
    out = []
    for i, r in enumerate(raw if isinstance(raw, list) else []):
        try:
            out.append((i, fn(r)))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return out
