"""测试 navigation 拆分出的 names.py 与 waypoints.py 子模块"""

from sc_mining.navigation import names, waypoints, navigate


def test_names_mappings():
    assert names.BODY_ZH["Hurston"] == "赫斯顿"
    assert names.BODY_ZH["Microtech"] == "微科星"
    assert names.SYS_ZH["Stanton"] == "斯坦顿"
    assert names.CITY_ZH["NewBabbage"] == "新巴贝奇"
    assert names.TYPE_ZH["Waypoint"] == "路标"
    assert names.QT_ZH[1] == "有信标"


def test_names_rule_zh():
    assert "岩石洞穴" in names.rule_zh("Rock Cave #12")
    assert "残骸" in names.rule_zh("Caterpillar Derelict 01")
    assert names.body_label("Hurston") == "赫斯顿（Hurston）"
    assert names.body_label("@Stanton") == "斯坦顿星系 太空"


def test_names_facade_reexport():
    assert navigate.BODY_ZH is names.BODY_ZH
    assert navigate.CITY_ZH is names.CITY_ZH
    assert navigate.rule_zh is names.rule_zh
    assert navigate.label is names.label
    assert navigate.body_label is names.body_label


def test_waypoints_clipboard_parsing():
    valid = "Coordinates: x:-18930539540.1 y:-2610158765.2 z:295000.3"
    parsed = waypoints.parse_clip(valid)
    assert parsed is not None
    assert parsed[0] == -18930539540.1
    assert parsed[1] == -2610158765.2
    assert parsed[2] == 295000.3

    assert waypoints.parse_clip("Not coordinates text") is None
    assert waypoints.parse_clip("") is None


def test_waypoints_crud(tmp_path, monkeypatch):
    wp_file = tmp_path / "waypoints.json"
    monkeypatch.setattr(waypoints, "WAYPOINTS", wp_file)
    monkeypatch.setattr(navigate, "WAYPOINTS", wp_file)

    assert waypoints.waypoints() == []

    # 添加地表路标
    waypoints.add_waypoint("测试路标1", "Daymar", [10.5, 20.3, 30.1])
    all_wps = waypoints.waypoints()
    assert len(all_wps) == 1
    assert all_wps[0]["n"] == "测试路标1"
    assert all_wps[0]["b"] == "Daymar"
    assert all_wps[0]["x"] == 10.5
    assert not waypoints.is_space(all_wps[0])

    # 添加太空路标
    waypoints.add_space_waypoint(
        "太空路标1", "Stanton", [1000000.0, 2000000.0, 3000000.0]
    )
    all_wps = waypoints.waypoints()
    assert len(all_wps) == 2
    space_wp = [w for w in all_wps if w["n"] == "太空路标1"][0]
    assert waypoints.is_space(space_wp)
    assert space_wp["x"] == 1000.0

    # 删除路标
    assert waypoints.delete_waypoint("测试路标1") is True
    assert len(waypoints.waypoints()) == 1
    assert waypoints.delete_waypoint("不存在的路标") is False


def test_waypoints_facade_reexport():
    assert navigate.waypoints is waypoints.waypoints
    assert navigate.add_waypoint is waypoints.add_waypoint
    assert navigate.add_space_waypoint is waypoints.add_space_waypoint
    assert navigate.delete_waypoint is waypoints.delete_waypoint
    assert navigate.parse_clip is waypoints.parse_clip
    assert navigate.is_space is waypoints.is_space
