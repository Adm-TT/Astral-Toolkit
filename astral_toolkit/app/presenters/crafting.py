"""制造相关接口的展示（CR-B4）：用例取好的东西 → 窗口制造页的 JSON（字段、顺序、文字和以前逐字一样）。
只排版，不取数据；原来写在 tasks/goals.py 的 craft_search / craft_browse / _craft_struct / craft_detail 里。"""

from ...crafting.classify import category_zh, part_of
from ...crafting.labels import (
    GEAR_ZH,
    SUB_ZH,
    clean_title,
    prop_zh,
    slot_zh,
)
from ...crafting.materials import needs
from ...crafting.quality import (
    LOWER_BETTER,
    PROP_KEY,
    curve_text,
    group_mods,
)


def present_search(hits):
    out = []
    for h in hits:
        bp = h["bp"]
        note = h["note"]
        out.append(
            {
                "key": h["key"],
                "name": h["name"] + (f"｜{note}" if note else ""),
                "zh": h["zh"],
                "en": h["en"],
                "note": note,
                "kind": GEAR_ZH.get((bp["g"], bp["t"]), bp["t"] or bp["g"]),
            }
        )
    return out


def present_browse(f):
    mat = f["mat"]
    mq = f["mq"]
    rows = []
    for item in f["rows"]:
        bp = item["bp"]
        tags = [
            tag
            for tag in (
                part_of(bp),
                SUB_ZH.get(bp["s"] or "", bp["s"] or ""),
                item["note"],
            )
            if tag
        ]
        row = {
            "key": item["key"],
            "name": item["name"],
            "kind": category_zh(bp),
            "tags": " · ".join(tags),
            "maker": bp["m"] or "",
            "unlocked": bool(bp["d"]),
        }
        if mat:
            n = needs(bp, mat)
            minq = max(m for _, m in n)
            row["need"] = f"{f['mat_zh']} {sum(x for x, _ in n):g} SCU" + (
                f"（品质 ≥{minq}）" if minq > 1 else ""
            )
            if mq is not None and minq > 1:
                row["ok"] = mq >= minq
        rows.append(row)
    out = {**f["page"], "rows": rows}
    if mat:
        out["mat"] = {
            "en": mat,
            "zh": f["mat_zh"],
            "q": mq,
            **f["summary"],
        }
    return out


def present_struct(f):
    h = f["head"]
    h["note"] = f["note"]
    bp = f["bp"]
    slots = []
    for idx, (slot, opts, mods) in enumerate(bp["slots"]):
        mats = [
            {
                "kind": kind,
                "en": name,
                "zh": f["mat_zh"][name],
                "qty": qty,
                "unit": "SCU" if kind == "r" else "个",
                "minq": minq,
            }
            for kind, name, qty, minq in opts
        ]
        gm = group_mods(mods)
        curves = [
            {
                "prop": pz,
                "name": prop_zh(pz, bp),
                "key": PROP_KEY.get(pz, ""),
                "add": segs[0][4],
                "lower": pz in LOWER_BETTER,
                "segs": [list(x[:4]) for x in segs],
                "text": curve_text(pz, segs, prop_zh(pz, bp)),
            }
            for pz, segs in gm.items()
        ]
        slots.append(
            {
                "idx": idx,
                "slot": slot_zh(slot),
                "mats": mats,
                "minq": max([m["minq"] for m in mats] + [0]),
                "curves": curves,
            }
        )
    mine = [
        {
            "en": m["en"],
            "zh": f["mat_zh"][m["en"]],
            "spots": [{"loc": loc, "pct": round(pct)} for pct, loc in m["spots"]],
            "price": m["price"],
            "city": m["city"] or "",
        }
        for m in f["mine"]
    ]
    src = [
        {
            "title": clean_title(t),
            "who": w,
            "kind": k,
            "systems": sy,
            "chance": ch,
        }
        for t, w, k, sy, ch in bp["src"]
    ]
    return {
        "head": h,
        "slots": slots,
        "mine": mine,
        "sources": src,
        "nsrc": bp["nsrc"],
    }


def present_detail(f):
    if f is None:
        return {"error": "未找到此蓝图"}
    note = f["note"]
    text = f["text"]
    if note:
        first, _, rest = text.partition("\n")
        text = f"{first}｜{note}\n{rest}" if rest else f"{first}｜{note}"
    return {
        "key": f["key"],
        "text": text,
        "mix": f["mix"],
        **present_struct(f["struct"]),
    }
