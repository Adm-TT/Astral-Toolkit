"""制造联动（数据：scmdb.net，4.10.2；由 tools/build_crafting.py 生成 crafting.json，读取走游戏数据层 gamedata.crafting）

- 查蓝图：要哪些矿、多少 SCU、最低品质；矿的品质怎样影响成品属性；去哪挖；哪些任务给蓝图
- 反查：某种矿能做什么
- 扫描联动：扫到的矿石各成分品质，够做多少蓝图

规则在 labels / classify / materials / quality / mix / listing / reverse，这里留取数据、还没拆的排版和旧名字。
describe、header、uses_report 是取数据 + 排版，外面（目标、F8、物品查询）还在用，crafting 又不能反过来 import app：这些调用方都走用例以后再挪进排版文件（命令行 ask 2026-11-06 删了，F 段 B3）。
"""

from ..contracts.textkeys import blueprint_norm, blueprint_search_norm
from . import labels as _labels
from . import listing as _listing
from . import materials as _materials
from . import mix as _mix
from . import quality as _quality
from . import reverse as _reverse

# 旧名字：只留给还冻着的调用方，别处一律从纯规则文件拿（test_runtime_arch 管着）
# 目标（crafting/goals、tasks/goals）：目标链改从 crafting.labels / crafting.quality 拿时删
slot_zh = _labels.slot_zh
laser_total = _quality.laser_total
# 读屏（trade/inspector，熊老师的模块）：他改成从 crafting.reverse 拿时删
parse_mods = _reverse.parse_mods
# 库存（tasks/stock，冻着）：库存改从 crafting.reverse 拿时删
craft_text = _reverse.craft_text


def stats(bp, qualities):
    """成品各属性在给定材料品质下的「基础 → 强化 → 变化」（制造页属性统计表，1.6.47）。
    同一属性几个槽都影响时，倍率类各槽的百分比相加，加法类各槽相加（和游戏制造终端的算法一致）。
    qualities：{槽序号或槽名: 品质}；没填的槽按 500（商店货）算，并在 missing 里列出。
    返回 [{prop, name, key, base, unit, now, delta(倍率类是百分比，加法类是加的数), add, best, worst, lower, slots:[{slot, q, part}]}]"""
    from . import itemstats

    return _quality.stats(bp, qualities, itemstats.base_value)


def header(bp):
    """制造页的标题信息：中文名、英文名、类别、尺寸 / 等级 / 类别标签、厂商、制造时间"""
    from . import itemstats

    t = itemstats.tags(bp.get("u"))
    size = t.get("size")
    sz = bp.get("s") or ""
    if size is None and sz.startswith("size") and sz[4:].isdigit():
        size = int(sz[4:])
    cls_zh = {
        "Civilian": "民用",
        "Military": "军用",
        "Industrial": "工业",
        "Stealth": "隐形",
        "Competition": "竞速",
    }
    tags = []
    if size is not None:
        tags.append(f"S{size}")
    if t.get("grade") and str(t["grade"]).upper() in "ABCD":
        tags.append(f"{t['grade']} 级")
    cls = t.get("cls")
    if cls:
        tags.append(cls_zh.get(cls, cls))
    return {
        "zh": bp["z"] or "",
        "en": bp["n"],
        "kind": _labels.GEAR_ZH.get((bp["g"], bp["t"]), bp["t"] or bp["g"]),
        "tags": tags,
        "maker": bp["m"] or "",
        "sec": bp["sec"],
        "unlocked": bool(bp["d"]),
        "stats_version": itemstats.version() if t else "",
    }


_WARNED = set()
_EMPTY = None  # 库不可用 / 没有蓝图时用的空表（第一次用到时建）


def _catalog():
    """当前内容版本的蓝图和编号表（gamedata.crafting.catalog）；库不可用当成没有蓝图，同一个原因只记一次警告"""
    global _EMPTY
    from .. import gamedata

    why = None
    try:
        c = gamedata.crafting.catalog()
        if not c.data["blueprints"]:
            why = "库里没有蓝图"
    except gamedata.GamedataError as e:
        # 只记错误类型：消息里可能带数据目录的完整路径（含 Windows 用户名）
        c, why = None, f"游戏数据库不可用：{type(e).__name__}"
    if why is not None and why not in _WARNED:  # 同一个错只记一次，别刷日志
        _WARNED.add(why)
        import logging

        logging.getLogger(__name__).warning("制造数据读不到：%s", why)
    if c is None:
        if _EMPTY is None:
            from ..gamedata.crafting import Blueprints
            from collections import Counter

            _EMPTY = Blueprints({"blueprints": []}, {}, {}, Counter(), {})
        c = _EMPTY
    return c


def data():
    """{"blueprints": [bp…]}，bp 与 crafting.json 里的逐字一致；同一内容版本内每次返回同一批对象（bp_key 靠 id(bp)）。
    没有蓝图或库不可用时当成没有蓝图（别让整个目标清单、维科洛目标跟着报错）"""
    return _catalog().data


