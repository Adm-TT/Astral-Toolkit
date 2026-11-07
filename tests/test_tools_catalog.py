"""物品在哪买、限定版同款、最近买点、掉落、维科洛、物品搜索和名字（从 test_tools.py 拆出，CL-C3）"""

import pytest
import time
from astral_toolkit.tasks.catalog_queries import shops
from astral_toolkit.update import shops as shop_prices
from astral_toolkit.crafting import wikelo
from astral_toolkit.tasks.catalog_queries import loot
from astral_toolkit.tasks.catalog_queries import acquire
from astral_toolkit.navigation import position
from astral_toolkit.gamedata._cache import VersionCache as _VC
from tests.tools_helpers import _shops_db


def fake_shops(monkeypatch, tmp_path):
    data = {
        "fmt": shop_prices.FMT,
        "fetched": time.time(),
        "items": {
            "1600": ["SureGrip S1 Tractor Beam", "Tractor Beams"],
            "1700": ["MaxLift Tractor Beam", "Tractor Beams"],
        },
        "rows": [
            [
                1600,
                "Refinery Shop - ARC-L4",
                "Stanton · ArcCorp · ARC-L4 Faint Glen Station",
                4600,
                0,
                "4.10",
            ],
            [
                1600,
                "Cousin Crow's - Orison",
                "Stanton · Crusader · Orison",
                4500,
                0,
                "4.10",
            ],
            [
                1700,
                "Shubin - Lorville",
                "Stanton · Hurston · Lorville",
                0,
                1200,
                "4.10",
            ],
        ],
    }
    _shops_db(monkeypatch, tmp_path, data)


POINTS = [
    dict(
        n="ArcCorp",
        i="Stanton3",
        sys="Stanton",
        t="Planet",
        x=18587664740,
        y=-22151916920,
        z=0,
    ),
    dict(
        n="ARC L4",
        i="Stanton3_L4",
        sys="Stanton",
        t="Lagrange Point",
        x=28478354915,
        y=5021502482,
        z=8076,
    ),
    dict(
        n="Crusader",
        i="Stanton2",
        sys="Stanton",
        t="Planet",
        x=-18962176000,
        y=-2664960000,
        z=0,
    ),
    dict(
        n="Microtech",
        i="Stanton4",
        sys="Stanton",
        t="Planet",
        x=22462085252,
        y=37185744964,
        z=0,
    ),
    dict(
        n="Pyro1", i="Pyro1", sys="Pyro", t="Planet", x=-7920920853, y=-2386976476, z=0
    ),
]


def setup(monkeypatch, tmp_path):
    data = {
        "fmt": shop_prices.FMT,
        "fetched": time.time(),
        "items": {
            "1700": ["MaxLift Tractor Beam", "Tractor Beams"],
            "1701": ["MaxLift Tractor Beam Battery", "Attachments"],
            "1800": ['MaxLift-II "Keelback" Tractor Beam', "Tractor Beams"],
        },
        "rows": [
            [
                1700,
                "Shop ARC-L4",
                "Stanton · ArcCorp · ARC-L4",
                18000,
                9000,
                "4.10",
                [
                    "Stanton",
                    "ArcCorp",
                    "ArcCorp Lagrange Point 4",
                    "",
                    "ARC-L4 Faint Glen Station",
                    "",
                ],
            ],
            [
                1700,
                "Shop Orison",
                "Stanton · Crusader · Orison",
                17000,
                0,
                "4.10",
                ["Stanton", "Crusader", "", "", "", "Orison"],
            ],
            [
                1700,
                "Shop NB",
                "Stanton · microTech · New Babbage",
                19000,
                0,
                "4.10",
                ["Stanton", "microTech", "", "", "", "New Babbage"],
            ],
            [
                1701,
                "Shop NB",
                "x",
                300,
                0,
                "4.10",
                ["Stanton", "microTech", "", "", "", ""],
            ],
        ],
    }
    _shops_db(
        monkeypatch,
        tmp_path,
        data,
        starmap={"bodies": {}, "pois": [], "points": POINTS},
    )
    return data


def test_finder_cheapest_first(monkeypatch, tmp_path):
    fake_shops(monkeypatch, tmp_path)
    assert shops.find("SureGrip S1")[0][0] == 1600
    buy, sell = shops.where(1600)
    assert buy[0][0] == 4500 and "Orison" in buy[0][2] and not sell
    buy, sell = shops.where(
        1700
    )  # 没有商店卖、商店收最高 1,200（原来比 where_text 的文字，Q2 删了 where_text）
    assert not buy and sell[0][0] == 1200
    assert "Orison" in shops.where_by_name("SureGrip S1 Tractor Beam")


def test_item_record_matches_shops_json_items(monkeypatch, tmp_path):
    """商店里这件的 [英文名, 类别]：和以前读 shops.json 的 items[str(编号)] 一样，字符串编号也认；
    没有的给 None（CL-C4 起 acquire.info 用它，替代 shops.load）"""
    fake_shops(monkeypatch, tmp_path)
    assert shops.item_record(1700) == ["MaxLift Tractor Beam", "Tractor Beams"]
    assert shops.item_record("1600") == ["SureGrip S1 Tractor Beam", "Tractor Beams"]
    assert shops.item_record(9999) is None and shops.item_record(None) is None


def test_wikelo_data_and_lookup():
    if not wikelo.OUT.exists():
        pytest.skip("没有维科洛数据")
    rows = wikelo.load()
    assert len(rows) > 50
    hits = wikelo.uses("Carinite (Pure)")
    assert hits and all(
        any(r["n"] == "Carinite (Pure)" for r in c["req"]) for c, _, _ in hits
    )
    assert wikelo.uses("", "纯净科力晶")
    asg = wikelo.search("Asgard")
    assert asg and "Wikelo Favor" in [r["n"] for r in asg[0]["req"]]
    from astral_toolkit.crafting import wikelo_rules

    text = wikelo_rules.describe(
        asg[0], lambda n: "可买：某店" if n == "ASD Secure Drive" else ""
    )
    assert "× 50 个" in text and "可买：某店" in text


