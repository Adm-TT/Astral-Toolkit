"""成品的基础数值（data/item_stats.json，来自 star-citizen.wiki 的游戏解包数据，tools/build_item_stats.py 生成）

制造页的「属性统计」：基础值 → 按材料品质强化后的值 → 变化。按 uuid 和 scmdb 蓝图对上（bp["u"]）。
property_key 是 scmdb 蓝图里各槽「品质影响」用的键（health_maxhealth、weapon_damage …），这里把它对到解包数据的字段。
数据里没有的属性返回 None：页面上只显示倍率，不显示绝对值。
"""
import json
from functools import lru_cache

from . import paths


@lru_cache(maxsize=1)
def data():
    p = paths.data("item_stats.json")
    if not p.exists():
        return {"version": "", "items": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def item(uuid):
    return data()["items"].get(uuid or "") or None


def version():
    return data().get("version", "")


def _get(d, *path):
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d if isinstance(d, (int, float)) and not isinstance(d, bool) else None


def _first(*vals):
    return next((v for v in vals if v is not None), None)


# property_key → (取值函数, 单位)。取值函数拿到数据段 s 返回数值或 None。字段名按 2026-10-24 拉下来的数据核对过
def _damage(s):
    return _first(_get(s, "mining_laser", "laser_power", "max"), _get(s, "vehicle_weapon", "damage_per_shot"),
                  _get(s, "personal_weapon", "damage_per_shot"))


def _firerate(s):
    return _first(_get(s, "personal_weapon", "rpm"), _get(s, "vehicle_weapon", "rpm"))


def _dmgmit(s):
    """护甲的伤害减免：各伤害类型的 multiplier（0.85 = 挡掉 15%），取平均；impact 是另一回事，不算"""
    dr = (s.get("suit_armor") or s.get("clothing") or {}).get("damage_resistance") or {}
    vals = [v.get("multiplier") for k, v in dr.items() if isinstance(v, dict) and isinstance(v.get("multiplier"), (int, float))]
    return round(sum(vals) / len(vals), 4) if vals else None


def _qspeed(s):
    return _get(s, "quantum_drive", "standard_jump", "drive_speed")


PROPS = {
    "health_maxhealth": (lambda s: _get(s, "durability", "health"), ""),
    "shield_maxhealth": (lambda s: _get(s, "shield", "max_health"), ""),
    "weapon_damage": (_damage, ""),
    "weapon_firerate": (_firerate, " RPM"),
    "armor_damagemitigation": (_dmgmit, ""),
    "armor_temperaturemin": (lambda s: _get(s, "temperature_resistance", "min"), " ºC"),
    "armor_temperaturemax": (lambda s: _get(s, "temperature_resistance", "max"), " ºC"),
    "armor_radiationdissipation": (lambda s: _get(s, "radiation_resistance", "radiation_dissipation_rate"), " mRem/s"),
    "itemresource_coolantgeneration": (lambda s: _first(_get(s, "cooler", "coolant_segment_generation"), _get(s, "cooler", "cooling_rate")), ""),
    "itemresource_powergeneration": (lambda s: _first(_get(s, "power_plant", "power_segment_generation"), _get(s, "power_plant", "power_output")), ""),
    "quantum_speed": (_qspeed, " m/s"),
    "quantum_fuelrequirement": (lambda s: _get(s, "quantum_drive", "quantum_fuel_requirement"), ""),
    "radar_minaimassistdistance": (lambda s: _get(s, "radar", "aim_assist", "distance_min_assignment"), " m"),
    "radar_maxaimassistdistance": (lambda s: _get(s, "radar", "aim_assist", "distance_max_assignment"), " m"),
    "weapon_tractor_force": (lambda s: _get(s, "tractor_beam", "force", "max"), ""),
    "weapon_tractor_maxdist": (lambda s: _get(s, "tractor_beam", "range", "max"), " m"),
    "weapon_tractor_fullstrengthdist": (lambda s: _get(s, "tractor_beam", "range", "full_strength_distance"), " m"),
    "weapon_tractor_maxvolume": (lambda s: _get(s, "tractor_beam", "force", "max_volume"), ""),
    "weapon_hullscraping_speed": (lambda s: _get(s, "weapon_modifier", "salvage", "salvage_speed_multiplier"), ""),
    "weapon_hullscraping_efficiency": (lambda s: _get(s, "weapon_modifier", "salvage", "extraction_efficiency"), ""),
    "weapon_hullscraping_radius": (lambda s: _get(s, "weapon_modifier", "salvage", "radius_multiplier"), ""),
    # 后坐力三项、装填速度、散布：解包数据里没有对应的基础值，只显示倍率
}


def base_value(uuid, prop_key):
    """成品这项属性的基础值（数据里没有 → None）。返回 (数值, 单位)"""
    it = item(uuid)
    if not it:
        return None, ""
    fn, unit = PROPS.get(prop_key, (None, ""))
    if fn is None:
        return None, ""
    try:
        v = fn(it.get("s") or {})
    except Exception:
        v = None
    return (round(v, 4) if isinstance(v, (int, float)) else None), unit


def tags(uuid):
    """分类标签：尺寸 / 等级 / 类别 / 厂商。返回 {size, grade, cls, mfr, type}，没有数据返回 {}"""
    it = item(uuid)
    if not it:
        return {}
    return {"size": it.get("size"), "grade": it.get("grade"), "cls": it.get("cls"), "mfr": it.get("mfr"), "type": it.get("type")}