def blueprints():
    return data()["blueprints"]


def material_zh(name: str) -> str:
    from ..core.i18n import mineral_zh

    return _labels.ITEM_ZH.get(name) or mineral_zh(name)


def _keys():
    """(keys: {id(bp): 编号}, index: {编号: bp}, total: Counter(名字))，跟着 data() 那一版走；编号导入时按 contracts.blueprints.assign_keys 算好"""
    c = _catalog()
    return c.keys, c.index, c.total


def _owner(bp):
    """bp 所在的那份蓝图表：先查已缓存的那份（不开快照，bp_key / variant_note 一页要调上百次），
    不在里面再按当前版本取（开快照）"""
    from .. import gamedata

    c = gamedata.crafting.cached()
    if c is not None and id(bp) in c.keys:
        return c
    return _catalog()


def bp_key(bp) -> str:
    return _owner(bp).keys.get(id(bp), bp["n"])


def by_key(key):
    """按编号找蓝图；旧的只有名字的编号（以前存的目标）取同名的第一份"""
    _, index, _ = _keys()
    return index.get(key) or index.get(f"{key}#1")


def variant_note(bp) -> str:
    """同名多份配方时的区分说明，比如「配方 2/2 · 42 分钟」"""
    c = _owner(bp)
    total = c.total
    if total[bp["n"]] < 2:
        return ""
    k = c.keys.get(id(bp), bp["n"]).rsplit("#", 1)[-1]
    return f"配方 {k}/{total[bp['n']]} · {bp['sec'] // 60} 分钟"


def name_parts(bp):
    """(中文, 英文)：采矿装备的中文不带型号（霍夫斯泰德），其他用汉化包全名"""
    from ..core.i18n import gear_zh_of_item

    return gear_zh_of_item(bp["n"]) or bp["z"] or "", bp["n"]


def display_name(bp) -> str:
    """蓝图名「中文 English」（2026-10-26 统一写法）：「霍夫斯泰德 Hofstede-S2 Mining Laser」「卡纳 步枪 Karna Rifle」"""
    zh, en = name_parts(bp)
    return f"{zh} {en}" if zh else en


def for_item(name_en="", name_zh=""):
    """做这件东西的蓝图（英文名折叠后一样的第一份，没有再按中文名）；没有返回 None。比较键导入时算好（blueprints.norm_n / norm_z）"""
    from .. import gamedata

    try:
        return gamedata.crafting.for_item(
            blueprint_norm(name_en), blueprint_norm(name_zh)
        )
    except gamedata.GamedataError:  # 库不可用：当成没有蓝图
        return None


def _using(mineral):
    """用到这种原料的蓝图（按源顺序，每份一次）；库不可用当成没有"""
    from .. import gamedata

    try:
        return gamedata.crafting.using_material(mineral)
    except gamedata.GamedataError:
        return []


def search(query: str, limit: int = 20):
    """按中文或英文名搜索蓝图：完全匹配优先，再按包含匹配（候选由库按搜索键筛，分法和排序照旧）"""
    from .. import gamedata

    q = blueprint_search_norm(query.strip())
    if not q:
        return []
    try:
        rows = gamedata.crafting.containing(q)
    except gamedata.GamedataError:
        return []
    return _listing.search_rank(rows, q, limit)


def mat_summary(mineral, q=None):
    """多少份蓝图用到这种矿；给了品质再算其中多少份品质够（每个槽的最低品质都满足）"""
    return _materials.mat_summary(_using, mineral, q)


def browse(
    cat="", sub="", part="", maker="", q="", unlocked=False, offset=0, limit=60, mat=""
):
    """蓝图字典：按条件筛，按名字排（同一系列排在一起）。返回 {rows, total, cats, subs, parts, makers}
    mat：只看用到这种矿的蓝图（从扫描结果、矿物页点过来）"""
    return _listing.browse(
        blueprints,
        cat=cat,
        sub=sub,
        part=part,
        maker=maker,
        q=q,
        unlocked=unlocked,
        offset=offset,
        limit=limit,
        mat=mat,
    )