def test_shop_point_and_nearest(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    arc = position.shop_point(
        ["Stanton", "ArcCorp", "ArcCorp Lagrange Point 4", "", "ARC-L4", ""]
    )
    crusader = position.shop_point(["Stanton", "Crusader", "", "", "", "Orison"])
    assert arc is not None and arc["n"] == "ARC L4"
    assert crusader is not None and crusader["n"] == "Crusader"
    here = dict(POINTS[3], label="NB", age=0)  # 在微科星
    near = shops.nearest(1700, here, 3)
    assert near[0][2] == "Shop NB" and near[0][0] == 0


def test_log_location(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    log = tmp_path / "Game.log"
    log.write_text(
        "<2026-10-20T05:00:00.000Z> [Notice] <RequestLocationInventory> Player[X] requested inventory for Location[RR_ARC_L4] [Team]\n"
        "<2026-10-20T05:10:00.000Z> [Notice] <Calculate Route> ...|Projected Start Location is 微科星 (microTech) for route to destination LOC_X\n",
        encoding="utf-8",
    )
    t, label, p = position.from_log(log)
    assert p["n"] == "ARC L4"  # 只认「打开库存」的地点，量子路线的出发点不算
    assert position.from_code("Stanton4_NewBabbage")["n"] == "Microtech"
    assert position.from_code("RR_ARC_L4")["n"] == "ARC L4"


def test_limited_variant_recommends_base(monkeypatch, tmp_path):
    """限定版买不到：推荐能买到的同款（不推配件），同款的买点按离你远近排；能买的照常给买点、卖价、掉落"""
    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(
        position, "current", lambda: dict(POINTS[2], label="在 十字军 开过库存", age=0)
    )
    monkeypatch.setattr(
        loot, "info", lambda en="", zh="", **kw: {"groups": ["测试掉落"]}
    )
    d = acquire.info('MaxLift-II "Keelback" Tractor Beam', "", 1800)
    assert not d["buyable"] and d["buy"] == []
    names = [v["name"] for v in d["variants"]]
    assert "MaxLift Tractor Beam" in names and not any("Battery" in n for n in names)
    v = d["variants"][names.index("MaxLift Tractor Beam")]
    shops_in = [r["shop"] for r in v["buy"]]
    assert v["total"] == 3
    assert shops_in.index("Shop Orison") < shops_in.index(
        "Shop NB"
    )  # 在十字军，奥里森最近
    assert d["loot"] == {"groups": ["测试掉落"]}
    d2 = acquire.info("MaxLift Tractor Beam", "", 1700)  # 能买 + 也有掉落：两个都给
    assert d2["buyable"] and d2["buy_total"] == 3 and d2["variants"] == []
    assert d2["loot"] == {"groups": ["测试掉落"]} and d2["sell"]["price"] == 9000


def test_buy_rows_nearest_first_when_position_known(monkeypatch, tmp_path):
    """买点：有位置、算得出距离就按远近给最近 3 处并写上距离（贵的离得近也排前面）；没有位置给最便宜 3 处、
    不写距离（目录迁移 Q3b 改坏检查补的：上面那条最近和最便宜碰巧同序，不按远近也看不出来）"""
    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(loot, "info", lambda en="", zh="", **kw: None)
    monkeypatch.setattr(
        position, "current", lambda: dict(POINTS[3], label="在 微科 开过库存", age=0)
    )
    d = acquire.info("MaxLift Tractor Beam", "", 1700)
    assert d["buy"][0]["shop"] == "Shop NB"  # 在微科：新巴贝奇最近，虽然最贵
    assert all(r["dist"] for r in d["buy"]), d["buy"]
    monkeypatch.setattr(position, "current", lambda: None)
    d = acquire.info("MaxLift Tractor Beam", "", 1700)
    assert [r["shop"] for r in d["buy"]] == ["Shop Orison", "Shop ARC-L4", "Shop NB"]
    assert [r["dist"] for r in d["buy"]] == ["", "", ""]


def test_resolve_order(monkeypatch):
    """名字找商店物品编号的先后（目录迁移 Q3b 改坏检查补的）：给了编号就用 → 英文名完全一样（不分大小写、符号）
    → 中文名 → 英文名最像的（OCR 认错一两个字母）→ 只有英文名时取英文名模糊找的第一个；都没有给 None"""
    found = {
        "MaxLift Tractor Beam": [
            (1701, "MaxLift Tractor Beam Battery"),
            (1700, "maxlift tractor-beam"),
        ],
        "牵引光束": [(1600, "SureGrip S1 Tractor Beam")],
        "MaxLift": [(1701, "MaxLift Tractor Beam Battery")],
    }
    monkeypatch.setattr(shops, "find", lambda q, limit=3: found.get(q, []))
    monkeypatch.setattr(
        shops, "find_close", lambda q: [1702] if q == "MaxLlft Tractor Beam" else []
    )
    assert acquire.resolve("MaxLift Tractor Beam", "牵引光束", 42) == 42
    assert acquire.resolve() is None
    assert (
        acquire.resolve("MaxLift Tractor Beam", "牵引光束") == 1700
    )  # 英文名完全一样排第一
    assert (
        acquire.resolve("MaxLlft Tractor Beam", "牵引光束") == 1600
    )  # 英文名对不上：中文名
    assert (
        acquire.resolve("MaxLlft Tractor Beam", "没有这个") == 1702
    )  # 中文名也找不到：英文名最像的
    assert acquire.resolve("MaxLift", "") == 1701  # 只有英文名、也不像：模糊找的第一个
    assert acquire.resolve("MaxLift", "没有这个") is None  # 有中文名时不退到模糊找


def test_info_wires_lookups_into_facts(monkeypatch, tmp_path):
    """info 只取数据、交给规则拼（IQ-C2）：名字和类别以商店数据为准、当前位置、不是精确点进来时按商店名字查描述、
    维科洛用途和掉落按传进来的英文名、中文名查、精确命中但掉落数据里没有这件时不查掉落、
    排在前面的同款候选是配件时照样推荐原型、商店数据里有这件时是不是配件按商店里的名字判断"""
    from astral_toolkit.tasks.catalog_queries import search as itemsearch

    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(
        position,
        "current",
        lambda: dict(POINTS[2], label="在 十字军 开过库存", age=130),
    )
    asked = []
    monkeypatch.setattr(
        loot,
        "info",
        lambda en="", zh="", **kw: asked.append((en, zh)) or {"groups": ["测试掉落"]},
    )
    entry = {
        "shop": 1700,
        "has_data": True,
        "loot": False,
        "desc": "说明",
        "aka": ("别名",),
    }
    monkeypatch.setattr(
        itemsearch,
        "lookup",
        lambda name: entry if name == "MaxLift Tractor Beam" else None,
    )
    used = []
    monkeypatch.setattr(
        wikelo,
        "uses",
        lambda en, zh="": (
            used.append((en, zh))
            or [({"t": "T1", "rz": "", "rewards": ["R1", "R2", "R3"]}, 2, "个")]
        ),
    )
    d = acquire.info("maxlift tractor beam", "牵引光束", 1700)
    assert (d["name"], d["category"]) == ("MaxLift Tractor Beam", "Tractor Beams")
    assert d["here"] == {"label": "在 十字军 开过库存", "minutes": 2}
    assert (d["desc"], d["aka"]) == ("说明", ["别名"])
    assert used == [("maxlift tractor beam", "牵引光束")]
    assert d["wikelo"] == [{"title": "T1", "q": 2, "u": "个", "reward": "R1、R2"}]
    assert d["loot"] == {"groups": ["测试掉落"]}
    assert asked == [("maxlift tractor beam", "牵引光束")]
    asked.clear()
    d2 = acquire.info("MaxLift Tractor Beam", "", exact=True)
    assert d2["id"] == 1700 and d2["loot"] is None and asked == []
    assert not d2["nowhere"] and d2["buyable"]
    monkeypatch.setattr(
        shops,
        "variants",
        lambda name, limit=0: [
            (1701, "MaxLift Tractor Beam Battery", "Attachments"),
            (1702, "MaxLift Tractor Beam Magazine", "Attachments"),
            (1703, "MaxLift Tractor Beam Cap", "Attachments"),
            (1700, "MaxLift Tractor Beam", "Tractor Beams"),
        ][:limit],
    )
    d3 = acquire.info('MaxLift-II "Keelback" Tractor Beam', "", 1800)
    # 排在前面的几件是配件：跳过它们，照样推荐原型（所以候选要多取几件）
    assert [v["id"] for v in d3["variants"]] == [1700]
    # 商店数据里有这件：传进来的名字带 Battery，但商店里这件不是电池，照样不推配件
    d4 = acquire.info("MaxLift Battery", "", 1800)
    assert [v["id"] for v in d4["variants"]] == [1700]


def test_info_nowhere_brings_blueprint(monkeypatch, tmp_path):
    """「哪都没有」（物品查询精确命中、商店和掉落数据里都没有、不随船自带、没有来源说明）才去查制造蓝图，
    蓝图的 key 和显示名不对调；随船自带、有来源说明就不算「哪都没有」、也不查蓝图；商店里没有这件时名字先用英文名（IQ-C2）"""
    from astral_toolkit.crafting import crafting as C
    from astral_toolkit.tasks.catalog_queries import search as itemsearch

    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(position, "current", lambda: None)
    monkeypatch.setattr(
        itemsearch,
        "lookup",
        lambda name: {
            "shop": None,
            "has_data": False,
            "loot": False,
            "desc": "",
            "aka": [],
        },
    )
    ships = []
    monkeypatch.setattr(acquire, "ships_with", lambda name: ships)
    monkeypatch.setattr(wikelo, "source_note", lambda name: "")
    asked = []
    bp = {"d": 0, "src": [("任务A", 1), ("任务B", 2)], "nsrc": 2}
    monkeypatch.setattr(
        C, "for_item", lambda en="", zh="": asked.append((en, zh)) or bp
    )
    monkeypatch.setattr(C, "bp_key", lambda b: "key-1")
    monkeypatch.setattr(C, "display_name", lambda b: "蓝图名")
    d = acquire.info("Rare Thing", "稀有物", exact=True)
    assert (
        d["name"] == "Rare Thing"
        and d["nowhere"] is True
        and asked == [("Rare Thing", "稀有物")]
    )
    assert d["craft"] == {
        "key": "key-1",
        "name": "蓝图名",
        "unlocked": False,
        "missions": ["任务A", "任务B"],
        "nsrc": 2,
    }
    ships.append("Aurora")  # 随船自带：不算「哪都没有」，也不去查蓝图
    asked.clear()
    d2 = acquire.info("Rare Thing", "稀有物", exact=True)
    assert d2["nowhere"] is False and d2["craft"] is None and asked == []
    assert d2["ships"] == ["Aurora"]
    ships.clear()  # 不随船，但有来源说明（维科洛兑换）：也不算「哪都没有」
    monkeypatch.setattr(wikelo, "source_note", lambda name: "维科洛兑换")
    d3 = acquire.info("Rare Thing", "稀有物", exact=True)
    assert d3["nowhere"] is False and d3["craft"] is None and asked == []
    assert d3["how"] == "维科洛兑换"


def test_loot_summary():
    d = {
        "regions": [
            {
                "id": "asddelving",
                "name": "ASD",
                "best": 0.0106,
                "containers": [{"name": "Lootable_Container_Large", "openp": 0.0106}],
            },
            {
                "id": "caves",
                "name": "洞穴",
                "best": 0.0000067,
                "containers": [
                    {
                        "name": "Lootable_Generated_Container_06_dirty",
                        "loc": "阿伯丁洞穴·中等",
                        "openp": 6.7e-6,
                    }
                ],
            },
        ]
    }
    rows = loot.summary(d)
    assert rows[0][0] == "ASD" and "Large" in rows[0][2] and "阿伯丁洞穴" in rows[1][2]


def test_nearest_distinct_places_and_loot_grouping(monkeypatch, tmp_path):
    data = setup(monkeypatch, tmp_path)
    data["rows"].append(
        [
            1700,
            "Shop NB 2",
            "Stanton · microTech · New Babbage",
            18500,
            0,
            "4.10",
            ["Stanton", "microTech", "", "", "", "New Babbage"],
        ]
    )
    _shops_db(monkeypatch, tmp_path, data)  # 加了一行：重建临时库
    near = shops.nearest(1700, dict(POINTS[3], label="", age=0), 3)
    assert (
        len({r[3] for r in near}) == 3 and near[0][2] == "Shop NB 2"
    )  # 同一地点只留最便宜的
    d = {
        "regions": [
            {
                "name": n,
                "best": 0.0106,
                "containers": [{"name": "Lootable_Container_Large", "openp": 0.0106}],
            }
            for n in ("ASD", "QV", "Hathor")
        ]
        + [{"name": "SoO", "best": 0.1364, "containers": []}]
    }
    monkeypatch.setattr(loot, "find", lambda en, zh: [("u", "X", "某物", 1)])
    monkeypatch.setattr(loot, "detail", lambda u, online=True: d)
    got = loot.info("X")
    groups = got["groups"] if got else None
    assert isinstance(groups, list)
    # 概率和箱子一样的三个地点合成一行；都是箱子里开的，不是刷在场景里
    rows = sorted(
        (round(g["p"], 4), g["box"] or "", g["placed"], tuple(g["regions"]))
        for g in groups
    )
    assert rows == [
        (0.0106, "Large", False, ("ASD", "QV", "Hathor")),
        (0.1364, "", False, ("SoO",)),
    ], rows


def test_log_location_found_far_back_and_updates(monkeypatch, tmp_path):
    """「打开库存」在很早以前（几十 MB 之前）也能找到；之后日志新增了新的「打开库存」就换成新的"""
    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(position, "CHUNK", 1000)  # 用小块模拟大文件
    monkeypatch.setattr(position, "_save_ids", lambda: None)
    position._log_cache.clear()
    log = tmp_path / "Game.log"
    inv = "<2026-10-20T05:00:00.000Z> [Notice] <RequestLocationInventory> Player[X] requested inventory for Location[{}] [Team]\n"
    log.write_text(
        inv.format("RR_ARC_L4")
        + "<2026-10-20T05:01:00.000Z> noise line padding padding\n" * 500,
        encoding="utf-8",
    )
    assert position.from_log(log)[2]["n"] == "ARC L4"
    with open(log, "a", encoding="utf-8") as f:
        f.write(inv.format("Stanton4_NewBabbage"))
    assert position.from_log(log)[2]["n"] == "Microtech"


def test_log_location_learns_ids_and_follows_moves(monkeypatch, tmp_path):
    """开个人库存学到「编号 ↔ 地点」；之后开本地库存/走动时日志只给编号，认识的编号也能更新位置；
    不认识的编号（比如进了飞船）保持原地点；半行写入不会丢"""
    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(position, "_save_ids", lambda: None)
    position._log_cache.clear()
    position._log_cache["ids"] = {}
    log = tmp_path / "Game.log"
    L = lambda t, body: (  # noqa: E731
        f"<2026-10-20T05:{t}.000Z> [Notice] {body} [Team_CoreGameplayFeatures][Inventory]\n"
    )  # noqa: E731
    log.write_text(
        L(
            "00:00",
            "<RequestLocationInventory> Player[X] requested inventory for Location[Stanton4_NewBabbage]",
        )
        + L("00:01", "<Query Inventory> Request[1] Inventory[7:Location:111] ")
        + L(
            "01:00",
            "<RequestLocationInventory> Player[X] requested inventory for Location[RR_ARC_L4]",
        )
        + L("01:01", "<Query Inventory> Request[2] Inventory[7:Location:222]"),
        encoding="utf-8",
    )
    assert position.from_log(log)[2]["n"] == "ARC L4"
    assert position._ids() == {"111": "Stanton4_NewBabbage", "222": "RR_ARC_L4"}
    with open(log, "a", encoding="utf-8") as f:  # 进飞船：不认识的编号，保持原地点
        f.write(
            L(
                "02:00",
                "<Update Inventory Location> Player [X] is changing location. Landing [222] -> [222]. Location [222] -> [999]. Pending [0]",
            )
        )
    assert position.from_log(log)[2]["n"] == "ARC L4"
    line = L(
        "03:00",
        "<Update Inventory Location> Player [X] is changing location. Landing [0] -> [111]. Location [0] -> [111]. Pending [0]",
    )
    with open(log, "a", encoding="utf-8") as f:  # 游戏只写了半行
        f.write(line[:40])
    position.from_log(log)
    with open(log, "a", encoding="utf-8") as f:
        f.write(line[40:])
    assert position.from_log(log)[2]["n"] == "Microtech"  # 回到认识的地点：更新


def test_wikelo_detail_sticky_and_names_clean():
    """维科洛兑换：右边详情跟着页面滚动；汉化名末尾的反斜杠去掉"""
    from astral_toolkit.core import paths

    css = (paths.CODE / "app" / "web" / "style.css").read_text(encoding="utf-8")
    js = (paths.CODE / "app" / "web" / "app.js").read_text(encoding="utf-8")
    assert (
        ".split > .sticky { position: sticky" in css
        and 'id="wout" class="sticky"' in js
    )
    from astral_toolkit.crafting import wikelo

    for c in wikelo.load():
        for r in c["req"]:
            assert not r["z"].endswith("\\"), r


def test_wikelo_materials_all_have_source(monkeypatch):
    """每样维科洛材料都要有「去哪弄」：商店 / 挖矿 / 特殊说明 / 开箱掉落（用户 2026-10-23：不知道就查，补齐为止）"""
    import pytest
    from astral_toolkit.crafting import wikelo
    from astral_toolkit.update import loot as loot_index
    from astral_toolkit.tasks.catalog_queries.acquire import material_source

    cs = wikelo.load()
    if not cs or not loot_index.load_index(False):
        pytest.skip("没有维科洛 / 掉落数据")
    names = {r["n"] for c in cs for r in c["req"]}
    missing = [n for n in sorted(names) if not material_source(n)]
    assert not missing, missing


def test_material_source_order_and_sentence(monkeypatch):
    """维科洛材料去哪弄那一句（目录迁移 Q3b 改坏检查补的）：维科洛说明 → 商店最便宜的 → 挖矿最好的矿点（纯净的要精炼）
    → 开箱掉落（只看本机，不联网）；开箱那句写最常见的箱子、超过 3 个地方写「等」，副本专属矿说只能开采，刷在场景里的不说箱子"""
    from astral_toolkit.mining import locations

    monkeypatch.setattr(
        wikelo, "source_note", lambda n: "维科洛说明" if n == "Wikelo Favor" else ""
    )
    monkeypatch.setattr(
        shops,
        "where_by_name",
        lambda n: "可买：某店" if n in ("Wikelo Favor", "ASD Secure Drive") else "",
    )
    monkeypatch.setattr(
        locations,
        "where",
        lambda base: [(42.4, "LocA"), (10.0, "LocB")] if base == "Carinite" else [],
    )
    monkeypatch.setattr(
        locations, "zh_name", lambda loc: {"LocA": "甲地"}.get(loc, loc)
    )
    box = {"p": 0.25, "box": "Box A · 1", "regions": ["区一", "区二"], "placed": False}
    many = {
        "p": 0.5,
        "box": "Crate",
        "regions": ["一", "二", "三", "四"],
        "placed": False,
    }
    shelf = {"p": 0.3, "box": "x", "regions": ["奖励室"], "placed": True}
    ore = {"p": 1.0, "box": "洞里", "regions": ["副本"], "placed": False}
    found = {
        "Pearl": {"groups": [box]},
        "Many": {"groups": [many]},
        "Shelf": {"groups": [shelf]},
        "Ore": {"mine": True, "note": "副本专属矿：要开采", "groups": [ore]},
    }
    online = []

    def fake_info(en="", zh="", **kw):
        online.append(kw.get("online"))
        return found.get(en)

    monkeypatch.setattr(loot, "info", fake_info)
    assert acquire.material_source("Wikelo Favor") == "维科洛说明"  # 商店也有，说明在先
    assert acquire.material_source("ASD Secure Drive") == "可买：某店"
    assert acquire.material_source("Carinite") == "挖矿：甲地 42%"
    assert (
        acquire.material_source("Carinite (Pure)") == "挖矿：甲地 42%（要精炼成纯净的）"
    )
    assert (
        acquire.material_source("Pearl")
        == "开箱：区一、区二（Box A 箱，单箱最高约 25%）"
    )
    assert (
        acquire.material_source("Many")
        == "开箱：一、二、三等（Crate 箱，单箱最高约 50%）"
    )
    assert acquire.material_source("Shelf") == "场景里刷出：奖励室（最高约 30%）"
    assert acquire.material_source("Ore") == "副本专属矿，只能开采：副本（洞里）"
    assert acquire.material_source("Nothing") == ""
    assert online and not any(online)  # 只看本机，不在页面里逐个材料联网等


def test_names_follow_game_localization(tmp_path, monkeypatch):
    """中文名以游戏里装的汉化为准（2026-10-23 用户要求）：尺寸写 S1/S2，类别照「物品类型」，
    舰船部件按类名取名字（同名不同物品不再张冠李戴），双语包才拿来用"""
    from astral_toolkit.update import localization
    from astral_toolkit.crafting import build_crafting as B
    from astral_toolkit.crafting import labels

    assert (
        labels.SUB_ZH["size3"] == "S3"
        and labels.GEAR_ZH[("vehiclegear", "quantumdrive")] == "量子驱动器"
    )
    assert (
        labels.GEAR_ZH[("vehiclegear", "shield")] == "护盾生成器"
        and labels.SUB_ZH["tachyon"] == "快子"
    )
    assert (
        labels.SUB_ZH["undersuit"] == "基底服" and labels.SUB_ZH["distortion"] == "畸变"
    )
    ini = {
        "item_name_qdrv_arcc_s02_torrent": "激流Torrent\\n[量子 S2 民用 C]",
        "item_name_cool_jspn_s00_cryostarsl": "低温之星SL CryoStarSL\\n[冷却 S0 民用 B]",
        "item_name_radr_chco_s00_broadspecgo": "泛用规格-Go BroadSpec-Go\\n[雷达 S0 工业 B]",
        "item_nameshld_s02_kozane_scitem": "6MA “科赞Kozane”\\n[护盾 S2 军用 B]",
        "item_nametbeam_s01": "绝对牵引 TH1 牵引光束\\nSureGrip TH1 Tractor Beam",
        "item_namemodel_only": "VK-00\\n[量子 S1 军用 A]",
    }
    assert B.class_zh(ini, "BP_CRAFT_QDRV_ARCC_S02_Torrent", "Torrent") == "激流"
    assert (
        B.class_zh(ini, "BP_CRAFT_COOL_JSPN_S00_CryoStarSL_SCItem", "Cryo-Star SL")
        == "低温之星SL"
    )
    assert (
        B.class_zh(ini, "BP_CRAFT_RADR_CHCO_S00_BroadSpecGo", "BroadSpec-Go")
        == "泛用规格-Go"
    )
    assert (
        B.class_zh(ini, "BP_CRAFT_SHLD_S02_Kozane_SCItem", "6MA 'Kozane'")
        == "6MA “科赞”"
    )
    assert (
        B.class_zh(ini, "BP_CRAFT_TBEAM_S01", "SureGrip S1 Tractor Beam")
        == "绝对牵引 TH1 牵引光束"
    )
    assert (
        B.class_zh(ini, "BP_CRAFT_MODEL_ONLY", "VK-00") == ""
        and B.class_zh(ini, "BP_CRAFT_NOPE", "x") is None
    )
    # 游戏汉化：只认双语包
    live = tmp_path / "LIVE"
    loc = live / "data" / "Localization" / "chinese_(simplified)"
    loc.mkdir(parents=True)
    (loc / "global.ini").write_text(
        "\n".join(f"item_NameX{i}=激流{i}Torrent{i}\\n[量子]" for i in range(80)),
        encoding="utf-8",
    )
    from astral_toolkit.core import settings

    monkeypatch.setattr(settings, "load", lambda: {"game_log": str(live / "Game.log")})
    assert localization.game_ini() == loc / "global.ini"
    assert localization.names_source() == loc / "global.ini" and localization.names_tag(
        loc / "global.ini"
    ).startswith("game:")
    (loc / "global.ini").write_text(
        "\n".join(f"item_NameX{i}=纯中文名字{i}" for i in range(80)), encoding="utf-8"
    )
    assert localization._bilingual(loc / "global.ini") is False


def test_item_search_finds_everything():
    """物品查询搜索（1.6.41）：商店、掉落、汉化包一起搜，每件东西用完整的中文名、英文名都搜得到；
    视差步枪 → 视差 能量突击步枪（基础款在前，2026-10-23 用户报搜不到）；汉化包简称带出来的假英文名（视差步枪 → HD）不再有；
    商店和掉落数据里都没有的也搜得到，点开写明「商店和掉落数据里都没有」，能造的带上蓝图"""
    from astral_toolkit.app.api import trade as t_api
    from astral_toolkit.contracts.textkeys import en_key
    from astral_toolkit.tasks.catalog_queries import search as I
    from astral_toolkit import crafting
    from astral_toolkit.trade import names
    from astral_toolkit.tasks import trade as t_trade

    rows = I.build_index()["rows"]
    if len(rows) < 1000:
        pytest.skip("没有商店 / 掉落数据")
    miss_en = [
        e["en"]
        for e in rows
        if not any(en_key(x["en"]) == e["ek"] for x in I.find(e["en"], 30))
    ]
    miss_zh = [
        (k, e["en"])
        for e in rows
        for k in e["zks"]
        if not any(en_key(x["en"]) == e["ek"] for x in I.find(k, 30))
    ]
    assert not miss_en and not miss_zh, (
        len(miss_en),
        miss_en[:5],
        len(miss_zh),
        miss_zh[:5],
    )
    assert "HD" not in names.table().values() and "S1" not in names.table().values()
    if I.lookup("Parallax Energy Assault Rifle"):
        r = t_trade.item_search("视差步枪")
        assert r[0]["name"] == "Parallax Energy Assault Rifle" and all(
            '"' in x["name"] for x in r[1:6]
        )  # 后面是涂装版
        assert (
            t_trade.item_search("parallax rifle")[0]["name"]
            == "Parallax Energy Assault Rifle"
        )
        assert t_trade.item_search("视差")[0]["name"] == "Parallax Energy Assault Rifle"
    if I.lookup(
        "Steel"
    ):  # 只在掉落数据里、名字又很常见：以前商店搜到 5 个以上就不看掉落，搜不到
        assert t_trade.item_search("Steel")[0]["name"] == "Steel"
    # 完全一样的排第一（同一个中文名有两三件东西的，排在最前面那几个里）
    for e in rows[:: max(1, len(rows) // 300)]:
        assert en_key(I.find(e["en"], 1)[0]["en"]) == e["ek"], e["en"]
        if e["zh"]:
            assert e["ek"] in [en_key(x["en"]) for x in I.find(e["zh"], 3)], e["zh"]
    # 商店和掉落数据里都没有的（任务奖励、活动、涂装……）：搜得到，点开写明
    loc = [
        e for e in rows if not e["has_data"] and e["loc"]
    ]  # 1.6.48 起另有只在 wiki 清单里的（没有中文名）
    assert loc and all(e["zh"] for e in loc)
    e = loc[len(loc) // 2]
    hit = next(x for x in t_trade.item_search(e["zh"]) if en_key(x["name"]) == e["ek"])
    assert hit["src"] == "loc" and hit["id"] is None
    d = t_api.item_info(name=hit["name"], zh=hit["zh"], exact=True)
    assert (
        d["nowhere"]
        and d["loot"] is None
        and not d["buyable"]
        and d["name"] == hit["name"]
    )
    made = next((x for x in loc if crafting.for_item(x["en"], x["zh"])), None)
    if made:
        d = t_api.item_info(name=made["en"], zh=made["zh"], exact=True)
        assert d["nowhere"] and d["craft"]["key"] and d["craft"]["name"]
    # 有数据的：不算「都没有」；顶上搜索框也是这一套
    shop = next(x for x in rows if x["shop"] is not None)
    assert not t_api.item_info(name=shop["en"], exact=True, loot=False)["nowhere"]
    assert t_trade.search(q=shop["en"])["items"][0]["name"] == shop["en"]


def test_mineral_in_item_search_with_nav():
    """矿物并进物品页搜索：去哪挖的每个地点带导航方式——Aaron Halo 进小行星带导航（挑这种矿最多的带），
    星球 / 卫星去导航页搜它，拉格朗日点矿区和没有地点数据的小行星带只给提示（2026-10-23 用户要求拆掉找矿点页）"""
    from astral_toolkit.tasks import trade as t_trade
    from astral_toolkit.mining.locations import where

    if not where("Taranite"):
        pytest.skip("没有矿点数据")
    t = t_trade.mineral_info(name="Taranite")
    kinds = {r["name"]: r["nav"] for r in t["rows"]}
    assert len(t["rows"]) == min(30, t["total"])
    assert kinds["Clio"]["kind"] == "search" and kinds["Clio"]["q"] == "Clio"
    assert kinds["ARC-L1"]["kind"] == "hint" and "ARC-L1" in kinds["ARC-L1"]["hint"]
    if "Pyro II (Monox)" in kinds:
        assert kinds["Pyro II (Monox)"]["q"] == "Monox"
    halo = t_trade._mine_nav({"name": "Aaron Halo", "kind": "Belt"}, "Quantainium")
    assert halo["kind"] == "halo" and halo["band"] == 5  # 量子矿：第5带密度最高
    assert (
        t_trade._mine_nav({"name": "Aaron Halo", "kind": "Belt"}, "Agricium")["band"]
        == 7
    )
    assert (
        t_trade._mine_nav({"name": "Keeger Belt", "kind": "Belt"}, "Gold")["kind"]
        == "hint"
    )
    assert t_trade.mineral_search(q="塔兰")[0]["en"] == "Taranite"


def test_ground_gems_searchable_with_locations():
    """SCMiner 的 ROC 车矿、手采矿也能在百货集搜到：类型、信号、地点（2026-10-25 用户要求）；Hathor 矿洞写「校准站矿洞」、不能导航"""
    from astral_toolkit.tasks import trade as t_trade

    assert (
        t_trade.mineral_search(q="杰金")[0]["en"] == "Jaclium"
    )  # 中文名一字不差先认，不模糊成「愈金」
    f = t_trade.mineral_info(name="Feynmaline")
    assert (
        f["gem"]["kind"] == "车矿"
        and f["gem"]["rs"] == 4000
        and f["rows"][0]["pct"] == 100
    )
    j = t_trade.mineral_info(name="Jaclium")
    assert (
        j["rows"][0]["place"] == "校准站矿洞" and j["rows"][0]["nav"]["kind"] == "none"
    )
    assert t_trade.mineral_info(name="Taranite")["gem"] is None


def test_item_search_wiki_gap_fill_and_tail_name_keys():
    """物品查询查漏补缺（1.6.48，用户对照 starcitizen.tools 发现搜不到的）：
    ①汉化包里 item_Cargo_…_Name / item_Mining_…_Name / item_fuelpod_…_Name 这种结尾是 Name 的键也读（矿石吊舱、采矿模组、打捞头），
      采矿模组的英文补上 Module，燃料舱第二行的属性串不当中文名；
    ②英文 wiki（游戏数据）的物品清单只补别处都没有的英文名（标 wiki），中文名只信汉化包；涂装、飞船内部通用件不补；
    ③只有掉落数据的物品也带上 wiki 的类型 / 尺寸当分类"""
    from astral_toolkit.update.localization import zh2en_items
    from astral_toolkit.tasks.catalog_queries import search as I
    from astral_toolkit.tasks import trade as t_trade

    t = zh2en_items(
        {
            "item_Cargo_ShipMining_Pod_Golem_BTGL_Name": "Golem MC-4 矿石吊舱\\nGOLEM MC-4 Ore Pod ",
            "item_Mining_Modules_Active_GRIN_Charge_BTGL_Name": "净采 模组Clearcut\\n[+15%功率|+30%绿区速度]",
            "item_fuelpod_MISC_Standard_Name": "CR-60\\n[调节1.16 | 血量22800 | 20 SCU]",
            "item_fuelpod_GRIN_BigAndFast_Name": "巨灵Gargant\\n[调节1.3 | 血量11550 | 12.4 SCU]",
            "item_scraper_GRIN_Standard_Name": "研磨 刮削模块\\nAbrade Scraper Module",
            "item_Name_x_Desc": "说明",
        }
    )
    assert t == {
        "Golem MC-4 矿石吊舱": "GOLEM MC-4 Ore Pod",
        "净采 模组": "Clearcut Module",
        "巨灵": "Gargant",
        "研磨 刮削模块": "Abrade Scraper Module",
    }
    from astral_toolkit.core import paths

    if not (paths.DATA / "wiki_items.json").exists():
        pytest.skip("没有 wiki 物品数据")
    from astral_toolkit.gamedata import names as gd_names

    assert len(gd_names.wiki_classes()) > 7000
    hit = t_trade.item_search("Hartmoore Inverter")[0]
    # 2026-10-27 起汉化包只写中文名的物品也有英文名（data/zh_only_names.json）：带中文名、来源是汉化包
    assert (
        hit["name"] == "Hartmoore Inverter Code"
        and hit["src"] == "loc"
        and hit["zh"] == "哈特莫尔转换器密码"
        and hit["category"] == "钥匙卡"
    )  # 2026-10-27 负责人定：芯片卡（DCHS 计算板、密钥）归钥匙卡一类
    assert (
        t_trade.item_search("Biological Samples")[0]["zh"] == "生物样本"
        and t_trade.item_search("生物样本")[0]["name"] == "Biological Samples"
    )
    assert not [
        r for r in t_trade.item_search("300 Series Amber") if r["src"] == "wiki"
    ]  # 涂装只有汉化包 / 掉落来源，不从 wiki 补
    assert not any(
        r["name"] == "Remote Turret" and r["src"] == "wiki"
        for r in t_trade.item_search("Remote Turret")
    )
    assert any(
        r["category"].startswith("炮塔") for r in t_trade.item_search("Remote Turret")
    )  # 掉落物品带上 wiki 的类型
    names = {r["en"] for r in I.build_index()["rows"]}
    assert "mount_gimbal_mining_golem" not in names  # 内部占位名不收


def test_item_desc_and_alias_from_wiki(monkeypatch, tmp_path):
    """物品描述和英文名对齐（1.6.49）：①描述来自 wiki 的游戏官方中文说明（data/wiki_items.json 的 d），物品页显示；
    ②汉化包的英文名按游戏内部类名（item_Name_<类名>）对到 wiki 正名，写错 / 过时的（Bulldog → Badger、Monolith Arms → Monolith Armor Arms）
      记进 name_aliases.json，搜旧写法也能找到正名；③wiki 清单带类名 cls"""
    from astral_toolkit.app.api import trade as t_api
    from astral_toolkit.update import localization as L
    from astral_toolkit.tasks.catalog_queries import search as I
    from astral_toolkit.core import paths
    from astral_toolkit.tasks import trade as t_trade

    if not (paths.DATA / "wiki_items.json").exists():
        pytest.skip("没有 wiki 物品数据")
    d = t_api.item_info(name="Helix II Mining Laser", exact=True)
    assert "采矿激光" in d["desc"] and "铝热" in d["desc"]
    t = L.zh2en_items(
        {
            "item_Name_kap_combat_heavy_arms_01_01_01": "巨石 臂甲\\nMonolith Arms",
            "item_NameX_Y": "甲\\nFoo Bar",
        },
        {"kap_combat_heavy_arms_01_01_01": "Monolith Armor Arms", "x_y": "Foo Bar"},
    )
    assert t == {"巨石 臂甲": "Monolith Armor Arms", "甲": "Foo Bar"} and L.ALIASES == {
        "Monolith Arms": "Monolith Armor Arms"
    }
    cls = L.wiki_class_names()
    assert (
        cls.get("mining_laser_thcn_helix_s2") == "Helix II Mining Laser"
        and len(cls) > 10000
    )
    # 别名文件：搜旧写法找到正名，物品页标「也叫」
    f = tmp_path / "name_aliases.json"
    f.write_text('{"Helix 2 Old Name": "Helix II Mining Laser"}', encoding="utf-8")
    real = paths.DATA
    monkeypatch.setattr(I, "_cache", _VC())
    monkeypatch.setattr(paths, "DATA", tmp_path)
    import shutil

    for n in ("zh_names.json", "wiki_items.json", "shops.json", "loot_index.json"):
        if (real / n).exists() and not (tmp_path / n).exists():
            shutil.copyfile(
                real / n, tmp_path / n
            )  # Windows 建符号链接要特权，直接复制
    try:
        hit = t_trade.item_search("Helix 2 Old Name")
        assert hit and hit[0]["name"] == "Helix II Mining Laser"
        assert (
            "Helix 2 Old Name"
            in t_api.item_info(name="Helix II Mining Laser", exact=True)["aka"]
        )
    finally:
        monkeypatch.setattr(I, "_cache", _VC())


def test_item_names_and_categories_unified():
    """物品名「中文 English」（2026-10-26）：采矿装备的中文不带型号、中文也搜得到；蓝图同样写法；商店分类用游戏里的中文"""
    from astral_toolkit.core.i18n import gear_zh_of_item, shop_cat_zh
    from astral_toolkit.crafting import display_name

    assert (
        gear_zh_of_item("Hofstede-S2 Mining Laser") == "霍夫斯泰德"
        and gear_zh_of_item("Rieger-C3 Module") == "里格"
    )
    assert (
        gear_zh_of_item("Sabir") == "萨比尔"
        and gear_zh_of_item("FLTR-L Module") == ""
        and gear_zh_of_item("Antium Core") == ""
    )
    assert (
        shop_cat_zh("Mining Laser Heads") == "采矿激光器"
        and shop_cat_zh("Arms") == "臂甲"
        and shop_cat_zh("没见过的") == "没见过的"
    )
    assert (
        display_name(
            {"n": "Hofstede-S2 Mining Laser", "z": "霍夫斯泰德-S2 型采矿激光器"}
        )
        == "霍夫斯泰德 Hofstede-S2 Mining Laser"
    )
    assert (
        display_name({"n": "Karna Rifle", "z": "卡纳 步枪"}) == "卡纳 步枪 Karna Rifle"
        and display_name({"n": "X", "z": ""}) == "X"
    )
    from astral_toolkit.tasks import trade as t_trade

    rows = t_trade.item_search("霍夫斯泰德")
    assert any(
        r["name"] == "Hofstede-S2 Mining Laser"
        and r["zh"] == "霍夫斯泰德"
        and r["category"] == "采矿激光器"
        for r in rows
    )
