"""成品属性的取值规则（dev 拆分②，2026-11-09 从 crafting/itemstats.py 搬来）：一件成品的数据（item_stats.json 的
items[uuid]，形如 {n, size, grade, cls, type, sub, mass, ver, mfr, s{各属性段}}）里，制造蓝图各槽「品质影响」用的
property_key（health_maxhealth、weapon_damage …）对应哪个数、什么单位，以及分类标签挑哪几个字段。

纯规则：吃一件成品的字典、给值，不读库（取数据在 crafting/itemstats.item / version，走 gamedata.itemstats）。
数据里没有的属性给 None：页面上只显示倍率，不显示绝对值。
"""


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
    return _first(
        _get(s, "mining_laser", "laser_power", "max"),
        _get(s, "vehicle_weapon", "damage_per_shot"),
        _get(s, "personal_weapon", "damage_per_shot"),
    )


def _firerate(s):
    return _first(_get(s, "personal_weapon", "rpm"), _get(s, "vehicle_weapon", "rpm"))


def _dmgmit(s):
    """护甲的伤害减免：各伤害类型的 multiplier（0.85 = 挡掉 15%），取平均；impact 是另一回事，不算"""
    dr = (s.get("suit_armor") or s.get("clothing") or {}).get("damage_resistance") or {}
    vals = [
        v.get("multiplier")
        for k, v in dr.items()
        if isinstance(v, dict) and isinstance(v.get("multiplier"), (int, float))
    ]
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
    "armor_radiationdissipation": (
        lambda s: _get(s, "radiation_resistance", "radiation_dissipation_rate"),
        " mRem/s",
    ),
    "itemresource_coolantgeneration": (
        lambda s: _first(
            _get(s, "cooler", "coolant_segment_generation"),
            _get(s, "cooler", "cooling_rate"),
        ),
        "",
    ),
    "itemresource_powergeneration": (
        lambda s: _first(
            _get(s, "power_plant", "power_segment_generation"),
            _get(s, "power_plant", "power_output"),
        ),
        "",
    ),
    "quantum_speed": (_qspeed, " m/s"),
    "quantum_fuelrequirement": (
        lambda s: _get(s, "quantum_drive", "quantum_fuel_requirement"),
        "",
    ),
    "radar_minaimassistdistance": (
        lambda s: _get(s, "radar", "aim_assist", "distance_min_assignment"),
        " m",
    ),
    "radar_maxaimassistdistance": (
        lambda s: _get(s, "radar", "aim_assist", "distance_max_assignment"),
        " m",
    ),
    "weapon_tractor_force": (lambda s: _get(s, "tractor_beam", "force", "max"), ""),
    "weapon_tractor_maxdist": (lambda s: _get(s, "tractor_beam", "range", "max"), " m"),
    "weapon_tractor_fullstrengthdist": (
        lambda s: _get(s, "tractor_beam", "range", "full_strength_distance"),
        " m",
    ),
    "weapon_tractor_maxvolume": (
        lambda s: _get(s, "tractor_beam", "force", "max_volume"),
        "",
    ),
    "weapon_hullscraping_speed": (
        lambda s: _get(s, "weapon_modifier", "salvage", "salvage_speed_multiplier"),
        "",
    ),
    "weapon_hullscraping_efficiency": (
        lambda s: _get(s, "weapon_modifier", "salvage", "extraction_efficiency"),
        "",
    ),
    "weapon_hullscraping_radius": (
        lambda s: _get(s, "weapon_modifier", "salvage", "radius_multiplier"),
        "",
    ),
    # 后坐力三项、装填速度、散布：wiki 数据里没有对应的基础值，只显示倍率
}


def base_value_of(it, prop_key):
    """这件成品（数据字典，没有是 None）这项属性的基础值 → (数值, 单位)；数据里没有 → (None, "")"""
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


def tags_of(it):
    """分类标签：尺寸 / 等级 / 类别 / 厂商 / 类型 / 子类型（护甲是 Light / Medium / Heavy）/ 物品类名。
    返回 {size, grade, cls, mfr, type, sub, cn}，没有数据返回 {}"""
    if not it:
        return {}
    return {
        "size": it.get("size"),
        "grade": it.get("grade"),
        "cls": it.get("cls"),
        "mfr": it.get("mfr"),
        "type": it.get("type"),
        "sub": it.get("sub"),
        "cn": it.get("cn"),
    }
