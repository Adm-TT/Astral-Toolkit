"""制造 / 维科洛行为基线（CR-B0）：用本机真实数据录一份输出，改完再录一份逐项比较。

用法（在项目根目录）：
  .venv\\Scripts\\python.exe -X utf8 tools\\runtime_baseline_crafting.py --out <输出.json>
  .venv\\Scripts\\python.exe -X utf8 tools\\runtime_baseline_crafting.py --compare <改前.json> <改后.json>

不联网、不写 userdata、不导入 overlay。网络读取函数在脚本内换成断网替身，退出时还原。
"""

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OFFLINE = "基线断网"
SEARCH_WORDS = [
    "",
    "  ",
    "Hofstede",
    "霍夫斯泰德",
    "Helmet",
    "头盔",
    "Pyro",
    "S2",
    "不存在的东西",
]
WIKELO_SEARCH_WORDS = [
    "",
    "Polaris",
    "极地",
    "Jaclium",
    "杰金",
    "RCMBNT",
    "Wikelo Favor",
    "载具",
    "不存在的东西",
]
QUALITY_NAMES = (
    "None",
    "空字典",
    "槽0品质500",
    "全部1000",
    "全部1",
    "字符串槽0品质750",
)
CURVE_QUALITIES = (0, 1, 250, 500, 750, 999, 1000, 1001)
MIX_SCENARIOS = [
    ("合箱", 0, 0, 2, []),
    ("正常混合", 10, 700, 2, [[600, 5], [900, 10]]),
    ("多箱混合", 0, 800, 2, [[500, 3], [950, 2], [700, 4]]),
    ("材料不足", 50, 700, 2, [[600, 5]]),
    ("目标过高", 5, 1000, 0, [[999, 5]]),
    ("非数字", 1, 1, 2, [["abc", 1]]),
    ("空串", 1, 1, 2, [["", 3]]),
]
CRAFT_TEXT_CASES = [
    [
        {"slot": "框架", "q": 858},
        {"slot": "线缆", "q": 916},
        {"slot": "稳压器", "q": 959},
    ],
    [],
    [{"slot": "枪管", "q": 0}, {"slot": "外壳", "q": 1000}],
]
WIKELO_EXTRA_PAIRS = [
    ("Polar", "极地"),
    ("Jaclium", "杰金"),
    ("Jaclium (Ore)", "杰金矿石"),
]


# ---------------------------------------------------------------- 调用适配
# CR-B1～B6 拆制造、维科洛代码时只改这一节。
def call_craft_effect(key="", qualities=None):
    from astral_toolkit.tasks import goals

    return goals.craft_effect(key=key, qualities=qualities)


def call_craft_search(q=""):
    from astral_toolkit.tasks import goals

    return goals.craft_search(q=q)


def call_craft_browse(**kwargs):
    from astral_toolkit.tasks import goals

    return goals.craft_browse(**kwargs)


def call_craft_detail(key=""):
    from astral_toolkit.tasks import goals

    return goals.craft_detail(key=key)


def call_craft_stats(key="", qualities=None):
    from astral_toolkit.tasks import goals

    return goals.craft_stats(key=key, qualities=qualities)


def call_craft_mix(need=0, target=0, margin=2, boxes=()):
    from astral_toolkit.tasks import goals

    return goals.craft_mix(need=need, target=target, margin=margin, boxes=boxes)


def call_wikelo_search(q=""):
    from astral_toolkit.tasks import goals

    return goals.wikelo_search(q=q)


def call_wikelo_detail(key=""):
    from astral_toolkit.tasks import goals

    return goals.wikelo_detail(key=key)


def call_craft_text(slots):
    from astral_toolkit.crafting import reverse

    return reverse.craft_text(slots)


def call_mat_summary(mineral, q=None):
    from astral_toolkit.crafting import crafting

    return crafting.mat_summary(mineral, q)


def call_uses_report(mineral):
    from astral_toolkit.crafting import crafting

    return crafting.uses_report(mineral)


