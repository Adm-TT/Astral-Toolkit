"""交易的旧总入口 Trade（库存库 + 物品目录 + 行情查询），和几样还被别处用的小工具：钱和品质档的显示、说明框名字比较、维科洛材料去哪弄。

命令行版（python -m astral_toolkit.run trade 那套查价 / 入库 / 截图 / 悬停菜单）2026-11-06 删了（F 段 B3）；
不是库存的东西 F 段 B1 / B2 搬走，库存那半边等新库存。
"""

import os
import time
from datetime import datetime, timezone
from pathlib import Path
import re as _re

from .catalog import Catalog
from .history import History
from .inspector import (
    _ANCHOR,  # noqa: F401
    _VOLUME,  # noqa: F401
    _is_anchor,  # noqa: F401
    _SENTENCE,  # noqa: F401
    _LETTERS,  # noqa: F401
    _STAT,  # noqa: F401
    _NOT_ITEM,  # noqa: F401
    _ink,  # noqa: F401
    _bright_only,  # noqa: F401
    tooltip_name,  # noqa: F401
    plausible_name,  # noqa: F401
    tooltip_pick,  # noqa: F401
    _anchor_name,  # noqa: F401
    # 下面两个是再导出：F8（tasks/hover）、盘点（app/engines/count）经 console 拿，F 段 B1 改成直接从 inspector 拿时删
    _cursor_on_image as _cursor_on_image,
    _hover_log as _hover_log,
)
from .inventory import Inventory
from .market_service import MarketService
from ..contracts.textkeys import fold_en as _fold_en
from .names import has_chinese, to_english
from .providers.scm import ScmProvider
from .providers.uex import UexProvider
from .storage import Database


def _fold(text):
    """比较名字用：忽略大小写、空格、符号；OCR 常把 II 认成 ll，统一成 i。
    contracts.textkeys.fold_en 不动（那边查表要分清 l 和 i），只在这里比较 OCR 认出的名字时放宽"""
    return _fold_en(text).replace("l", "i")


VK = {f"F{i}": 0x6F + i for i in range(1, 13)}
SOURCE_ZH = {"uex": "UEX", "scm": "SCM"}
STATE_ZH = {
    "ok": "",
    "empty": "暂无报价",
    "partial": "部分数据",
    "stale": "旧缓存",
    "offline": "离线",
    "forbidden": "拒绝访问",
    "rate_limited": "限流",
    "schema_error": "格式变化",
    "cancelled": "已取消",
}


def data_directory():
    """和原 SC Trade Companion 同一个数据库位置，原来录入的库存直接能用。
    安装版按程序位置推（current → AT → Local），和 userdata 一样不读 LOCALAPPDATA：用另一个管理员账号提权时
    那个变量是别人的目录，库存会"丢"（审查 2026-10-31）。正常情况下推出来的就是同一个文件夹，不用搬。
    源码版照旧读 LOCALAPPDATA（测试和巡检靠改它把库存指到临时目录）"""
    from ..core import paths

    if paths.VELOPACK:
        return paths.USER.parent / "SCTradeCompanion"
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share")))
    return base / "SCTradeCompanion"


DB_NAME = "dubhe_inventory.db"