def describe(bp, with_locations: bool = True) -> str:
    """一份蓝图的完整中文说明"""
    from ..mining.data import best_price
    from ..mining.locations import where, zh_name

    kind = _labels.GEAR_ZH.get((bp["g"], bp["t"]), bp["t"] or bp["g"])
    lines = [
        f"【{display_name(bp)}】{kind}｜{bp['m'] or '—'}｜制造 {bp['sec'] // 60} 分 {bp['sec'] % 60} 秒"
        + ("｜默认已解锁" if bp["d"] else "")
    ]
    minerals = []
    for slot, opts, mods in bp["slots"]:
        alts = " 或 ".join(
            f"{material_zh(name)} {qty:g} {'SCU' if kind_ == 'r' else '个'}"
            + (f"（品质 ≥{minq}）" if minq > 1 else "")
            for kind_, name, qty, minq in opts
        )
        effect = "；".join(
            _quality.curve_text(p, segs, _labels.prop_zh(p, bp))
            for p, segs in _quality.group_mods(mods).items()
        )
        lines.append(
            f"  · {_labels.slot_zh(slot)}：{alts}"
            + (f"｜品质影响：{effect}" if effect else "")
        )
        minerals += [name for kind_, name, *_ in opts if kind_ == "r"]
    total = _quality.laser_total(bp)
    if total:
        lines.append(f"  · {total}")
    if with_locations and minerals:
        lines.append("  去哪挖：")
        for m in dict.fromkeys(minerals):
            rows = where(m)[:2]
            price, city = best_price(m)
            spots = (
                "，".join(f"{zh_name(loc)} {pct:.0f}%" for pct, loc in rows)
                or "SCMiner 没有船挖地点"
            )
            lines.append(
                f"    {material_zh(m)}：{spots}｜精炼后 {price:,}/SCU（{city or '无收购'}）"
            )
    if bp["src"]:
        lines.append(
            f"  蓝图来源（{bp['nsrc']} 个任务，列出前 {min(len(bp['src']), 5)} 个）："
        )
        for title, who, mtype, systems, chance in bp["src"][:5]:
            p = "" if chance >= 1 else f"，掉率 {chance:.0%}"
            lines.append(
                f"    {_labels.clean_title(title)}｜{who}｜{mtype}｜{systems or '—'}{p}"
            )
    elif not bp["d"]:
        lines.append("  蓝图来源：scmdb 的任务数据里没有找到")
    return "\n".join(lines)


def uses(mineral: str):
    """某种矿能做什么：返回 [(蓝图, 数量, 最低品质)]"""
    return _materials.uses(_using, mineral)


def uses_report(mineral: str, examples: int = 6) -> str:
    rows = uses(mineral)
    zh = material_zh(mineral)
    if not rows:
        return f"{zh}：没有蓝图用到它。"
    by_kind = {}
    for bp, qty, minq in rows:
        by_kind.setdefault(_labels.GEAR_ZH.get((bp["g"], bp["t"]), bp["t"]), []).append(
            (bp, qty, minq)
        )
    lines = [f"【{zh}】被 {len(rows)} 份蓝图用到："]
    for kind, items in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        high = sum(1 for _, _, q in items if q >= 500)
        ex = "、".join(dict.fromkeys(display_name(b) for b, _, _ in items))
        ex = "、".join(
            list(dict.fromkeys(display_name(b) for b, _, _ in items))[:examples]
        )
        lines.append(
            f"  {kind} {len(items)} 份"
            + (f"（其中 {high} 份要求品质 ≥500）" if high else "")
            + f"：{ex}{' 等' if len(items) > examples else ''}"
        )
    return "\n".join(lines)


def effect(bp, qualities):
    """蓝图每个材料槽在给定品质下对成品属性的影响。qualities：{槽序号或槽名: 品质}，没给的槽不算。
    返回 [{slot, idx, material, q, props:[{name, now, best, worst, pos(0~1，越大越好), text, next_gate}]}]"""
    return _quality.effect(bp, qualities, material_zh)


def curves_for(mineral: str):
    """用这种矿的部件里出现过的属性曲线：{(属性, 曲线): [蓝图类别...]}"""
    return _quality.curves_for(blueprints, mineral)


def quality_hints(composition) -> list:
    """扫描联动：[(矿物, 百分比, 品质)] → 每种矿的品质对制造意味着什么（分段门槛最重要，如发电机能量格）"""
    return _quality.quality_hints(composition, curves_for, uses, material_zh)


def mix_targets(bp):
    """这份蓝图里每种矿：要多少 SCU、品质到多少换档（只列分档的属性，连续变化的没有「过线」一说）"""
    return _mix.mix_targets(bp, material_zh)


def solve_slots(bp, mods):
    """按说明框里的加成倒推每个材料槽的品质：每个槽只在这种材料的固定几档品质里找（mining/quality 的 tier_values），
    同一属性几个槽都影响时各槽百分比相加（和制造终端一致，那把枪验证过）。正负号怎么比、exact 什么意思见
    crafting.reverse.solve_slots。返回 {"slots": [{idx, slot, mat, q}], "avg": 平均品质, "exact": …}；对不上返回 None"""
    from ..mining.quality import tier_values as tiers

    return _reverse.solve_slots(bp, mods, tiers, material_zh)


def craft_slots(bp):
    """入库时手填：这个蓝图会影响属性的材料槽 [{idx, slot, mat, mat_en, tiers}]"""
    from ..mining.quality import tier_values as tiers

    return _reverse.craft_slots(bp, tiers, material_zh)
