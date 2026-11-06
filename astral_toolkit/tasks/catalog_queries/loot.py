"""掉落查询（目录迁移 Q3 从 crafting/loot.py 拆来）：这件东西在哪些地方的箱子里会开出来，副本专属矿去哪开采，
船挖矿物去哪挖。数据来自 scl.miao.network（从游戏文件解析的掉落表）；概率是该站算出的「单个箱子开出这件东西的最高概率」，只作参考。

- 找物品只查游戏数据库：物品索引由「更新数据」写 loot_index.json、导进库（update/loot.py），掉落索引缺了也不在这里下
  （副本专属矿缺索引、联网时例外：先结束旧快照、下载重建，再开新快照读）
- 单件掉落明细：先查随数据包发布的整包，再查本机缓存（infrastructure/persistence/loot_details.py），都没有才联网现取
  （infrastructure/providers/loot_site.py）；online=False 时不联网，抛 Pending 让调用方后台再取
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
from ...infrastructure.providers import loot_site


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
    数据来自游戏数据库（掉落索引缺了也不在 F8 / 物品页里联网下，更新数据会下）；库不可用时返回空"""
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


_failed = {}  # 下载失败的物品 → 时间：10 分钟内不再重试（断网时每次都要等超时）


class Pending(Exception):
    """掉落明细本机没有，要上网取（online=False 时抛出，调用方后台再取）"""


_UUID_RE = re.compile(r"[0-9A-Za-z\-]{1,64}")
_VER_RE = re.compile(r"\w[\w.\-]{0,63}")


def detail(uuid, online=True):
    """单件物品的掉落明细：整包 → 本机缓存 → 联网现取（写进缓存）。online=False 本机没有就抛 Pending；
    同一件联网失败后 10 分钟内不再试（抛 OSError），断网时别每次都等超时"""
    version = (_index_meta() or {}).get("version", "4.10.2LIVE")
    # 要拼进缓存路径和网址：只认字母数字、点、横线，别让 ..\ 之类跑到缓存目录外面
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
    if not online:
        raise Pending()
    import time as _t

    if _t.time() - _failed.get(uuid, 0) < 600:
        raise OSError("网络不通，稍后再试")
    try:
        d = loot_site.item_detail(version, uuid)
    except Exception:
        _failed[uuid] = _t.time()
        raise
    loot_details.write_cached(version, uuid, d)
    return d


def mine_info(key, top=5, online=True):
    """副本专属矿的开采点：{name, mine: True, note, groups: [{p, box, regions}], more}"""
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
            if not online:
                return None
            from ...update import loot as loot_index

            loot_index.load_index(
                True
            )  # 联网下一份（在快照外）：update() 在更新边界里，写完重建库
            with (
                gamedata.snapshot() as s
            ):  # 重建后的新版本；若外面还钉着旧快照就还是旧的，下次再查
                if gd_loot.index_meta(s) is None:
                    return None
                rocks = gd_loot.by_cls_prefix(want, s)
    except (
        gamedata.GamedataError
    ):  # 库不可用：不在查询路径里读 JSON / 联网（收口 2，待做 ⑮）
        return None
    rocks = [r for r in rocks if not (skip and r.cls_lower.startswith(skip))]
    best = {}  # 地区 → (概率, 位置说明)
    for r in rocks:
        try:
            d = detail(r.uuid, online)
        except Pending:
            return {"pending": True}
        except Exception as e:
            return {"error": f"开采点数据暂时取不到（{e}）"}
        for region, p, where in summary(d, top=99):
            loc = where.split("｜")[0] if where else ""
            if region not in best or p > best[region][0]:
                best[region] = (p, loc)
    rows, more = mine_groups(best, top)
    from ...core.i18n import mineral_zh

    en = "Carinite (Pure)" if key == "carinitepure" else key.capitalize()
    zh = mineral_zh(en) if key != "carinitepure" else "科力晶（纯）"
    return {
        "name": zh,
        "en": en,
        "mine": True,
        "src": "scl.miao.network 开采点出现概率",
        "note": "副本专属矿：不会从箱子里开出来，只能开采",
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
    except Exception:
        return None
    base = re.sub(r"\s*\(.*?\)", "", name_en or "").strip().lower()
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


def info(name_en="", name_zh="", top=5, online=True):
    """掉落（窗口用）：{name, groups: [{p, box, regions}], more} 或 None；取不到数据时 {error}。
    副本专属矿（科力晶、加纳石、杰金、烁迪银）返回开采点：多一个 mine=True、note。
    online=False：明细本机没有就返回 {pending: True}，不上网等（2026-10-28 用户反馈物品查询卡 10 秒）"""
    key = instance_ore(name_en, name_zh)
    if key:
        return mine_info(key, top, online)
    ship = ship_mineral(name_en, name_zh)
    if ship:
        return ship_info(ship, top)
    hits = find(name_en, name_zh)
    if not hits:
        return None
    u, en, zh, rar = hits[0]
    try:
        d = detail(u, online)
    except Pending:
        return {"pending": True}
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