def call_quality_hints(composition):
    from astral_toolkit.crafting import crafting

    return crafting.quality_hints(composition)


def call_curve_value(segs, q):
    from astral_toolkit.crafting import quality

    return quality.curve_value(segs, q)


def call_for_item(name_en="", name_zh=""):
    from astral_toolkit.crafting import crafting

    return crafting.for_item(name_en=name_en, name_zh=name_zh)


def call_craft_slots(bp):
    from astral_toolkit.crafting import crafting

    return crafting.craft_slots(bp)


def call_mix_targets(bp):
    from astral_toolkit.crafting import crafting

    return crafting.mix_targets(bp)


def call_laser(key, quality=500):
    from astral_toolkit.mining import laser

    slots = laser.craft_slots(key)
    craft = {s["slot"]: quality for s in slots} if slots else None
    return {
        "head_blueprint": laser.head_blueprint(key),
        "craft_slots": slots,
        "craft_mult": laser.craft_mult(key, craft),
    }


def call_laser_heads():
    from astral_toolkit.mining import laser

    return laser.HEADS


def call_mineral_info(name=""):
    from astral_toolkit.tasks import trade

    return trade.mineral_info(name=name)


def call_wikelo_uses(name_en="", name_zh=""):
    from astral_toolkit.crafting import wikelo

    return wikelo.uses(name_en=name_en, name_zh=name_zh)


def call_wikelo_uses_text(name_en="", name_zh=""):
    from astral_toolkit.crafting import wikelo

    return wikelo.uses_text(name_en, name_zh)


def call_wikelo_source_note(name):
    from astral_toolkit.crafting import wikelo

    return wikelo.source_note(name)


def call_wikelo_describe(c, where=None):
    from astral_toolkit.crafting import wikelo_rules

    return wikelo_rules.describe(c, where=where)


def call_group_mods(mods):
    from astral_toolkit.crafting import quality

    return quality.group_mods(mods)


def call_bp_key(bp):
    from astral_toolkit.crafting import crafting

    return crafting.bp_key(bp)


def call_crafting_blueprints():
    from astral_toolkit.crafting import crafting

    return crafting.blueprints()


def call_wikelo_load():
    from astral_toolkit.crafting import wikelo

    return wikelo.load()


def call_clear_caches():
    from astral_toolkit.tasks import goals

    goals.clear_caches()


def _offline(*_args, **_kwargs):
    raise OSError(OFFLINE)


class _Offline:
    """把网络读取换成断网替身，退出时逐项还原。"""

    def __init__(self):
        self._saved = []

    def __enter__(self):
        from astral_toolkit.core import net as net_mod
        from astral_toolkit.crafting import loot as loot_mod
        from astral_toolkit.crafting import shops as shops_mod

        self._patch(net_mod, "read", _offline)
        self._patch(loot_mod, "_get", _offline)
        self._patch(shops_mod, "_get", _offline)
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        for obj, name, old in reversed(self._saved):
            setattr(obj, name, old)
        return False

    def _patch(self, obj, name, value):
        self._saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)


def _reason(exc):
    text = str(exc)
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


# ---------------------------------------------------------------- 元信息
def _git_head() -> str:
    try:
        done = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return done.stdout.strip() if done.returncode == 0 else ""
    except Exception:
        return ""


def _file_stamp(path) -> dict[str, Any]:
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return {"path": str(p), "exists": False}
    return {
        "path": str(p),
        "exists": True,
        "size": st.st_size,
        "mtime": st.st_mtime,
    }


def _gamedata_version() -> str:
    try:
        from astral_toolkit import gamedata

        return str(gamedata.version())
    except Exception:
        return ""