class Trade:
    def __init__(self, directory=None, providers=None):
        d = Path(directory or data_directory())
        d.mkdir(parents=True, exist_ok=True)
        # 1.6.58：天枢自己的库存文件（表结构重新设计）。旧的 inventory.db 不动，第一次启动时只读地导一份过来
        self.db = Database(d / DB_NAME)
        if not self.db.get("v1_imported"):
            try:
                from .storage import import_v1

                n = import_v1(d / "inventory.db", self.db)
                self.db.set("v1_imported", {"at": time.strftime("%F %T"), "rows": n})
            except Exception as e:  # 导不成功也照常用（从空库开始），下次启动再试
                print(f"旧库存导入没成功：{e}")
        self.catalog = Catalog(self.db)
        self.inventory = Inventory(self.db)
        self.market = MarketService(
            self.db,
            providers if providers is not None else [UexProvider(), ScmProvider()],
        )
        self.history = History(self.db)
        # 1.6.37：矿和材料从 0.01 SCU 改成按 uSCU 记，旧记录换算一次（换算前备份数据库，2026-10-23 用户同意）
        try:
            self.inventory.migrate_cscu(
                backup=d / time.strftime("inventory_换算前备份_%Y%m%d_%H%M%S.db")
            )
        except Exception as e:  # 换算失败不影响用：旧的 cSCU 记录照样能读
            print(f"库存单位换算没成功：{e}")
        # 1.6.39：以前手打的位置能对上地点列表的（New Babbage、Area18…）改成列表里的叫法（真要改时先备份，记一笔移库能撤销）
        try:
            from ..crafting.stockplaces import match

            def canon(loc):
                p = match(loc)
                return p["label"] if p else None

            self.inventory.normalize_locations(
                canon,
                backup=d / time.strftime("inventory_地点归位前备份_%Y%m%d_%H%M%S.db"),
            )
        except Exception as e:  # 归位失败不影响用：对不上的位置在库存页「未归类」里
            print(f"库存地点归位没成功：{e}")
        # 1.6.55：物品对上游戏类名 + uuid（交易平台用；第一次填之前先备份数据库）
        try:
            self.catalog.fill_keys()
        except Exception as e:  # 对不上不影响用
            print(f"物品游戏编号没对上：{e}")

    # ---------------------------------------------------------------- 名字
    def label(self, item_id):
        """「中文名（英文名）」。中文名以汉化包为准：记下的中文名可能是 F8 认错的（冷冻舱（刻度）），
        先按汉化包纠正；对不上的才原样用（2026-10-23 用户反馈库存里显示认错的名字）"""
        from .names import canonical, zh_for

        item = self.catalog.get(item_id)
        if not item:
            return item_id
        with self.db.connection() as c:
            zh = [
                r[0]
                for r in c.execute(
                    "SELECT alias FROM aliases WHERE item_id=?", (item_id,)
                )
                if has_chinese(r[0])
            ]
        name = None
        for a in zh:
            hit = canonical(a, "")
            if hit and _similar(_fold(hit[1]), _fold(item.name)):
                name = hit[0]
                break
        name = name or zh_for(item.name) or (zh[0] if zh else None)
        return f"{name}（{item.name}）" if name else item.name

    # ---------------------------------------------------------------- 查价
    def lookup(self, query):
        return self.market.lookup(query)

    def prices(self, item, quality_group="q0", operation="sell", now=None):
        now = now or datetime.now(timezone.utc)
        return self.market.refresh(item, quality_group, operation, now)


def hud_market(results):
    """悬浮窗「市场」那一行：最低 / 最高 / 均价，没有的不写；所有来源都没数据返回 ""。
    最低价优先用来源给的；UEX 样本不全时不给最低价，就用能看到的挂牌里最低的（标「已知最低」）"""
    parts = []
    for r in results:
        src = SOURCE_ZH.get(r.source, r.source)
        for st in r.stats:
            prices = [q.price for q in (r.quotes or ()) if q.key == st.key]
            bits = []
            if st.minimum is not None:
                bits.append(f"最低 {_money(st.minimum)}")
            elif prices:
                bits.append(f"已知最低 {_money(min(prices))}")
            if prices and (st.minimum is None or max(prices) > st.minimum):
                bits.append(f"最高 {_money(max(prices))}")
            mean = st.mean if st.mean is not None else st.week_mean
            if mean is not None:
                bits.append(
                    f"{'均价' if st.mean is not None else '7天均价'} {_money(mean)}"
                )
            if bits:
                parts.append(f"{src} " + "｜".join(bits))
                break
    return "\n".join(parts)


def _money(v):
    if v is None:
        return "—"
    try:
        return f"{float(v):,.0f}"
    except (TypeError, ValueError):
        return str(v)


def _quality(text):
    """'650' → exact:650；'q6' → q6；空 → None"""
    t = (text or "").strip().lower()
    if not t:
        return None
    if t in ("未知", "unknown", "?"):
        return "unknown"
    if t.startswith("q") and t[1:].isdigit() and 0 <= int(t[1:]) <= 7:
        return t
    if t.isdigit() and 0 <= int(t) <= 1000:
        return "exact:" + str(int(t))
    raise ValueError("品质填 0–1000 的数值，或 q0–q7，或「未知」")


def _group(quality):
    from .providers.http import quality_group

    if quality and quality.startswith("exact:"):
        return quality_group(quality[6:])
    return quality if quality and quality.startswith("q") else "q0"


# ---------------------------------------------------------------- 哪里买 / 维科洛


def material_source(name_en):
    """维科洛材料去哪弄：商店能买就给最便宜的店；是矿就给最好的矿点"""
    from ..crafting import shops
    from ..crafting.wikelo import source_note

    note = source_note(name_en)
    if note:
        return note
    tip = shops.where_by_name(name_en)
    if tip:
        return tip
    try:
        from ..mining.locations import where as mine_where, zh_name

        base = _re.sub(r"\s*\(.*?\)", "", name_en).strip()
        rows = mine_where(base)
        if rows:
            pct, loc = rows[0]
            return f"挖矿：{zh_name(loc)} {pct:.0f}%" + (
                "（要精炼成纯净的）" if "Pure" in name_en else ""
            )
    except Exception:
        pass
    return loot_source(name_en)


