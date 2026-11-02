"""测试 navigation 拆分出的 names.py、waypoints.py、starmap.py、celestial.py 与 transit.py 子模块"""

import math
from astral_toolkit.navigation import names, waypoints, starmap, celestial, transit, navigate


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


def test_starmap_compact():
    oc = [
        {
            "Type": "Planet",
            "BodyRadius": 1000000,
            "System": "Stanton",
            "Planet": "Microtech",
            "XCoord": 100.0,
            "YCoord": 200.0,
            "ZCoord": 300.0,
            "RotationSpeedX": 24.0,
            "RotationAdjustmentX": 10.0,
            "OrbitalMarkerRadius": 1200000,
            "GRIDRadius": 1500000,
        }
    ]
    pois = [
        {
            "Planet": "Microtech",
            "PoiName": "New Babbage",
            "Type": "City",
            "XCoord": 10.0,
            "YCoord": 20.0,
            "ZCoord": 30.0,
            "QTMarker": 1,
        }
    ]
    data = starmap.compact(oc, pois)
    assert "bodies" in data
    assert "Microtech" in data["bodies"]
    assert len(data["pois"]) == 1
    assert data["pois"][0]["n"] == "New Babbage"


def test_starmap_facade_reexport():
    assert navigate.CACHE is starmap.CACHE
    assert navigate.API is starmap.API
    assert navigate.load is starmap.load
    assert navigate.compact is starmap.compact
    assert navigate.update is starmap.update


def test_celestial_math():
    # 经纬度互转
    pos = celestial.from_latlon(45.0, 90.0, 1000.0, 500.0)
    lat, lon, r = celestial.latlon(pos)
    assert abs(lat - 45.0) < 1e-4
    assert abs(lon - 90.0) < 1e-4
    assert abs(r - 1000.5) < 1e-4

    # 距离计算
    assert celestial.direct_km((0, 0, 0), (3, 4, 0)) == 5.0
    surf = celestial.surface_km((1000, 0, 0), (0, 1000, 0), 1000.0)
    assert abs(surf - 1000.0 * (math.pi / 2)) < 1e-2

    # 罗盘方位
    assert celestial.compass(0) == "北"
    assert celestial.compass(90) == "东"
    assert celestial.compass(180) == "南"
    assert celestial.compass(270) == "西"

    # 方位角与转向
    brg = celestial.bearing((1000, 0, 0), (0, 1000, 0))
    assert isinstance(brg, float)
    s = celestial.steer((0, 0, 0), (0, 0, 0), (0, 100, 0))
    assert "turn" in s and "pitch" in s and "off" in s


def test_celestial_facade_reexport():
    assert navigate.latlon is celestial.latlon
    assert navigate.from_latlon is celestial.from_latlon
    assert navigate.bearing is celestial.bearing
    assert navigate.surface_km is celestial.surface_km
    assert navigate.direct_km is celestial.direct_km
    assert navigate.compass is celestial.compass
    assert navigate.locate is celestial.locate
    assert navigate.cam_axes is celestial.cam_axes
    assert navigate.steer is celestial.steer
    assert navigate.project is celestial.project
    assert navigate.rotation_deg is celestial.rotation_deg
    assert navigate.CALIB is celestial.CALIB
    assert navigate.LAST is celestial.LAST


def test_transit_helpers():
    assert transit.LINE_ZH["loop"] == "微科地铁环线"
    assert transit._bi("商业区", "Commerce") == "商业区（Commerce）"
    assert transit._bi("Station", "Station") == "Station"
    assert transit._zkey("Transit_Carriage_01") == "transitcarriage01"
    assert transit._hangar_size("Hangar_Medium_02") == "Medium"
    assert transit._car_changed("12345", "12999") is True
    assert transit._car_changed("12345", "12345") is False


def test_transit_facade_reexport():
    assert navigate.city_places is transit.city_places
    assert navigate.city_route is transit.city_route
    assert navigate.city_leg is transit.city_leg
    assert navigate.station_lifts is transit.station_lifts
    assert navigate.station_route is transit.station_route
    assert navigate.station_leg is transit.station_leg
    assert navigate.zone_kind is transit.zone_kind
    assert navigate.site_at is transit.site_at
    assert navigate.nearest is transit.nearest
    assert navigate.amenity_targets is transit.amenity_targets
