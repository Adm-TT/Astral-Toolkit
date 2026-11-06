"""制造用的中文名表：装备类别、属性、物品、部件槽的中文译名。

只吃传进来的名字，不读库、不读文件、不读汉化包。
"""

GEAR_ZH = {
    ("fpsgear", "armour"): "护甲",
    ("fpsgear", "weapons"): "个人武器",
    ("fpsgear", "ammo"): "弹匣",
    ("vehiclegear", "weapons"): "舰船武器",
    ("vehiclegear", "cooler"): "冷却器",
    ("vehiclegear", "powerplant"): "发电机",
    ("vehiclegear", "shield"): "护盾生成器",
    ("vehiclegear", "radar"): "雷达",
    ("vehiclegear", "quantumdrive"): "量子驱动器",
    ("vehiclegear", "mininglaser"): "采矿激光器",
    ("vehiclegear", "miningmodule"): "采矿模组",
    ("vehiclegear", "orepod"): "矿石吊舱",
    ("vehiclegear", "tractorbeam"): "牵引光束",
    ("vehiclegear", "refuelling"): "燃料喷嘴",
    ("vehiclegear", "salvage"): "刮削模块",
    ("missionitems", None): "任务物品",
}
PROP_ZH = {
    "Min Temp": "最低耐温",
    "Max Temp": "最高耐温",
    "Damage Mitigation": "伤害减免",
    "Integrity": "结构强度",
    "Power Pips": "能量格",
    "Impact Force": "冲击力",
    "Coolant Rating": "冷却能力",
    "Max. Shield Strength": "护盾强度上限",
    "Recoil Smoothness": "后坐力平滑",
    "Recoil Handling": "后坐力控制",
    "Recoil Kick": "后坐力",
    "Fire Rate": "射速",
    "Min. Assist Distance": "最小辅助距离",
    "Max. Assist Distance": "最大辅助距离",
    "Quantum Speed": "量子速度",
    "Quantum Fuel Burn": "量子燃料消耗",
    "Full Strength Dist.": "满强度距离",
    "Max. Distance": "最大距离",
    "Radius": "半径",
    "Speed": "速度",
    "Beam Force": "光束力",
    "Max. Volume": "最大体积",
    "Efficiency": "效率",
    "Radiation Dissipation": "辐射消散",
}
ITEM_ZH = {
    "Sadaryx": "萨达瑞晶",
    "Saldynium (Ore)": "烁迪银矿石",
    "Yormandi Eye": "约曼迪之眼",
}
# 采矿激光的「Impact Force」在游戏里叫 Laser Power（scmdb 数据 nameOverrides: WeaponMining → Laser Power）
LASER_POWER = "激光功率"

# ---------------------------------------------------------------- 蓝图字典：按类别 / 子类 / 部位 / 厂商筛选

# 类别、子类的叫法照游戏汉化包（物品说明里的「物品类型：…」），2026-10-23 用户要求以游戏内汉化为准
SUB_ZH = {
    "combat": "战斗",
    "engineer": "工程",
    "hunter": "猎人",
    "stealth": "潜行",
    "miner": "矿工",
    "medic": "医疗",
    "explorer": "探索",
    "cosmonaut": "宇航",
    "environment": "环境",
    "flightsuit": "飞行服",
    "racer": "竞速",
    "radiation": "防辐射",
    "salvager": "打捞",
    "undersuit": "基底服",
    "pistol": "手枪",
    "rifle": "突击步枪",
    "smg": "冲锋枪",
    "shotgun": "霰弹枪",
    "sniper": "狙击步枪",
    "lmg": "轻机枪",
    "ballistic": "实弹",
    "laser": "激光",
    "electron": "电子",
    "plasma": "电浆",
    "distortion": "畸变",
    "neutron": "中子",
    "tachyon": "快子",
    "active": "手动激活",
    "passive": "被动生效",
    "nozzle": "燃料喷嘴",
    "small": "小型",
    "medium": "中型",
    "large": "大型",
    **{f"size{i}": f"S{i}" for i in range(0, 11)},  # 尺寸照游戏里写 S1 / S2
}
PART_ZH = {
    "Helmet": "头盔",
    "Core": "胸甲",
    "Arms": "臂甲",
    "Legs": "腿甲",
    "Backpack": "背包",
    "Undersuit": "基底服",
}
# 蓝图材料槽（部件）名：游戏汉化包里没有这些词，按部件用途译（2026-10-23）
SLOT_ZH = {
    "Acceleration Unit": "加速单元",
    "Anchor Pins": "固定销",
    "Aperture Iris": "光圈",
    "Armored Carapace": "装甲外壳",
    "Barrel": "枪管",
    "Barrels": "枪管",
    "Bus Bars": "汇流排",
    "Cabling": "线缆",
    "Case": "外壳",
    "Casing": "壳体",
    "Casing Weave": "壳体编织层",
    "Charge Chamber": "充能室",
    "Conduit": "导管",
    "Conduit Channel": "导流通道",
    "Containment Matrix": "约束矩阵",
    "Coolant": "冷却剂",
    "Core": "核心",
    "Cycler": "循环器",
    "Distorter Unit": "畸变单元",
    "Drive Motor": "驱动电机",
    "Electronics": "电子元件",
    "Emitter": "发射器",
    "Field Array": "力场阵列",
    "Filament Coating": "灯丝涂层",
    "Filter": "滤芯",
    "Focus Zone Plate": "聚焦波带片",
    "Frame": "框架",
    "Frequency Controller": "频率控制器",
    "Grip": "握把",
    "Injector Nozzles": "喷射嘴",
    "Insulative Liner": "绝缘内衬",
    "Internal Array": "内部阵列",
    "Lattice": "晶格",
    "Lenses": "透镜",
    "Magazine": "弹匣",
    "Magnetizer": "磁化器",
    "Main Valve": "主阀",
    "Ocular Enhancer": "目镜增强器",
    "Panel Covering": "面板覆层",
    "Plating": "镀层",
    "Plating Barrier": "镀层屏障",
    "Power Regulator": "功率调节器",
    "Precision Parts": "精密零件",
    "Protective Sheathing": "防护护套",
    "Pump Impeller": "泵叶轮",
    "Radiator": "散热器",
    "Reinforced Frame": "加固框架",
    "Segment Paneling": "分段面板",
    "Sheathing Coating": "护套涂层",
    "Shell": "外壳",
    "Shot": "弹丸",
    "Signal Provessor": "信号处理器",
    "Signal Processor": "信号处理器",
    "Stabilizer": "稳定器",
    "Stator Cores": "定子铁芯",
    "Stock": "枪托",
    "Substrate": "基板",
    "Suit Underlay": "服装内衬",
    "Support Structure": "支撑结构",
    "Tensive Fibre": "张力纤维",
    "Thermal Sink": "散热片",
    "Torque Junction": "扭矩接头",
    "Transmitter": "发射机",
    "Voltage Regulator": "稳压器",
    "Wiring": "布线",
}


def prop_zh(prop, bp=None):
    """属性的中文名；采矿激光的冲击力其实是激光功率"""
    if prop == "Impact Force" and bp is not None and bp.get("t") == "mininglaser":
        return LASER_POWER
    return PROP_ZH.get(prop, prop)


def slot_zh(slot):
    """材料槽名的中文；占位名、没收录的照原样"""
    if not slot or "PLACEHOLDER" in slot:
        return "材料"
    return SLOT_ZH.get(slot, slot)
