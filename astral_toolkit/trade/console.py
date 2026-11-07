"""交易的旧总入口里库存那半边：Trade（库存库 + 物品目录 + 行情查询）、data_directory、ore_item、_quality，
和给冻结调用方（库存、盘点、目标）留的几个旧名字。

命令行版 2026-11-06 删了（F 段 B3）；行情显示搬到 trade/market_text，名字比较搬到 trade/matching，
维科洛材料来源搬到 crafting/acquire（F 段 B1；目录迁移 Q3b 起在 tasks/catalog_queries/acquire）；库存这半边等新库存。
"""

import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .catalog import Catalog
from .history import History
from .inventory import Inventory
from .market_service import MarketService
from .matching import _fold, _similar
from .names import has_chinese
from .providers.scm import ScmProvider
from .providers.uex import UexProvider
from .storage import Database

# 旧名字：只留给还冻着的调用方，别处一律从新家拿（test_runtime_arch 管着）
from .market_text import (
    SOURCE_ZH as SOURCE_ZH,
)  # 目标（tasks/goals）：目标链改从 trade.market_text 拿时删


def material_source(name_en):
    """目标（crafting/goals）用的旧名字：目标改用新实现时删。目录迁移 Q3b 起转给 tasks/catalog_queries/acquire——
    trade 往上调 tasks 只许这一处（老大 11-07 定：留着转发、钉住这一条；门禁 test_trade_reaches_up_into_tasks_only_where_listed）"""
    from ..tasks.catalog_queries.acquire import material_source as f

    return f(name_en)


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


def ore_item(item):
    """交易库里的这个物品是不是矿（矿按 SCU 记、存成 uSCU，和库存页、F6 同一行；别的按个）。
    和 F8 用同一个判断（inspector._is_mineral）；市场上的名字可能带「(Raw)」「（原矿）」这种后缀，先去掉"""
    import re
    from .inspector import _is_mineral

    n = re.sub(r"\s*[（(][^（）()]*[)）]\s*$", "", item.name or "").strip()
    return _is_mineral(n if has_chinese(n) else "", n)