def _meta() -> dict[str, Any]:
    try:
        from astral_toolkit.core import paths

        data = paths.DATA
    except Exception:
        data = ROOT / "data"
    return {
        "git": _git_head(),
        "gamedata_version": _gamedata_version(),
        "data": {
            "crafting": _file_stamp(data / "crafting.json"),
            "wikelo": _file_stamp(data / "wikelo.json"),
            "item_stats": _file_stamp(data / "item_stats.json"),
        },
        "python": platform.python_version(),
        "PYTHONHASHSEED": os.environ.get("PYTHONHASHSEED", ""),
    }


# ---------------------------------------------------------------- 选择与通用工具
def _bp_sort_key(bp):
    return (
        str(bp.get("g") or ""),
        str(bp.get("t") or ""),
        str(bp.get("n") or ""),
        bp.get("sec") or 0,
    )


def _has_minq(bp):
    for _slot, opts, _mods in bp.get("slots") or []:
        for _kind, _name, _qty, minq in opts:
            if (minq or 0) > 1:
                return True
    return False


def _picked_minerals(picked):
    names = {
        name
        for bp in picked
        for _slot, opts, _mods in bp.get("slots") or []
        for kind, name, _qty, _minq in opts
        if kind == "r" and name
    }
    return sorted(names)[:12]


