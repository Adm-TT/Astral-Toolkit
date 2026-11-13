"""掉落查询（目录迁移 Q3 从 crafting/loot.py 拆来）：这件东西在哪些地方的箱子里会开出来，副本专属矿去哪开采，
船挖矿物去哪挖。数据来自 scl.miao.network（从游戏文件解析的掉落表）；概率是该站算出的「单个箱子开出这件东西的最高概率」，只作参考。

- 整条查询路径不联网（2026-11-13 老大定：玩家端不再连 scl.miao.network，索引和明细都跟数据包来）
- 找物品只查游戏数据库：物品索引随数据包来（loot_index.json，导进库），掉落索引缺了也不在这里下
- 单件掉落明细：先查随数据包发布的整包，再查老版本留下的本机缓存（infrastructure/persistence/loot_details.py），
  都没有就抛 NoDetail（「这件物品暂时没有掉落明细」）
- 按名字挑候选、分组、汇总、认副本专属矿这些纯规则在 catalog/loot.py
"""

import re

from ...catalog.loot import (
    INSTANCE_ORES,
    exact_candidates,
    group_info,
    instance_ore,
    mine_groups,
    partial_hits,
    pick_exact,
    ship_groups,
    summary,
)
from ...contracts.textkeys import fold_mixed_loose as _fold
from ...infrastructure.persistence import loot_details


def _index_meta(snap=None):
    """游戏数据库里掉落索引的版本信息 {"version": …}；没有掉落索引、或库不可用返回 None"""
    from ... import gamedata
    from ...gamedata import loot as gd_loot

    try:
        return gd_loot.index_meta(snap)
    except gamedata.GamedataError:
        return None


def _wiki_classes(name_en):
    """物品查询（wiki）里这个英文名对应的全部游戏类名（含 alt）；没有返回空集。在 find 里调时用 find 钉住的快照"""
    try:
        from ...gamedata import loot as gd_loot

        return set(gd_loot.wiki_classes(_fold(name_en)))
    except Exception:
        return set()


def find(name_en="", name_zh=""):
    """按名字找物品：[(uuid, 英文名, 中文名, 稀有度)]，完全同名的排前面。
    同名的有好几个实体时，先要物品查询（wiki）里这个名字的类名，再去掉 NPC 专用、测试这些变体，有掉落的在前。
    名字只是开头像 / 包含的（Zeus 探索头盔 → Zeus 探索头盔 Echo）：物品查询里本来就有这个物品时不算。
    数据来自游戏数据库（掉落索引缺了不联网下，等数据包）；库不可用时返回空"""
    from ... import gamedata
    from ...gamedata import loot as gd_loot

    ke, kz = _fold(name_en), _fold(name_zh)
    try:
        gamedata.ensure()
        with gamedata.snapshot() as s:  # 精确、wiki 类名、部分匹配钉在同一个版本上
            exact = exact_candidates(gd_loot.exact(ke, kz, s))
            if exact:
                good = _wiki_classes(name_en or exact[0][1])  # 源顺序第一个，排序前取
                return pick_exact(exact, good)
            if name_en and _wiki_classes(name_en):
                return []
            return partial_hits(gd_loot.rows(s), ke, kz)
    except gamedata.GamedataError:
        return []


class NoDetail(Exception):
    """这件物品本机没有掉落明细：数据包的整包里没有，老版本留下的单件缓存里也没有（不再上网现查）"""


_UUID_RE = re.compile(r"[0-9A-Za-z\-]{1,64}")
_VER_RE = re.compile(r"\w[\w.\-]{0,63}")


def detail(uuid):
    """单件物品的掉落明细：整包 → 老版本留下的本机缓存；都没有抛 NoDetail。不联网"""
    version = (_index_meta() or {}).get("version", "4.10.2LIVE")
    # 要拼进缓存路径：只认字母数字、点、横线，别让 ..\ 之类跑到缓存目录外面
    if not isinstance(uuid, str) or not _UUID_RE.fullmatch(uuid):
        raise ValueError("物品编号格式不对")
    if not isinstance(version, str) or not _VER_RE.fullmatch(version):
        raise ValueError("掉落数据版本号格式不对")
    hit = loot_details.from_zip(uuid, version)  # 先查整包（数据包带来的）
    if hit is not None:
        return hit
    cached = loot_details.read_cached(version, uuid)
    if cached is not loot_details.MISSING:
        return cached
    raise NoDetail("这件物品暂时没有掉落明细")


