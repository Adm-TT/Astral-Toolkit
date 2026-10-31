"""扫描到的飞船信号（红外 IR / 电磁 EM / 截面 CS）→ 可能是哪几种船

数据：data/ship_signatures.json，从 erkul.games（LIVE 4.10.2）整理：
  cs      三个方向的截面（已乘装甲系数），从小到大。游戏里显示的截面随你看它的角度变化，
          正对船头时接近最小值，侧面/上方看时接近较大的值，所以只要落在「最小 ~ 最大」之间都算可能。
  em_max  默认配置下电源、冷却、护盾、量子引擎、雷达等全部开满时的电磁估算上限
  ir_max  红外估算上限
截面基本只看船体大小形状，最可靠；红外、电磁随开机状态/加速/开火变化很大，只用来排除「明显超出上限」的船。
"""

import json
from functools import lru_cache

from ..core.paths import DATA

TOL = 0.12  # 截面允许的误差（读数取整、装甲改装、角度不在三个主方向上）
SLACK = 1.6  # 电磁/红外超过估算上限多少倍才算不可能（加速、开火时会冲高）


@lru_cache(maxsize=1)
def ships():
    return json.loads((DATA / "ship_signatures.json").read_text(encoding="utf-8"))[
        "ships"
    ]


def _cs_score(cs, axes):
    """截面匹配度：0 最好；不在范围内返回 None"""
    lo, hi = axes[0] * (1 - TOL), axes[-1] * (1 + TOL)
    if not lo <= cs <= hi:
        return None
    return min(abs(cs - a) / a for a in axes)  # 离哪个主方向最近


def match(cs, em=None, ir=None, limit=6):
    """[(船, 匹配度)]，匹配度越小越像；同一外形的变体（如各种 Aurora）合并成一行"""
    if not cs:
        return []
    hits = []
    for s in ships():
        sc = _cs_score(cs, s["cs"])
        if sc is None:
            continue
        if em and s["em_max"] and em > s["em_max"] * SLACK:
            continue
        if ir and s["ir_max"] and ir > s["ir_max"] * SLACK:
            continue
        hits.append((s, sc))
    hits.sort(key=lambda h: (h[1], h[0]["name"]))
    out, seen = [], {}
    for s, sc in hits:
        key = tuple(s["cs"])
        if key in seen:  # 同一船体的变体：并到第一行
            seen[key]["variants"].append(s.get("zh") or s["name"])
            continue
        row = dict(s, score=sc, variants=[])
        seen[key] = row
        out.append(row)
    return out[:limit]


def describe(cs, em=None, ir=None, limit=4):
    rows = match(cs, em, ir, limit)
    if not rows:
        return [f"截面 {cs:,}：没有对得上的船"]
    lines = []
    for r in rows:
        name = r.get("zh") or r["name"]
        more = (
            f"（同外形：{'、'.join(r['variants'][:3])}{'等' if len(r['variants']) > 3 else ''}）"
            if r["variants"]
            else ""
        )
        lines.append(f"{name}{more}")
    return lines