def _select_blueprints(bps):
    rows = sorted(bps, key=_bp_sort_key)
    count = len(rows)
    step = max(1, count // 40) if count else 1
    picked = []
    seen = set()

    def add(bp):
        if id(bp) not in seen:
            seen.add(id(bp))
            picked.append(bp)

    for bp in rows[::step][:40]:
        add(bp)
    cats = {(b.get("g"), b.get("t")) for b in picked}
    for bp in rows:  # 每个类别（g, t）至少一份：按步长挑会漏掉份数少的类别
        cat = (bp.get("g"), bp.get("t"))
        if cat not in cats:
            cats.add(cat)
            add(bp)
    for bp in rows:
        if bp.get("t") == "mininglaser":
            add(bp)

    groups = []
    by_name = {}
    for bp in rows:
        by_name.setdefault(bp.get("n") or "", []).append(bp)
    for _name, group in by_name.items():
        if len(group) > 1:
            groups.append(group)
            if len(groups) >= 3:
                break
    for group in groups:
        for bp in group:
            add(bp)

    minq_count = 0
    for bp in rows:
        if _has_minq(bp):
            add(bp)
            minq_count += 1
            if minq_count >= 3:
                break
    return picked


def _quality_cases(bp):
    slot_count = len(bp.get("slots") or [])
    return [
        QUALITY_NAMES[0],
        None,
        QUALITY_NAMES[1],
        {},
        QUALITY_NAMES[2],
        {0: 500},
        QUALITY_NAMES[3],
        {idx: 1000 for idx in range(slot_count)},
        QUALITY_NAMES[4],
        {idx: 1 for idx in range(slot_count)},
        QUALITY_NAMES[5],
        {"0": "750"},
    ]


def _quality_case_pairs(bp):
    values = _quality_cases(bp)
    return list(zip(values[0::2], values[1::2]))


def _record(items, path, fn):
    try:
        call_clear_caches()
        value = fn()
    except Exception as exc:
        value = {"_error": type(exc).__name__, "_message": str(exc)}
    items[path] = value
    return value


def _add_unique(out, seen, value):
    if value not in seen:
        seen.add(value)
        out.append(value)


def _unique_label(base, used):
    label = base or "空"
    out = label
    n = 2
    while out in used:
        out = f"{label}#{n}"
        n += 1
    used.add(out)
    return out


def _missing_key(existing, prefix):
    existing = set(existing)
    candidate = prefix
    n = 1
    while candidate in existing:
        n += 1
        candidate = f"{prefix}{n}"
    return candidate


def _blueprint_key_or_none(bp):
    return call_bp_key(bp) if bp else None


def _simplify_uses(rows):
    out = []
    for c, q, u in rows:
        cid = c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
        out.append([cid, q, u])
    return out


# ---------------------------------------------------------------- 制造
def _collect_craft_search(items, picked):
    queries = []
    seen = set()
    for q in SEARCH_WORDS:
        _add_unique(queries, seen, q)
    for bp in picked:
        n = bp.get("n") or ""
        z = bp.get("z") or ""
        if n:
            _add_unique(queries, seen, n)
            _add_unique(queries, seen, n.lower())
        if z:
            _add_unique(queries, seen, z)
            if len(z) > 1:
                _add_unique(queries, seen, z[:-1])
    for q in queries:
        _record(items, f"craft_search.{q}", lambda q=q: call_craft_search(q))


def _collect_craft_browse(items, minerals):
    base = _record(items, "craft_browse.default", call_craft_browse)
    if isinstance(base, dict):
        for facet, arg in (("cats", "cat"), ("subs", "sub"), ("parts", "part")):
            for row in (base.get(facet) or [])[:5]:
                value = row.get("key") if isinstance(row, dict) else None
                if value in (None, ""):
                    continue
                _record(
                    items,
                    f"craft_browse.{arg}.{value}",
                    lambda value=value, arg=arg: call_craft_browse(**{arg: value}),
                )
        makers = base.get("makers") or []
        if makers:
            first = makers[0]
            maker = first.get("key") if isinstance(first, dict) else first
            if maker:
                _record(
                    items,
                    f"craft_browse.maker.{maker}",
                    lambda maker=maker: call_craft_browse(maker=maker),
                )
    _record(items, "craft_browse.q.Arclight", lambda: call_craft_browse(q="Arclight"))
    _record(items, "craft_browse.unlocked", lambda: call_craft_browse(unlocked=True))
    _record(items, "craft_browse.offset.30", lambda: call_craft_browse(offset=30))
    for mineral in minerals[:5]:
        for mq in (None, 500, 900):
            label = "None" if mq is None else str(mq)
            _record(
                items,
                f"craft_browse.mat.{mineral}.{label}",
                lambda mineral=mineral, mq=mq: call_craft_browse(mat=mineral, mq=mq),
            )
    mat = minerals[0] if minerals else ""
    _record(
        items,
        "craft_browse.mq.abc",
        lambda mat=mat: call_craft_browse(mat=mat, mq="abc"),
    )


def _collect_craft_details(items, picked, keys):
    for bp, key in zip(picked, keys):
        _record(items, f"craft_detail.{key}", lambda key=key: call_craft_detail(key))
        for case_name, qualities in _quality_case_pairs(bp):
            _record(
                items,
                f"craft_effect.{key}.{case_name}",
                lambda key=key, qualities=qualities: call_craft_effect(key, qualities),
            )
            _record(
                items,
                f"craft_stats.{key}.{case_name}",
                lambda key=key, qualities=qualities: call_craft_stats(key, qualities),
            )
        _record(items, f"mix_targets.{key}", lambda bp=bp: call_mix_targets(bp))
        _record(items, f"craft_slots.{key}", lambda bp=bp: call_craft_slots(bp))

    missing = _missing_key(set(keys), "__CR_B0_MISSING_BLUEPRINT__")
    _record(items, f"craft_detail.{missing}", lambda: call_craft_detail(missing))
    _record(
        items,
        f"craft_effect.{missing}.None",
        lambda: call_craft_effect(missing, None),
    )
    _record(
        items,
        f"craft_stats.{missing}.None",
        lambda: call_craft_stats(missing, None),
    )
    _record(items, f"mix_targets.{missing}", lambda: None)
    _record(items, f"craft_slots.{missing}", lambda: call_craft_slots(None))


def _collect_craft_mix(items):
    for name, need, target, margin, boxes in MIX_SCENARIOS:
        _record(
            items,
            f"craft_mix.{name}",
            lambda need=need, target=target, margin=margin, boxes=boxes: call_craft_mix(
                need=need, target=target, margin=margin, boxes=boxes
            ),
        )


def _collect_minerals(items, minerals):
    for mineral in minerals:
        for q in (None, 500, 900):
            label = "None" if q is None else str(q)
            _record(
                items,
                f"mat_summary.{mineral}.{label}",
                lambda mineral=mineral, q=q: call_mat_summary(mineral, q),
            )
        _record(
            items,
            f"uses_report.{mineral}",
            lambda mineral=mineral: call_uses_report(mineral),
        )
        _record(
            items,
            f"mineral_info.{mineral}",
            lambda mineral=mineral: call_mineral_info(mineral),
        )


def _collect_quality_hints(items, minerals):
    pcts = ([60, 25, 15], [40, 35, 25], [50, 30, 20])
    base_q = (500, 800, 1000)
    for scene in range(3):
        take = minerals[scene * 3 : scene * 3 + 3] or minerals[:3]
        composition = []
        for idx, mineral in enumerate(take):
            pct = pcts[scene][idx % len(pcts[scene])]
            q = min(1000, base_q[scene] + idx * 50)
            composition.append((mineral, pct, q))
        _record(
            items,
            f"quality_hints.{scene}",
            lambda composition=composition: call_quality_hints(composition),
        )


def _collect_curve_value(items, picked, keys):
    for bp, key in zip(picked, keys):
        slots = bp.get("slots") or []
        if not slots:
            continue
        gm = call_group_mods(slots[0][2])
        for prop, segs in gm.items():
            _record(
                items,
                f"curve_value.{key}.{prop}",
                lambda segs=segs: [
                    {"q": q, "value": call_curve_value(segs, q)}
                    for q in CURVE_QUALITIES
                ],
            )


def _collect_craft_text(items):
    for idx, slots in enumerate(CRAFT_TEXT_CASES):
        _record(items, f"craft_text.{idx}", lambda slots=slots: call_craft_text(slots))


def _collect_for_item(items, picked):
    en_names, zh_names, folded = [], [], []
    seen_en, seen_zh, seen_fold = set(), set(), set()
    for bp in picked:
        n = bp.get("n") or ""
        z = bp.get("z") or ""
        if n and n not in seen_en:
            seen_en.add(n)
            en_names.append(n)
        if z and z not in seen_zh:
            seen_zh.add(z)
            zh_names.append(z)
        f = n.lower().replace(" ", "")
        if f and f not in seen_fold:
            seen_fold.add(f)
            folded.append(f)

    for name in en_names:
        _record(
            items,
            f"for_item.{name}",
            lambda name=name: _blueprint_key_or_none(call_for_item(name_en=name)),
        )
    for name in zh_names:
        _record(
            items,
            f"for_item.zh.{name}",
            lambda name=name: _blueprint_key_or_none(call_for_item(name_zh=name)),
        )
    for name in folded:
        _record(
            items,
            f"for_item.fold.{name}",
            lambda name=name: _blueprint_key_or_none(call_for_item(name_en=name)),
        )

    missing = _missing_key(
        set(en_names) | set(zh_names) | set(folded), "__CR_B0_NO_SUCH_ITEM__"
    )
    _record(
        items,
        f"for_item.{missing}",
        lambda missing=missing: _blueprint_key_or_none(call_for_item(name_en=missing)),
    )


def _laser_record(key):
    data = call_laser(key)
    head = data["head_blueprint"]
    return {
        "head_blueprint": call_bp_key(head) if head else None,
        "craft_slots": data["craft_slots"],
        "craft_mult": data["craft_mult"],
    }


def _collect_laser(items):
    heads = call_laser_heads()
    if not isinstance(heads, dict):
        return
    by_size = {}
    for key, head in sorted(
        heads.items(), key=lambda kv: (str(kv[1].get("size", "")), str(kv[0]))
    ):
        if not isinstance(head, dict):
            continue
        size = head.get("size")
        if size is None:
            continue
        by_size.setdefault(size, key)
    for size, key in sorted(by_size.items(), key=lambda kv: str(kv[0])):
        _record(items, f"laser.{size}", lambda key=key: _laser_record(key))


# ---------------------------------------------------------------- 维科洛
def _collect_wikelo_search(items, contracts):
    queries = []
    seen = set()
    for q in WIKELO_SEARCH_WORDS:
        _add_unique(queries, seen, q)
    for c in contracts[:20]:
        for value in (c.get("t") or "", c.get("rz") or ""):
            if value:
                _add_unique(queries, seen, value)
    for q in queries:
        _record(items, f"wikelo_search.{q}", lambda q=q: call_wikelo_search(q))


def _after_search_detail(q, key):
    call_wikelo_search(q)
    return call_wikelo_detail(key)


def _collect_wikelo_detail(items, contracts):
    ids = [c.get("id") for c in contracts]
    for c in contracts:
        key = c.get("id") or ""
        _record(items, f"wikelo_detail.{key}", lambda key=key: call_wikelo_detail(key))
    missing = _missing_key(set(ids), "__CR_B0_MISSING_WIKELO__")
    _record(items, f"wikelo_detail.{missing}", lambda: call_wikelo_detail(missing))
    if contracts:
        first = contracts[0]
        q = first.get("t") or first.get("id") or ""
        key = first.get("id") or ""
        _record(
            items,
            "wikelo_detail.__after_search__",
            lambda q=q, key=key: _after_search_detail(q, key),
        )


def _wikelo_use_scenarios(contracts):
    pairs = []
    seen_pairs = set()
    for c in contracts:
        for r in c.get("req") or []:
            n = (r.get("n") or "").strip()
            z = (r.get("z") or "").strip()
            if not n and not z:
                continue
            pair = (n, z)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                pairs.append(pair)
    pairs.sort(key=lambda p: (p[0], p[1]))

    raw = []
    for n, z in pairs[:60]:
        raw.append((n or z, n, z))
    for n, z in WIKELO_EXTRA_PAIRS:
        raw.append((n or z, n, z))

    names = sorted({name for pair in pairs for name in pair if name})
    for name in names[:60]:
        if any(n == name for n, _z in pairs):
            raw.append((name, name, ""))
        if any(z == name for _n, z in pairs):
            raw.append((f"中文.{name}", "", name))
    for name in names[:20]:
        truncated = name[:5]
        if not truncated:
            continue
        raw.append((truncated, truncated, ""))
        raw.append((f"中文.{truncated}", "", truncated))

    out = []
    seen_args = set()
    for label, en, zh in raw:
        args = (en.strip(), zh.strip())
        if args in seen_args:
            continue
        seen_args.add(args)
        out.append((label, args[0], args[1]))
    return out


def _collect_wikelo_uses(items, contracts):
    used = set()
    for label, en, zh in _wikelo_use_scenarios(contracts):
        label = _unique_label(label, used)
        _record(
            items,
            f"wikelo_uses.{label}",
            lambda en=en, zh=zh: _simplify_uses(
                call_wikelo_uses(name_en=en, name_zh=zh)
            ),
        )
        _record(
            items,
            f"wikelo_uses_text.{label}",
            lambda en=en, zh=zh: call_wikelo_uses_text(name_en=en, name_zh=zh),
        )


def _collect_wikelo_source_note(items, contracts):
    names = sorted(
        {
            (r.get("n") or "").strip()
            for c in contracts
            for r in c.get("req") or []
            if (r.get("n") or "").strip()
        }
    )
    for name in names[:60]:
        _record(
            items,
            f"wikelo_source_note.{name}",
            lambda name=name: call_wikelo_source_note(name),
        )


def _collect_wikelo_describe(items, contracts):
    for c in contracts[:10]:
        key = c.get("id") or ""
        _record(
            items,
            f"wikelo_describe.{key}",
            lambda c=c: call_wikelo_describe(c, None),
        )


# ---------------------------------------------------------------- 录制与比较
def collect() -> dict[str, Any]:
    with _Offline():
        try:
            from astral_toolkit import gamedata

            gamedata.ensure()
        except Exception as exc:
            return {"skipped": f"gamedata 不可用：{_reason(exc)}"}

        meta = _meta()
        try:
            bps = list(call_crafting_blueprints())
            contracts = list(call_wikelo_load())
        except Exception as exc:
            return {"skipped": f"gamedata 不可用：{_reason(exc)}"}

        picked = _select_blueprints(bps)
        keys = [call_bp_key(bp) for bp in picked]
        minerals = _picked_minerals(picked)
        meta["picked"] = {
            "blueprints": keys,
            "minerals": minerals,
            "wikelo": [c.get("id") for c in contracts],
        }

        items: dict[str, Any] = {}
        _collect_craft_search(items, picked)
        _collect_craft_browse(items, minerals)
        _collect_craft_details(items, picked, keys)
        _collect_craft_mix(items)
        _collect_minerals(items, minerals)
        _collect_quality_hints(items, minerals)
        _collect_curve_value(items, picked, keys)
        _collect_craft_text(items)
        _collect_for_item(items, picked)
        _collect_laser(items)
        _collect_wikelo_search(items, contracts)
        _collect_wikelo_detail(items, contracts)
        _collect_wikelo_uses(items, contracts)
        _collect_wikelo_source_note(items, contracts)
        _collect_wikelo_describe(items, contracts)
        return {"meta": meta, "items": items}


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _diff(left, right, path, out):
    if len(out) >= 20:
        return
    if type(left) is not type(right):
        out.append((path, left, right))
        return
    if isinstance(left, dict):
        left_keys = list(left)
        right_keys = list(right)
        if left_keys != right_keys:
            out.append((path + ".<keys>", left_keys, right_keys))
            if len(out) >= 20:
                return
        for key in left_keys:
            if len(out) >= 20:
                return
            if key in right:
                _diff(left[key], right[key], f"{path}.{key}", out)
            else:
                out.append((f"{path}.{key}", left[key], "<缺失>"))
        for key in right_keys:
            if len(out) >= 20:
                return
            if key not in left:
                out.append((f"{path}.{key}", "<缺失>", right[key]))
        return
    if isinstance(left, list):
        if len(left) != len(right):
            out.append((path, left, right))
            return
        for idx, (a, b) in enumerate(zip(left, right)):
            if len(out) >= 20:
                return
            _diff(a, b, f"{path}[{idx}]", out)
        return
    if left != right:
        out.append((path, left, right))


def _show(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _compare(path_a, path_b) -> int:
    left = _load_json(path_a).get("items", {})
    right = _load_json(path_b).get("items", {})
    diffs: list[tuple[str, Any, Any]] = []
    _diff(left, right, "items", diffs)
    if not diffs:
        print("items 相同")
        return 0
    for path, a, b in diffs:
        print(path)
        print(f"  A = {_show(a)}")
        print(f"  B = {_show(b)}")
    if len(diffs) >= 20:
        print("（最多显示 20 处差异）")
    return 1


def main(argv=None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description="CR-B0 制造 / 维科洛行为基线")
    ap.add_argument("--out", metavar="JSON", help="录制输出 JSON 路径")
    ap.add_argument(
        "--compare",
        nargs=2,
        metavar=("A", "B"),
        help="比较两个基线 JSON 的 items",
    )
    args = ap.parse_args(args_list)

    if args.compare:
        return _compare(args.compare[0], args.compare[1])
    if not args.out:
        ap.error("需要 --out 或 --compare")

    if os.environ.get("PYTHONHASHSEED") != "0":
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = "0"
        cmd = [
            sys.executable,
            "-X",
            "utf8",
            str(Path(__file__).resolve()),
            *args_list,
        ]
        return subprocess.run(cmd, env=env, check=False).returncode

    result = collect()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )
    if "skipped" in result:
        print(f"跳过：{result['skipped']}")
    else:
        print(f"基线写到 {out}：{len(result.get('items', {}))} 项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
