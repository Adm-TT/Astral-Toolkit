"""地点补丁：导出、检查、装上、停用、删除，以及补丁里的点进搜索（2026-11-19）"""

import json

from astral_toolkit.navigation import patches as P

# 不靠真实数据的「认得哪些」：一个太空里的站、一个跟着星球转的城、一个星球、两个星系
_SITES = {
    "st_space": {
        "space": True,
        "b": "@Pyro",
        "sys": "Pyro",
        "points": [(1000.0, 2000.0, 30.0)],
    },
    "city_a": {
        "space": False,
        "b": "Hurston",
        "sys": "",
        "points": [(600.0, 600.0, 520.0)],
    },
}
KN = P.Known({"Hurston": 1000.0, "Daymar": 295.0}, ["Stanton", "Pyro"], _SITES.get)


def _patch(**over):
    base = {
        "格式": "AT 地点补丁 1",
        "游戏版本": "4.10.2",
        "日期": "2026-11-19",
        "AT 版本": "1.1.4",
        "作者": "Adm_TT",
        "地点": [
            {
                "中文名": "打印机 · 争夺区",
                "英文名": "",
                "所在": "站:st_space",
                "坐标": [1000.1, 2000.2, 30.0],
            },
            {
                "中文名": "洞口",
                "英文名": "Cave",
                "所在": "星球:Daymar",
                "坐标": [100, 200, 190],
            },
            {
                "中文名": "",
                "英文名": "Wreck",
                "所在": "太空:Stanton",
                "坐标": [1.5e5, -7890, 12],
            },
        ],
    }
    base.update(over)
    return base


def _why(obj):
    try:
        P.check(json.dumps(obj, ensure_ascii=False), KN)
    except P.PatchError as e:
        return str(e)
    return ""


def _place(**over):
    p = dict(_patch()["地点"][0])
    p.update(over)
    return _patch(地点=[p])


def test_good_patch_passes_and_keeps_only_what_the_format_has():
    out = P.check(json.dumps(_patch(), ensure_ascii=False), KN)
    assert out["head"]["作者"] == "Adm_TT"
    assert [(p["kind"], p["name"]) for p in out["places"]] == [
        ("站", "st_space"),
        ("星球", "Daymar"),
        ("太空", "Stanton"),
    ]
    assert out["places"][1]["zh"] == "洞口" and out["places"][1]["en"] == "Cave"
    assert out["places"][2]["xyz"] == (150000.0, -7890.0, 12.0)
    # 带 BOM 的文件（记事本存的）照收
    assert P.check(b"\xef\xbb\xbf" + json.dumps(_patch()).encode(), KN)["places"]


def test_whole_file_is_refused_when_anything_is_off():
    assert "不是 JSON" in P_why(b"not json")
    assert "1 MB" in P_why(b" " * (P.MAX_BYTES + 1))
    assert "不是地点补丁" in _why([1, 2])
    assert "没有「格式」" in _why({k: v for k, v in _patch().items() if k != "格式"})
    assert "不认识" in _why(_patch(格式="AT 地点补丁 x"))
    assert "不认识" in _why(_patch(格式="AT 地点补丁 01"))
    assert "需要先更新 AT" in _why(_patch(格式="AT 地点补丁 2"))
    for odd in (
        chr(0xB2),
        "1" * 5000,
        chr(0xFF11),
        " 1",
        "1.0",
        "",
    ):  # 不是规矩的版本号（审查 2026-11-19）
        assert "不认识" in _why(_patch(格式="AT 地点补丁 " + odd)), odd
    assert "不是 JSON" in P_why("[" * 5000 + "]" * 5000)  # 套几千层
    assert "读不出" in P_why(chr(0xD800))  # 落单的代理字符
    assert "读不出" in P_why(123)
    assert "多了「备注」" in _why(_patch(备注="hi"))  # 文件头多一项
    assert "少了「作者」" in _why({k: v for k, v in _patch().items() if k != "作者"})
    assert "「作者」不是文字" in _why(_patch(作者=5))
    assert "「作者」超过 40 个字" in _why(_patch(作者="字" * 41))
    assert "「日期」里有换行" in _why(_patch(日期="2026\n11"))
    assert "不是一张列表" in _why(_patch(地点={}))
    assert "一个地点都没有" in _why(_patch(地点=[]))
    one = _patch()["地点"][0]
    assert "超过 2000 个" in _why(_patch(地点=[one] * 2001))


