"""材料用途的纯规则：蓝图要多少矿、某种矿能做哪些蓝图。

只吃传进来的蓝图和取用矿蓝图的函数，不读库、不读文件、不读汉化包。
"""


def needs(bp, mineral):
    """这份蓝图要这种矿：[(数量 SCU, 最低品质)]（一个槽一条）"""
    return [
        (qty, minq)
        for slot, opts, mods in bp["slots"]
        for kind_, name, qty, minq in opts
        if kind_ == "r" and name == mineral
    ]


def mat_summary(_using, mineral, q=None):
    """多少份蓝图用到这种矿；给了品质再算其中多少份品质够（每个槽的最低品质都满足）"""
    rows = [bp for bp in _using(mineral) if needs(bp, mineral)]
    ok = (
        None
        if q is None
        else sum(1 for bp in rows if all(q >= m for _, m in needs(bp, mineral)))
    )
    gated = sum(1 for bp in rows if any(m > 1 for _, m in needs(bp, mineral)))
    gates = sorted({m for bp in rows for _, m in needs(bp, mineral) if m > 1})
    return {
        "count": len(rows),
        "ok": ok,
        "gated": gated,
        "gates": gates,
        "gated_ok": None if q is None else ok - (len(rows) - gated),
    }


def uses(_using, mineral):
    """某种矿能做什么：返回 [(蓝图, 数量, 最低品质)]"""
    out = []
    for bp in _using(mineral):
        for slot, opts, mods in bp["slots"]:
            for kind_, name, qty, minq in opts:
                if kind_ == "r" and name == mineral:
                    out.append((bp, qty, minq))
    return out
