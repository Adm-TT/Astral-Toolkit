"""新界面的一级分类（2026-11-23）：商店分类 / wiki 类型 → 十个大类之一。

新界面的仓库、查询、交易行按大类分页签。只看物品自己的资料（商店分类 cat、wiki 类型 wtype、英文名），
拿不准的一律归「未分类」，不猜。纯规则，不读数据。
"""

CLASSES = (
    ("weapon", "武器"),
    ("attachment", "配件"),
    ("armor", "护甲服装"),
    ("ammo", "弹药"),
    ("consumable", "消耗品"),
    ("collectible", "收藏品"),
    ("access", "通行凭证"),
    ("ship", "载具部件"),
    ("material", "材料"),
    ("unclassified", "未分类"),
)

_ARMOR_CATS = (
    "Jackets Footwear Legwear Helmets Shirts Arms Legs Torso Undersuits Hats Gloves Backpacks Mobiglas"
).split()
_SHIP_CATS = (
    "Guns|Radar|Coolers|Missiles|Flight Blade|Quantum Drives|Power Plants|Shield Generators|Liveries|"
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
    **dict.fromkeys(_ARMOR_CATS, "armor"),
    **dict.fromkeys(_SHIP_CATS, "ship"),
}
_SHIP_TYPES = (
    "Paints WeaponGun MissileLauncher PowerPlant Turret WeaponDefensive Shield Cooler Module QuantumDrive "
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
    "RemovableChip": "access",
    "Cargo": "material",
    **dict.fromkeys(_SHIP_TYPES, "ship"),
}
_ARMOR_PREFIXES = ("Char_Armor_", "Char_Clothing_", "Char_Accessory_", "Char_Head_")


def top_class(cat: str | None = "", wtype: str | None = "", en: str | None = "") -> str:
    """一件物品的大类键（CLASSES 里的一个）。先看商店分类，没有再看 wiki 类型；弹匣从配件里单拎成弹药"""
    cat = cat if isinstance(cat, str) else ""
    wtype = wtype if isinstance(wtype, str) else ""
    en = en if isinstance(en, str) else ""
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
