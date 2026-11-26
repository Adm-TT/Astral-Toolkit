"""每个目标要什么材料（维科洛兑换 / 制造蓝图，数量已乘次数）（2026-11-26 从 crafting/goals.py 搬出来，只搬家）"""


# ---------------------------------------------------------------- 目标要什么


def _source(kind, ref):
    if kind == "wikelo":
        from . import wikelo

        return next((c for c in wikelo.load() if c["id"] == ref), None)
    from .crafting import by_key

    return by_key(ref)


def _title(kind, src):
    if kind == "wikelo":
        reward = src["rz"] or "、".join(src["rewards"][:2]) or src["te"]
        return f"维科洛：{src['t']}（换 {reward}）"
    from .crafting import display_name

    return f"制造：{display_name(src)}"


def requirements(goal):
    """[{"slot": 部件名或空, "alts": [{en, zh, qty, unit, minq}]}]，数量已乘次数"""
    src = _source(goal["kind"], goal["ref"])
    if not src:
        return None
    n = goal["times"]
    out = []
    if goal["kind"] == "wikelo":
        for r in src["req"]:
            out.append(
                {
                    "slot": "",
                    "alts": [
                        {
                            "en": r["n"],
                            "zh": r["z"],
                            "qty": (r["q"] or 1) * n,
                            "unit": r["u"],
                            "minq": 0,
                        }
                    ],
                }
            )
    else:
        from .crafting import material_zh

        for slot, opts, _mods in src["slots"]:
            alts = [
                {
                    "en": name,
                    "zh": material_zh(name),
                    "qty": qty * n,
                    "unit": "SCU" if k == "r" else "个",
                    "minq": minq if minq > 1 else 0,
                }
                for k, name, qty, minq in opts
            ]
            if alts:
                out.append({"slot": slot, "alts": alts})
    return out