def P_why(raw):
    try:
        P.check(raw, KN)
    except P.PatchError as e:
        return str(e)
    return ""


def test_each_place_is_checked_and_the_message_says_which_one():
    bad = _patch()
    bad["地点"][1]["备注"] = "多一项"
    assert _why(bad).startswith("第 2 个地点：要正好")
    assert "第 1 个地点：要正好" in _why(_patch(地点=["x"]))
    assert "「中文名」不是文字" in _why(_place(中文名=1))
    assert "「中文名」超过 40 个字" in _why(_place(中文名="字" * 41))
    assert "「英文名」里有换行" in _why(_place(英文名="a\tb"))
    assert "至少要有一个" in _why(_place(中文名=" ", 英文名=""))
    for where in ("st_space", "站：st_space", "城:st_space", "站:", 7):
        assert "「所在」要写成" in _why(_place(所在=where)), where
    assert "站「nope」AT 不认识" in _why(_place(所在="站:nope"))
    assert "星球「Mars」AT 不认识" in _why(_place(所在="星球:Mars"))
    assert "星系「Sol」AT 不认识" in _why(_place(所在="太空:Sol"))
    for xyz in ([1, 2], [1, 2, 3, 4], "1,2,3", None):
        assert "正好三个数" in _why(_place(坐标=xyz)), xyz
    for xyz in ([1, 2, "3"], [1, 2, True], [1, 2, None]):
        assert "不是数" in _why(_place(坐标=xyz)), xyz
    assert "不是 JSON" in P_why('{"坐标": [NaN]}'.replace("NaN", "nope"))
    assert "太大" in _why(_place(坐标=[10**400, 0, 0]))  # 几百位的整数不能把程序弄崩
    big = json.dumps(_place(), ensure_ascii=False).replace("1000.1", "1e999")
    assert "不是数" in P_why(big)  # 1e999 读出来是无穷大
    assert "里有换行或控制字符" in P_why(json.dumps(_place(中文名="a" + chr(0xD800))))
    assert "里有换行或控制字符" in _why(_place(中文名="a" + chr(0x2028)))
    # 范围：太空里太大、星球上太远太深、站里离站太远
    assert "太大" in _why(_place(所在="太空:Pyro", 坐标=[2e9, 0, 0]))
    assert "太远或太深" in _why(_place(所在="星球:Daymar", 坐标=[1, 1, 1]))
    assert "太远或太深" in _why(_place(所在="星球:Daymar", 坐标=[5000, 0, 0]))
    assert "这个站太远" in _why(_place(坐标=[1100.0, 2000.0, 30.0]))
    assert "这个站太远" in _why(_place(所在="站:city_a", 坐标=[700.0, 700.0, 100.0]))
    assert _why(_place(所在="站:city_a", 坐标=[600.5, 600.0, 520.0])) == ""


def test_export_round_trips_through_check():
    wps = [
        {
            "b": "@Pyro",
            "sys": "Pyro",
            "space": True,
            "n": "2",
            "x": 1000.0,
            "y": 2000.0,
            "z": 30.0,
            "city": "st_space",
            "area_id": "hall",
            "saved": "x",
        },
        {"b": "Daymar", "n": "洞口", "x": 100.0, "y": 200.0, "z": 190.0},
        {
            "b": "@Stanton",
            "sys": "Stanton",
            "space": True,
            "n": "wreck A",
            "x": 5.0,
            "y": 6.0,
            "z": 7.0,
        },
        {"b": "Daymar", "n": "", "x": 1, "y": 2, "z": 3},  # 没名字的不导
    ]
    patch = P.export(
        wps, " 我 ", game_version="4.10.2", at_version="1.1.4", date="2026-11-19"
    )
    assert list(patch) == [*P.HEAD_KEYS, "地点"]
    assert patch["作者"] == "我"
    assert patch["地点"] == [
        {
            "中文名": "",
            "英文名": "2",
            "所在": "站:st_space",
            "坐标": [1000.0, 2000.0, 30.0],
        },
        {
            "中文名": "洞口",
            "英文名": "",
            "所在": "星球:Daymar",
            "坐标": [100.0, 200.0, 190.0],
        },
        {
            "中文名": "",
            "英文名": "wreck A",
            "所在": "太空:Stanton",
            "坐标": [5.0, 6.0, 7.0],
        },
    ]
    text = P.dumps(patch)
    assert json.loads(text) == patch
    assert text.count("\n") == 5 + 1 + 3 + 2 + 1  # 文件头五行、地点一个一行
    assert len(P.check(text, KN)["places"]) == 3