def mine_info(key, top=5):
    """副本专属矿的开采点：{name, mine: True, note, groups: [{p, box, regions}], more}；
    没有掉落索引（数据包还没到）、库不可用返回 None；石头都没有明细给 {error}"""
    from ... import gamedata
    from ...gamedata import loot as gd_loot

    want, skip = INSTANCE_ORES[key]
    try:
        gamedata.ensure()
        with gamedata.snapshot() as s:  # 索引版本和石头行钉同一个版本
            has = (
                gd_loot.index_meta(s) is not None
            )  # 库在、只是没有掉落索引（有索引、只是没有行不算）
            rocks = gd_loot.by_cls_prefix(want, s) if has else ()
        if not has:
            return None  # 没有掉落索引：等数据包，不在这里下
    except (
        gamedata.GamedataError
    ):  # 库不可用：不在查询路径里读 JSON / 联网（收口 2，待做 ⑮）
        return None
    rocks = [r for r in rocks if not (skip and r.cls_lower.startswith(skip))]
    best = {}  # 地区 → (概率, 位置说明)
    missing = 0
    for r in rocks:
        try:
            d = detail(r.uuid)
        except NoDetail:
            missing += 1  # 这块石头没有明细：跳过，别的石头照样算
            continue
        except Exception as e:
            return {"error": f"开采点数据暂时取不到（{e}）"}
        for region, p, where in summary(d, top=99):
            loc = where.split("｜")[0] if where else ""
            if region not in best or p > best[region][0]:
                best[region] = (p, loc)
    if rocks and missing == len(rocks):
        return {"error": "开采点数据暂时没有"}
    rows, more = mine_groups(best, top)
    from ...core.i18n import mineral_zh

    en = "Carinite (Pure)" if key == "carinitepure" else key.capitalize()
    zh = mineral_zh(en) if key != "carinitepure" else "科力晶（纯）"
    return {
        "name": zh,
        "en": en,
        "mine": True,
        "src": "scl.miao.network 开采点出现概率",
        "note": "副本专属矿：不会从箱子里开出来，只能开采"
        + (f"（有 {missing} 种矿石暂时没有开采点数据，下面不全）" if missing else ""),
        "groups": rows,
        "more": more,
    }


def ship_mineral(name_en="", name_zh=""):
    """是不是船挖矿物（量子矿、石英、塔兰导电石…）：返回英文矿名，不是返回 None。
    船挖矿物至少 1/8 SCU，太大进不了战利品箱，掉落站列的开箱掉落实际开不出来（用户 2026-10-24）。
    矿名表经采矿那边的公开数据（mining.data.SIGNATURES）和中英对照（core.i18n）取"""
    try:
        from ...mining.data import SIGNATURES
        from ...core.i18n import mineral_en
        from ...trade.names import raw_base
    except Exception:
        return None
    # 原矿名先去掉原矿那截：Taranite (Raw)、Raw Ouratite（原欧拉特烃）照样给开采点（原矿和精炼分开认以后，2026-11-08）
    base = re.sub(r"\s*\(.*?\)", "", raw_base(name_en) or name_en or "").strip().lower()
    names = {k.lower(): k for k in SIGNATURES}
    names["pressurized ice"] = "Pressurized Ice"
    if base in names:
        return names[base]
    if name_zh and not name_en:
        m = mineral_en(name_zh, fuzzy=False, ship_only=True)
        return m if m in SIGNATURES else None
    return None


def ship_info(mineral, top=5):
    """船挖矿物的挖矿地点（SCMiner 的船挖地点数据，经 mining.locations 取）：格式同 info，多 mine=True、note、src"""
    from ...core.i18n import mineral_zh
    from ...mining.locations import where, zh_name

    pairs = [(pct, zh_name(loc)) for pct, loc in where(mineral)]
    rows, more = ship_groups(pairs, top)
    zh = {"Pressurized Ice": "高压冰"}.get(mineral) or mineral_zh(mineral)
    return {
        "name": zh,
        "en": mineral,
        "mine": True,
        "src": "SCMiner 船挖地点",
        "note": "船挖矿物：太大进不了战利品箱，只能用船开采"
        + ("" if rows else "（暂无地点数据）"),
        "groups": rows,
        "more": more,
    }


def info(name_en="", name_zh="", top=5):
    """掉落（窗口用）：{name, groups: [{p, box, regions}], more} 或 None；取不到数据时 {error}
    （明细本机没有：「这件物品暂时没有掉落明细」）。只查本机，不联网。
    副本专属矿（科力晶、加纳石、杰金、烁迪银）返回开采点：多一个 mine=True、note"""
    key = instance_ore(name_en, name_zh)
    if key:
        return mine_info(key, top)
    ship = ship_mineral(name_en, name_zh)
    if ship:
        return ship_info(ship, top)
    hits = find(name_en, name_zh)
    if not hits:
        return None
    u, en, zh, rar = hits[0]
    try:
        d = detail(u)
    except NoDetail as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"掉落数据暂时取不到（{e}）"}
    grouped = group_info(d, top)  # 概率和箱子一样的地点合成一行
    if grouped is None:
        return None
    rows, more = grouped
    return {
        "name": zh or en,
        "en": en,
        "uuid": u,
        "groups": rows,
        "more": more,
    }
