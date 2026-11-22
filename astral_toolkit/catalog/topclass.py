"""新界面的一级分类（2026-11-23）：商店分类 / wiki 类型 → 十个大类之一，部分大类下面再分小类。

新界面的仓库、查询、交易行按大类分页签。只看物品自己的资料（商店分类 cat、wiki 类型 wtype、英文名），
拿不准的一律归「未分类」，不猜。纯规则，不读数据。
老大 11-23 定：衣服算「服饰」（和护甲同一个大类、分开的小类）；涂装单独一个小类，挂在装饰下面。
"""

CLASSES = (
    ("weapon", "武器"),
    ("attachment", "配件"),
    ("armor", "护甲服饰"),
    ("ammo", "弹药"),
    ("consumable", "消耗品"),
    ("collectible", "装饰收藏"),
    ("access", "通行凭证"),
    ("ship", "载具部件"),
    ("material", "材料"),
    ("unclassified", "未分类"),
)
# 大类 → 下面的小类（键、中文）；没列的大类不分小类
SUBS = {
    "armor": (("armor", "护甲"), ("clothing", "服饰")),
    "collectible": (("paint", "涂装"), ("decor", "摆件收藏")),
}

_CLOTHING_CATS = "Jackets Footwear Legwear Shirts Hats Gloves Mobiglas".split()
_ARMOR_CATS = "Helmets Arms Legs Torso Undersuits Backpacks".split()
_SHIP_CATS = (
    "Guns|Radar|Coolers|Missiles|Flight Blade|Quantum Drives|Power Plants|Shield Generators|"
    "Missile Racks|Turrets|Mining Modules|Mining Laser Heads|Module|Bomb Racks|External Fuel Tanks|"
    "Tractor Beams|Docking Collars|Scraper Beams|Salvage Beams|Bombs|Jump Modules"
).split("|")
_CAT = {
    "Personal Weapons": "weapon",
    "Attachments": "attachment",
    "Foods": "consumable",
    "Drinks": "consumable",
    "Consumables": "consumable",
    "Decorations": "collectible",
    "Surface": "collectible",
    "Liveries": "collectible",
    **dict.fromkeys(_CLOTHING_CATS, "armor"),
    **dict.fromkeys(_ARMOR_CATS, "armor"),
    **dict.fromkeys(_SHIP_CATS, "ship"),
}
_SHIP_TYPES = (
    "WeaponGun MissileLauncher PowerPlant Turret WeaponDefensive Shield Cooler Module QuantumDrive "
    "Missile TurretBase Radar QuantumInterdictionGenerator LifeSupportGenerator MiningModifier Battery EMP "
    "ToolArm TractorBeam SalvageHead DockingCollar FuelTank MainThruster ManneuverThruster SalvageModifier "
    "JumpDrive FuelIntake ExternalFuelTank WeaponMining QuantumFuelTank UtilityTurret TowingBeam Armor "
    "GroundVehicleMissileLauncher Thruster"
).split()
_WTYPE = {
    "WeaponPersonal": "weapon",
    "Grenade": "weapon",
    "WeaponAttachment": "attachment",
    "Suit": "armor",
    "Food": "consumable",
    "Drink": "consumable",
    "FPS_Consumable": "consumable",
    "Bottle": "consumable",
    "Misc": "collectible",
    "Usable": "collectible",
    "Paints": "collectible",
    "RemovableChip": "access",
    "Cargo": "material",
    **dict.fromkeys(_SHIP_TYPES, "ship"),
}
_CLOTHING_PREFIXES = ("Char_Clothing_", "Char_Accessory_", "Char_Head_")
_ARMOR_PREFIXES = ("Char_Armor_", *_CLOTHING_PREFIXES)


def _text(v) -> str:
    return v if isinstance(v, str) else ""


def top_class(cat: str | None = "", wtype: str | None = "", en: str | None = "") -> str:
    """一件物品的大类键（CLASSES 里的一个）。先看商店分类，没有再看 wiki 类型；弹匣从配件里单拎成弹药"""
    cat, wtype, en = _text(cat), _text(wtype), _text(en)
    if (
        cat == "Attachments" or wtype == "WeaponAttachment"
    ) and "magazine" in en.lower():
        return "ammo"
    top = _CAT.get(cat) or _WTYPE.get(wtype)
    if top:
        return top
    if wtype.startswith(_ARMOR_PREFIXES):
        return "armor"
    if wtype.startswith("Flair_"):
        return "collectible"
    if wtype.endswith("Controller"):
        return "ship"
    return "unclassified"


def sub_class(cat: str | None = "", wtype: str | None = "", en: str | None = "") -> str:
    """大类下面的小类键（SUBS 里的）；这个大类不分小类就是空串。和 top_class 一样先看商店分类"""
    cat, wtype = _text(cat), _text(wtype)
    top = top_class(cat, wtype, en)
    if top == "armor":
        if cat in _CLOTHING_CATS:
            return "clothing"
        if cat in _ARMOR_CATS:
            return "armor"
        return "clothing" if wtype.startswith(_CLOTHING_PREFIXES) else "armor"
    if top == "collectible":
        return "paint" if cat == "Liveries" or wtype == "Paints" else "decor"
    return ""