def _dir(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "PATCH_DIR", tmp_path / "patches")
    monkeypatch.setattr(P, "STATE", tmp_path / "patches" / "_state.json")
    monkeypatch.setattr(P, "_cache", {"key": None, "rows": []})
    monkeypatch.setattr(P, "known", lambda: KN)


def test_install_list_toggle_remove(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    raw = json.dumps(_patch(), ensure_ascii=False).encode("utf-8")
    assert P.installed("4.10.2") == []
    info = P.install(raw, r"C:\x\我的点.json")
    assert info["file"] == "我的点.json" and info["count"] == 3
    assert (tmp_path / "patches" / "我的点.json").read_bytes() == raw  # 原样保存
    assert P.install(raw, "我的点.json")["file"] == "我的点_2.json"  # 重名加序号
    assert (
        P.install(raw, "..\\..\\_state.json")["file"] == "state.json"
    )  # 不盖状态文件、不出文件夹
    try:
        P.install(b"{}", "bad.json")
    except P.PatchError:
        pass
    else:
        raise AssertionError("坏文件装上了")
    assert not (tmp_path / "patches" / "bad.json").exists()  # 不合格什么都不存
    assert (
        P._safe_name("CON.json") == "补丁_CON"
        and P._safe_name("lpt1 .json") == "补丁_lpt1"
    )
    assert P._safe_name("  ..  ") == "补丁" and P._safe_name("x/y:z.json") == "y_z"

    rows = P.installed("4.10.3")
    assert [r["file"] for r in rows] == ["state.json", "我的点.json", "我的点_2.json"]
    assert all(r["enabled"] and r["stale"] and r["count"] == 3 for r in rows)
    assert not P.installed("4.10.2")[0]["stale"]
    assert len(P.points()) == 9

    assert P.set_enabled("我的点.json", False) and not P.set_enabled("没有.json", False)
    assert [r["enabled"] for r in P.installed()] == [True, False, True]
    assert len(P.points()) == 6
    assert P.set_enabled("我的点.json", True) and len(P.points()) == 9

    (tmp_path / "patches" / "我的点_2.json").write_text(
        "{}", encoding="utf-8"
    )  # 后来被改坏
    row = P.installed()[2]
    assert row["error"] and not row["enabled"] and row["count"] == 0
    assert len(P.points()) == 6

    assert P.remove("我的点.json") and not P.remove("我的点.json")
    assert [r["file"] for r in P.installed()] == ["state.json", "我的点_2.json"]
    assert len(P.points()) == 3


def test_points_look_like_waypoints_and_carry_their_patch(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    from astral_toolkit.navigation import transit, waypoints as W

    monkeypatch.setattr(transit, "site_area_at", lambda site, a: "hall")
    monkeypatch.setattr(W, "_with_site", lambda w: {**w, "city_zh": "某站"})
    P.install(json.dumps(_patch(), ensure_ascii=False), "a.json")
    a, b, c = P.points()
    assert (a["b"], a["sys"], a["space"], a["city"], a["area_id"]) == (
        "@Pyro",
        "Pyro",
        True,
        "st_space",
        "hall",
    )
    assert a["n"] == "打印机 · 争夺区" and a["t"] == "Waypoint" and a["qt"] == 0
    assert a["id"] == "patch:a.json:0" and a["patch"] == {
        "file": "a.json",
        "author": "Adm_TT",
    }
    assert (b["b"], b["n"], b.get("space"), b.get("city")) == (
        "Daymar",
        "洞口（Cave）",
        None,
        None,
    )
    assert (c["b"], c["sys"], c["space"], c["n"]) == (
        "@Stanton",
        "Stanton",
        True,
        "Wreck",
    )
    assert P.points() is P.points()  # 文件没变不重读

    from astral_toolkit.tasks import navigation as T

    row = T._place_row(a)
    assert row["type"] == "补丁 · Adm_TT · 某站"
    assert row["waypoint"] is False and row["patch"] == {
        "file": "a.json",
        "author": "Adm_TT",
    }
    assert row["city"] is True and row["key"] == "@Pyro|Waypoint|patch:a.json:0"
    mine = T._place_row(
        {"b": "Daymar", "n": "洞口", "t": "Waypoint", "x": 1, "y": 2, "z": 3, "qt": 0}
    )
    assert mine["waypoint"] is True and "patch" not in mine  # 自己的路标照旧


def test_patch_points_show_up_in_search(monkeypatch):
    from astral_toolkit.navigation import navigate as n

    row = {
        "b": "Daymar",
        "n": "补丁测试洞口",
        "t": "Waypoint",
        "x": 100.0,
        "y": 200.0,
        "z": 190.0,
        "qt": 0,
        "id": "patch:a.json:0",
        "patch": {"file": "a.json", "author": "X"},
    }
    monkeypatch.setattr(n, "waypoints", lambda: [])
    monkeypatch.setattr(n, "patch_points", lambda: [row])
    hits, _total = n.search("补丁测试洞口", limit=5)
    assert [h.get("id") for h in hits] == ["patch:a.json:0"]
    monkeypatch.setattr(n, "patch_points", lambda: [])
    assert n.search("补丁测试洞口", limit=5)[0] == []


def test_use_cases(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    from astral_toolkit.navigation import waypoints as W
    from astral_toolkit.tasks import navigation as T
    from astral_toolkit.tasks.navigation import place_patches as U

    shown = []
    monkeypatch.setattr(U, "_desktop", lambda: tmp_path)
    monkeypatch.setattr(U, "_reveal", shown.append)
    monkeypatch.setattr(U, "_version", lambda: "1.1.4")
    monkeypatch.setattr(U, "_game_version", lambda: "4.10.2")
    mine = [
        {
            "b": "Daymar",
            "n": "洞口",
            "t": "Waypoint",
            "x": 100.0,
            "y": 200.0,
            "z": 190.0,
        },
        {"b": "Mars", "n": "坏的", "t": "Waypoint", "x": 1.0, "y": 2.0, "z": 3.0},
    ]
    monkeypatch.setattr(W, "_waypoints_strict", lambda: list(mine))

    assert "不认识" in T.patch_export()["error"]  # 有一个导出去别人装不上：整份不导
    assert T.patch_export(names=["没有"]) == {"error": "没有可以导出的路标"}
    out = T.patch_export(names=["洞口"], author="我")
    assert out["count"] == 1 and shown and str(shown[0]) == out["path"]
    text = open(out["path"], encoding="utf-8").read()
    assert json.loads(text)["作者"] == "我" and json.loads(text)["AT 版本"] == "1.1.4"

    assert T.patch_import(text="{}", name="x.json")["error"].startswith(
        "这份补丁不收："
    )
    got = T.patch_import(text=text, name="朋友给的.json")
    assert got == {
        "file": "朋友给的.json",
        "count": 1,
        "author": "我",
        "game_version": "4.10.2",
        "stale": False,
    }
    assert T.patch_list()["rows"] == [
        {
            "file": "朋友给的.json",
            "author": "我",
            "date": json.loads(text)["日期"],
            "game_version": "4.10.2",
            "at_version": "1.1.4",
            "count": 1,
            "enabled": True,
            "stale": False,
            "error": "",
        }
    ]
    assert T.patch_toggle(file="朋友给的.json", on=False) == {
        "file": "朋友给的.json",
        "enabled": False,
    }
    assert T.patch_toggle(file="没有.json")["error"]
    assert T.patch_delete(file="朋友给的.json") == {"file": "朋友给的.json"}
    assert (
        T.patch_delete(file="朋友给的.json")["error"] and T.patch_list()["rows"] == []
    )


def test_routes_registered():
    from astral_toolkit.app.api import router

    router.reset()
    r = router.routes()
    for name in (
        "patch_export",
        "patch_import",
        "patch_list",
        "patch_toggle",
        "patch_delete",
    ):
        assert name in r, name
