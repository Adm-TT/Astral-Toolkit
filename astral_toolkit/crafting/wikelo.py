"""维科洛（Wikelo）兑换：每个兑换要交哪些材料、换来什么；某样东西能拿去换什么

数据来自 scmdb 的任务数据（和制造蓝图同一份 merged-*.json），中文名来自用户的汉化包。
菜单 5 更新制造数据时会一起重建 wikelo.json。
"""

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
from ..contracts.textkeys import fold_mixed_loose as _fold  # noqa: E402
from ..core.paths import DATA  # noqa: E402
from . import wikelo_rules as _rules  # noqa: E402

OUT = DATA / "wikelo.json"
TYPE_ZH = {
    "Wikelo - Vehicles": "载具",
    "Wikelo - Other Items": "装备/物品",
    "Collection": "收集",
}
# 旧名字：只留给还冻着的调用方（test_runtime_arch 管着）
# trade/console：F 段拆 Trade 总入口、它改走 tasks/wikelo + 排版时删
describe = _rules.describe


def make_data(merged_path, names_path):
    """merged-*.json + 汉化名 → wikelo.json 的内容（只算不写，不拿锁）"""
    from .build_crafting import _load_names, _item_names

    merged = json.loads(Path(merged_path).read_text(encoding="utf-8"))
    ini, items = _load_names(names_path)
    en2zh = _item_names(items)
    pools = merged.get("resourcePools") or {}

    def text(key):
        v = ini.get((key or "").lstrip("@").lower(), "")
        return re.sub(r"<[^>]+>", "", v)

    # 汉化包里所有「中文 + 英文名」格式的文本都拿来对照（任务道具不在物品表里，比如 ASD 安全驱动器、维科洛人情）
    any_en = {}
    for v in ini.values():
        v = re.sub(r"<[^>]+>", "", v)
        m = re.fullmatch(
            r"(.*?[\u4e00-\u9fff][^\\]*?)\s*(?:\\n)?([A-Za-z][\x20-\x7e]*)", v.strip()
        )
        if m and len(m.group(2)) > 2:
            any_en.setdefault(m.group(2).strip().lower(), m.group(1).strip())

    def zh_of(name, key=None):
        if _rules.note_for(name):
            return _rules.note_for(name)[0]
        z = text(key) if key else ""
        if z:  # 「幽影 臂甲 ASD 版\nGeist Armor Arms ASD Edition」→ 只留中文名（2026-10-28 改用和蓝图一样的 _strip_en，不在第一个英文字母处截断）
            from .build_crafting import _strip_en

            first, _, rest = z.partition("\\n")
            return (_strip_en(first.strip(), rest.strip(), name) or first).strip()
        return (
            en2zh.get(name.lower())
            or en2zh.get(name.lower().replace("-", ""))
            or any_en.get(name.lower(), "")
        )

    out_rows = []
    for c in merged.get("contracts") or []:
        if (
            "wikelo" not in (c.get("contractorName") or "").lower()
        ):  # scmdb 写 Wikelo，游戏数据写 Wikelo Emporium（2026-10-28）
            continue
        req = []
        for h in c.get("haulingOrders") or []:
            pool = pools.get(h.get("resource"), {})
            name = pool.get("name") or h.get("resource")
            if "minSCU" in h:
                qty, unit = h.get("minSCU") or 0, "SCU"
            else:
                qty, unit = max(h.get("minAmount") or 0, h.get("maxAmount") or 0), "个"
            req.append(
                {"n": name, "z": zh_of(name, pool.get("nameKey")), "q": qty, "u": unit}
            )
        rewards = []
        for r in c.get("itemRewards") or []:
            if r.get("name"):
                rewards.append(r["name"])
            for g in r.get("groups") or []:
                rewards += [i["name"] for i in g.get("items") or [] if i.get("name")]
        title_raw = text(c.get("titleLocKey") or c.get("titleKey"))
        title_zh, _, bracket = title_raw.partition("\\n")
        reward_zh = re.sub(r"^\[兑换\s*-\s*|\]$", "", bracket.strip())
        out_rows.append(
            {
                "id": c.get("debugName") or c.get("id"),
                "type": TYPE_ZH.get(c.get("missionType"), c.get("missionType")),
                "t": title_zh.strip() or c.get("title", ""),
                "te": c.get("title", ""),
                "rz": reward_zh,
                "rewards": rewards,
                "req": req,
                "systems": c.get("availableSystems") or c.get("systems") or [],
            }
        )
    out_rows.sort(key=lambda r: (r["type"], r["te"]))
    return {"version": merged.get("version"), "contracts": out_rows}


def build(merged_path, names_path, out=OUT):
    """merged-*.json + 汉化名 → wikelo.json（算好再在更新边界里写）；返回兑换个数"""
    data = make_data(merged_path, names_path)
    _write(out, data)
    return len(data["contracts"])


def _write(out, data):
    """写 wikelo.json（游戏数据库的源）：write_json 临时文件再换名（换名撞上占用会重试）；
    在更新边界里写（updating 在外、BUILD_LOCK 在内），出口重建一次库"""
    from .. import gamedata
    from ..core.paths import write_json
    from .build_crafting import BUILD_LOCK

    with gamedata.updating(), BUILD_LOCK:
        write_json(out, data, separators=(",", ":"))


def load():
    """全部兑换（wikelo.json 的 contracts 同形，按源顺序；材料中文名已去掉末尾的反斜杠）。同一内容版本内是同一个列表；
    库不可用当成没有兑换"""
    from .. import gamedata

    try:
        return gamedata.wikelo.contracts()
    except gamedata.GamedataError:
        return []


def _full_name(name_en, name_zh):
    """汉化包 / 矿物表里精确对得上的全名（F8 认准了的、物品查询页点开的），不是 OCR 截断的半截名字"""
    from ..trade.names import canonical_exact

    try:
        return canonical_exact(name_zh or "", name_en or "") is not None
    except Exception:
        return False


def uses(name_en="", name_zh=""):
    """这样东西（英文名/中文名）在哪些兑换里要用：[(兑换, 需要的数量, 单位)]"""
    from .. import gamedata

    fe, fz = _fold(name_en), _fold(name_zh)
    try:  # 先按折叠名相等：库里按比较键筛（norm_n / norm_z），再照原条件核一遍（中文名去掉反斜杠后为空的不算）
        pairs = gamedata.wikelo.requiring(
            fe if name_en else None, fz if name_zh else None
        )
    except gamedata.GamedataError:
        return []
    return _rules.uses(
        name_en, name_zh, pairs, load, lambda: _full_name(name_en, name_zh)
    )


def search(text):
    """按兑换名/奖励名/材料名搜兑换"""
    return _rules.search(load, text)


def print_spots(name):
    """打印机打印的物品在哪打（print_spots.json，由数据构建脚本从游戏数据生成，2026-10-27；读库）→ [地点]，不分大小写"""
    from .. import gamedata

    try:
        return gamedata.wikelo.print_places((name or "").strip().lower())
    except gamedata.GamedataError:
        return []


def source_note(name):
    return _rules.source_note(name, print_spots)


def uses_text(name_en, name_zh=""):
    return _rules.uses_text(uses(name_en, name_zh))