def loot_source(name_en, name_zh=""):
    """开箱掉落一句话（scl.miao.network 的掉落表）：概率最高的箱子在哪些地方；没有掉落返回空"""
    try:
        from ..crafting.loot import info

        d = info(
            name_en, name_zh, top=2, online=False
        )  # 本机没有明细就算没有，不在页面里逐个材料联网等（细查 2026-10-28）
    except Exception:
        return ""
    if not d or not d.get("groups"):
        return ""
    g = d["groups"][0]
    regions = "、".join(g["regions"][:3]) + (
        "等" if len(g["regions"]) > 3 or d.get("more") else ""
    )
    if d.get("mine"):  # 副本专属矿：不开箱，只能开采
        return (
            d["note"].split("：")[0]
            + f"，只能开采：{regions}"
            + (f"（{g['box']}）" if g["box"] else "")
        )
    if g.get("placed"):  # 不在箱子里，直接刷在场景里（争夺区奖励室架子上的舰船组件…）
        return f"场景里刷出：{regions}（最高约 {g['p']:.0%}）"
    box = g["box"].split(" · ")[0]
    box = "" if _re.fullmatch(r"\d+.*", box or "") else box
    return (
        f"开箱：{regions}"
        + (f"（{box} 箱" if box else "（")
        + f"，单箱最高约 {g['p']:.0%}）"
    )


def ore_item(item):
    """交易库里的这个物品是不是矿（矿按 SCU 记、存成 uSCU，和库存页、F6 同一行；别的按个）。
    和 F8 用同一个判断（inspector._is_mineral）；市场上的名字可能带「(Raw)」「（原矿）」这种后缀，先去掉"""
    import re
    from .inspector import _is_mineral

    n = re.sub(r"\s*[（(][^（）()]*[)）]\s*$", "", item.name or "").strip()
    return _is_mineral(n if has_chinese(n) else "", n)


# ---------------------------------------------------------------- 说明框里的名字对上物品（F8、物品查询用）


def _similar(a, b):
    import difflib

    if not a or not b:
        return False
    return (
        a.startswith(b[:6])
        or b.startswith(a[:6])
        or difflib.SequenceMatcher(None, a, b).ratio() >= 0.6
    )


def match_tooltip(t, zh, en, online=True):
    """说明框里的名字 → 物品。顺序：中文名查汉化包对照表 → 英文名（容忍 OCR 丢空格、II/ll、截断）。
    先查本机目录（以前查到过的物品、记下的中文名），查到就不联网；本机没有才去 UEX/SCM 搜（每次搜要零点几秒到几秒）。
    返回 (物品或 None, 候选列表)"""
    if zh and hasattr(t.catalog, "by_alias"):
        hit = t.catalog.by_alias(zh)
        if hit:
            return hit, [hit]
    want = []
    if zh:
        want += to_english(zh)[:1] if len(to_english(zh)) == 1 else []
    if en:
        want.append(en)
    best, local = _match_names(t.catalog.search, want)
    if best is not None or not online:
        return best, local
    best, remote = _match_names(lambda q: t.lookup(q)[0], want)
    merged = {i.id: i for i in local + remote}
    return best, list(merged.values())


def _match_names(search, want):
    import difflib

    candidates = {}
    for name in want:
        target = _fold(name)
        # OCR 常把空格丢掉（CQ7Rifle），补回空格再搜
        spaced = _re.sub(
            r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Za-z])(?=")|(?<=")(?=[A-Za-z])', " ", name
        )
        words = _re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}", spaced)
        for q in dict.fromkeys([name, spaced] + words[:1]):
            items = search(q)
            # 搜不到时有的来源会返回一大串不相干的物品，只留名字像的
            items = [i for i in items if _similar(_fold(i.name), target)]
            for i in items:
                candidates.setdefault(i.id, i)
            if items:
                break
        scored = []
        for i in candidates.values():
            f = _fold(i.name)
            score = (
                1.0
                if f == target
                else 0.95
                if f.startswith(target) and len(target) >= 8
                else difflib.SequenceMatcher(None, f, target).ratio()
            )
            scored.append((score, not i.id.startswith("scm:"), i))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        if scored and scored[0][0] >= 0.85:
            return scored[0][2], [x[2] for x in scored]
    return None, list(candidates.values())
