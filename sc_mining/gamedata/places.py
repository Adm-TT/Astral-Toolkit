"""地点 topic：地名中文对照（place_names / place_codes）

place_names 存两份：src='zh' 是 places_zh.json（汉化包对出来的，键是规范化英文名），src='extra' 是 places_extra_zh.json
（从游戏数据补的）。读的一方决定看哪份：names.poi_zh 用合并表（extra 盖过 zh）；position 那一路只看 zh（以前就是只读
places_zh.json）。"""

from ._cache import VersionCache
from ._ready import use

_merged: VersionCache[dict[str, str]] = VersionCache()


def _load_merged(s) -> dict[str, str]:
    out: dict[str, str] = {}
    for src in ("zh", "extra"):  # 后放的盖过先放的
        out.update(
            s.execute(
                "select norm_key, zh from place_names where src = ? order by source_order",
                (src,),
            )
        )
    return out


def poi_names(snap=None) -> dict[str, str]:
    """规范化英文名 → 中文的合并表（places_extra_zh 盖过 places_zh），按内容版本缓存一份。
    names.poi_zh 在搜索里一次要查几千个名字，查整张表的 dict 比逐个 SQL 快（调用方别改它）"""
    with use(snap) as s:
        return _merged.get(s, _load_merged)


def zh_of(norm_key: str, snap=None) -> str | None:
    """places_zh（不看 extra）里这个规范化键的中文；没有返回 None"""
    with use(snap) as s:
        rows = s.execute(
            "select zh from place_names where src = 'zh' and norm_key = ?", (norm_key,)
        )
    return rows[0][0] if rows else None


def zh_by_prefix(prefix: str, snap=None) -> str | None:
    """places_zh 里以 prefix 开头（区分大小写）的键中最短的那个的中文；同样长取源里靠前的。没有返回 None"""
    with use(snap) as s:
        rows = s.execute(
            "select zh from place_names where src = 'zh' and substr(norm_key, 1, ?) = ? "
            "order by length(norm_key), source_order limit 1",
            (len(prefix), prefix),
        )
    return rows[0][0] if rows else None


def code_zh(code: str, snap=None) -> str | None:
    """place_codes_zh.json：小写地点代码 → 中文；没有返回 None"""
    with use(snap) as s:
        rows = s.execute("select zh from place_codes where code = ?", (code,))
    return rows[0][0] if rows else None
