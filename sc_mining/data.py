"""星际公民挖矿助手 —— 游戏数据（基于 4.10.2-LIVE）

来源：starcitizen.tools / api.star-citizen.wiki（矿头、模组、手持工具）、
grimhex.net（矿物信号）、UEX / cryon.rocks（精炼站加成、矿价）。
每个大版本更新后都要核对一遍。标了 TODO 的是来源有冲突或待确认的值。
"""
import sys

GAME_VERSION = "4.10.2"

# ---------------------------------------------------------------- 矿物信号
# 单块原矿的雷达信号值（以 SCMiner 矿物目录为准，4.10.2）。一簇 N 块 = 基础值 × N。
SIGNATURES = {
    "Quantainium": 3170, "Stileron": 3185, "Savrilium": 3200,
    "Ouratite": 3370, "Riccite": 3385, "Lindinium": 3400,
    "Beryl": 3540, "Taranite": 3555, "Borase": 3570, "Gold": 3585, "Bexalite": 3600,
    "Laranite": 3825, "Aslarite": 3840, "Titanium": 3855, "Tungsten": 3870,
    "Agricium": 3885, "Torite": 3900,
    "Hephaestanite": 4180, "Tin": 4195, "Quartz": 4210, "Corundum": 4225,
    "Copper": 4240, "Silicon": 4255, "Iron": 4270, "Aluminum": 4285, "Ice": 4300,
}

RARITY = {
    **dict.fromkeys(["Quantainium", "Stileron", "Savrilium"], "传说"),
    **dict.fromkeys(["Ouratite", "Riccite", "Lindinium"], "史诗"),
    # 波射石：SCMiner 写史诗，游戏数据是稀有（rareshipmineables，一团 2～4 块），以解包为准（用户 2026-10-27）
    **dict.fromkeys(["Beryl", "Taranite", "Gold", "Bexalite", "Borase"], "稀有"),
    **dict.fromkeys(["Laranite", "Aslarite", "Titanium", "Tungsten", "Agricium", "Torite"], "罕见"),
    **dict.fromkeys(["Hephaestanite", "Tin", "Quartz", "Corundum", "Copper",
                     "Silicon", "Iron", "Aluminum", "Ice"], "普通"),
}

MAX_CLUSTER = 10  # 一簇最多几块（SCMiner 列 1–10 块）

# ---------------------------------------------------------------- 矿头
# pmax/pmin: 最大/最小功率；res/instab/window/rate: 百分比修正（-30 表示 -30%）；slots: 模组槽数；size: 尺寸
# S2 四个原有矿头：starcitizen.tools（4.10.2-LIVE.12881860）+ SCMiner + 汉化包三方一致，保留原值。
# 其余（S1、Pitman、Impact II、Klein-S2）：erkul.games 解包数据（4.10.2-LIVE.12913470），已与 Wiki 抽查一致。
HEADS = {
    "helix_ii": dict(name="Helix II", size=2, pmin=1479, pmax=4930, slots=3,       # 解包 2026-10-27：最低 30%、没有充能速率加成
                     res=-30, instab=0, window=-40, rate=0),
    "hofstede_s2": dict(name="Hofstede-S2", size=2, pmin=406, pmax=4060, slots=2,
                        res=-30, instab=10, window=60, rate=20),
    "lancet_mh2": dict(name="Lancet MH2", size=2, pmin=1305, pmax=4350, slots=2,     # 解包：最低 30%
                       res=0, instab=-10, window=-60, rate=40),
    "arbor_mh2": dict(name="Arbor MH2", size=2, pmin=145, pmax=2900, slots=2,
                      res=25, instab=-35, window=40, rate=0),
    "impact_ii": dict(name="Impact II", size=2, pmin=1218, pmax=4060, slots=3,
                      res=10, instab=-10, window=20, rate=-40),
    "klein_s2": dict(name="Klein-S2", size=2, pmin=870, pmax=4350, slots=1,
                     res=-45, instab=35, window=20, rate=0),
    "arbor_mh1": dict(name="Arbor MH1", size=1, pmin=117, pmax=2340, slots=1,
                      res=25, instab=-35, window=40, rate=0),
    "helix_i": dict(name="Helix I", size=1, pmin=780, pmax=3900, slots=2,
                    res=-30, instab=0, window=-40, rate=0),
    "hofstede_s1": dict(name="Hofstede-S1", size=1, pmin=130, pmax=2600, slots=1,
                        res=-30, instab=10, window=60, rate=20),
    "impact_i": dict(name="Impact I", size=1, pmin=520, pmax=2600, slots=2,
                     res=10, instab=-10, window=20, rate=-40),
    "klein_s1": dict(name="Klein-S1", size=1, pmin=468, pmax=3120, slots=0,
                     res=-45, instab=35, window=20, rate=0),
    "lancet_mh1": dict(name="Lancet MH1", size=1, pmin=624, pmax=3120, slots=1,
                       res=0, instab=-10, window=-60, rate=40),
    # 魔像（Golem）专用，游戏里锁死不能换，只能换模组
    "pitman": dict(name="Pitman", size=1, pmin=780, pmax=3900, slots=2,
                   res=25, instab=35, window=40, rate=-40, ship="golem"),
}

# ---------------------------------------------------------------- 被动模组（S1、S2 通用）
# power: 功率修正 %；window: 绿区大小 %；rate: 充能速率 %；res: 抗性 %；instab: 不稳定 %
# 原有三个（Rieger-C3、Focus III、Torrent III）三方一致；其余取 erkul 解包（4.10.2），与原有三个的数值一致。
MODULES = {
    "rieger": dict(name="Rieger", power=15, window=-10),
    "rieger_c2": dict(name="Rieger-C2", power=20, window=-3),
    "rieger_c3": dict(name="Rieger-C3", power=25, window=-1),
    # Vaux / XTR / FLTR 改的是「提取」光束功率（extract），不是破碎功率（解包 2026-10-27；以前当成破碎功率算）
    "vaux": dict(name="Vaux", extract=15, rate=-20),
    "vaux_c2": dict(name="Vaux-C2", extract=20, rate=-15),
    "vaux_c3": dict(name="Vaux-C3", extract=25, rate=-5),
    "focus": dict(name="Focus", power=-15, window=30),
    "focus_ii": dict(name="Focus II", power=-10, window=37),
    "focus_iii": dict(name="Focus III", power=-5, window=40),
    "torrent": dict(name="Torrent", window=-10, rate=30),
    "torrent_ii": dict(name="Torrent II", window=-3, rate=35),
    "torrent_iii": dict(name="Torrent III", window=-1, rate=45),
    "xtr": dict(name="XTR", extract=-15, window=15, filter=5),
    "xtr_l": dict(name="XTR-L", extract=-10, window=22, filter=5.75),
    "xtr_xl": dict(name="XTR-XL", extract=-5, window=25, filter=6),
    "fltr": dict(name="FLTR", extract=-15, filter=20),
    "fltr_l": dict(name="FLTR-L", extract=-10, filter=23),
    "fltr_xl": dict(name="FLTR-XL", extract=-5, filter=24),
    "deluge": dict(name="Deluge", power=15, res=-15.5),
    "overrun": dict(name="Overrun", power=2, res=-24.8),
}

# ---------------------------------------------------------------- 手持工具（贴在原矿上）
GADGETS = {
    "sabir": dict(name="Sabir", res=-50, instab=15, window=50),
    "optimax": dict(name="OptiMax", res=-25, window=-30, cluster=60),          # 解包：抗性 -25%（以前 -30）
    "boremax": dict(name="BoreMax", res=10, instab=-70, cluster=30),
    "okunis": dict(name="Okunis", window=50, rate=100, cluster=-20),
    "waveshift": dict(name="WaveShift", instab=-35, window=100, rate=-30),
    "stalwart": dict(name="Stalwart", instab=-35, window=-30, rate=50, cluster=30),
}

# ---------------------------------------------------------------- 采矿船
# heads: 几个矿头位；size: 矿头尺寸；bag: 矿袋容量 SCU；fixed: 矿头锁死（只能换模组）；crew_max: 最多几人同时开矿头
SHIPS = {
    "mole": dict(name="鼹鼠 MOLE", size=2, heads=3, crew_max=3, bag=96),          # 矿袋 8×12 SCU
    "prospector": dict(name="勘探者 Prospector", size=1, heads=1, crew_max=1, bag=32),  # 4×8 SCU
    "golem": dict(name="魔像 Golem", size=1, heads=1, crew_max=1, bag=32, fixed="pitman"),  # 2×16 SCU
}

# 每条船的出厂配置（用户第一次用原矿扫描时选船，再在「我的配置」里改成自己实际装的，存在 userdata/settings.json）
DEFAULT_LOADOUTS = {
    "mole": {"heads": [["arbor_mh2", []], ["arbor_mh2", []], ["arbor_mh2", []]], "crew": 1},   # 出厂：3 个 Arbor MH2
    "prospector": {"heads": [["arbor_mh1", []]], "crew": 1},     # 出厂：Arbor MH1，不带模组
    "golem": {"heads": [["pitman", []]], "crew": 1},             # 出厂：Pitman，不带模组
}
DEFAULT_SHIP = "mole"           # 还没选船时临时按这条算（窗口里会先问用户开什么船）

# 作者自己的两人 MOLE 配置（以前写死在这里当默认；现在只作参考，作者自己的已存进他的设置）
AUTHOR_MOLE = {"heads": [["helix_ii", ["rieger_c3", "rieger_c3", "focus_iii"]],
                         ["hofstede_s2", ["focus_iii", "focus_iii"]],
                         ["arbor_mh2", ["torrent_iii", "torrent_iii"]]],
               "crew": 2}

# 破碎公式（用户定）：最大可破质量 = 矿头功率 × 模组功率 × (1 − 抗性) × 5
# 等价于 所需功率 = 0.2 × 质量（与 Mort13 实测公式一致）。功率等数值取多方对照后的数据。
# 其他来源的常数只留作参考，不参与计算：SCMiner 计算器 0.36
BREAK_MODELS = {"user": 0.20, "scminer": 0.36}
DEFAULT_MODEL = "user"
AUTO_CALIBRATE = False  # 实测记录只用来核对，不自动改公式
# 扫描面板上的抗性是否还要再乘矿头自带的抗性修正。实际使用中验证：
# 如果面板显示的已经是算过矿头之后的值，改成 False。
APPLY_HEAD_RES = True
SOLO_RATIO = 1.15         # 功率比 ≥115% 算余量充足（SCMiner 档位）
GADGET_RATIO = 0.70       # 70–114% 需要贴工具；<70% 需要多人

# ---------------------------------------------------------------- 精炼
# UEX 评级：yield/cost/speed 1=低 3=高。yield_pct 为社区估算值，仅作参考。
# 精炼方式（SCMiner 4.10.2 精炼模拟器，32 SCU 量子矿批次实测值）：
# yield_pct 产出率；fee_per_scu 精炼费（按 32 SCU 的费用折算到每 SCU）；hours_per_32 每 32 SCU 用时
REFINING_METHODS = {
    "Dinyx Solventation": dict(yield_pct=45.0, fee_per_scu=80.0, hours_per_32=19.2),
    "Ferron Exchange": dict(yield_pct=45.0, fee_per_scu=100.0, hours_per_32=9.6),
    "Pyrometric Chromalysis": dict(yield_pct=45.0, fee_per_scu=112.0, hours_per_32=9.6),
    "Electrostarolysis": dict(yield_pct=38.25, fee_per_scu=96.0, hours_per_32=5.33),
    "Thermonatic Deposition": dict(yield_pct=38.25, fee_per_scu=88.0, hours_per_32=9.6),
    "Gaskin Process": dict(yield_pct=38.25, fee_per_scu=104.0, hours_per_32=2.67),
    "Cormack Method": dict(yield_pct=31.5, fee_per_scu=92.0, hours_per_32=2.67),
    "Kazen Winnowing": dict(yield_pct=31.5, fee_per_scu=88.0, hours_per_32=5.33),
    "XCR Reaction": dict(yield_pct=31.5, fee_per_scu=120.0, hours_per_32=0.8),
}
DEFAULT_METHODS = ["Dinyx Solventation", "Ferron Exchange"]

_PYRO_HUB = {"Tungsten": 4, "Quantainium": 2, "Laranite": 2, "Borase": 1, "Bexalite": -2,
             "Gold": -3, "Aluminum": -4, "Iron": -5, "Corundum": -5, "Copper": -5,
             "Agricium": -8}
_ARC_L1 = {"Quartz": 11, "Beryl": 7, "Titanium": 5, "Quantainium": 3, "Iron": 1,
           "Laranite": -2, "Corundum": -4, "Hephaestanite": -4, "Aluminum": -5, "Taranite": -6}
_CRU_L1 = {"Beryl": 7, "Corundum": 7, "Iron": 2, "Tungsten": 2, "Titanium": -1,
           "Hephaestanite": -2, "Bexalite": -6, "Gold": -6, "Laranite": -8}
_MIC_L1 = {"Agricium": 8, "Aluminum": 7, "Copper": 4, "Corundum": 2, "Gold": 1,
           "Laranite": 2, "Quartz": -3, "Beryl": -6}

# 精炼站加成 %（未列出的矿物 = 0）
REFINERIES = {
    # Stanton
    "ARC-L1": ("Stanton", _ARC_L1),
    "ARC-L2": ("Stanton", {"Gold": 7, "Copper": 6, "Quantainium": 3, "Titanium": 3,
                           "Bexalite": 2, "Borase": 2, "Corundum": -3, "Tungsten": -6,
                           "Hephaestanite": -8}),
    "ARC-L4": ("Stanton", {"Taranite": 5, "Quartz": -2, "Titanium": -2, "Aluminum": -3,
                           "Agricium": -4, "Beryl": -4, "Copper": -4, "Gold": -4,
                           "Hephaestanite": -5, "Tungsten": -5, "Corundum": -9}),
    "CRU-L1": ("Stanton", _CRU_L1),
    "HUR-L1": ("Stanton", _PYRO_HUB),
    "HUR-L2": ("Stanton", {"Quantainium": 2, "Beryl": 1, "Corundum": 1, "Gold": 1,
                           "Laranite": -1, "Agricium": -2, "Copper": -3, "Taranite": -3}),
    "MIC-L1": ("Stanton", _MIC_L1),
    "MIC-L2": ("Stanton", {"Bexalite": 9, "Gold": 9, "Tungsten": 9, "Corundum": 6,
                           "Titanium": 6, "Copper": 2, "Quantainium": 1, "Laranite": -1,
                           "Borase": -3, "Quartz": -5, "Beryl": -8}),
    "MIC-L5": ("Stanton", {"Titanium": 13, "Bexalite": 12, "Borase": 9, "Copper": 9,
                           "Hephaestanite": 8, "Iron": 8, "Torite": 8, "Beryl": 7,
                           "Lindinium": 7, "Savrilium": 6}),
    "Pyro Gateway (Stanton)": ("Stanton", _CRU_L1),
    "Nyx Gateway (Stanton)": ("Stanton", _ARC_L1),
    "Terra Gateway (Stanton)": ("Stanton", _MIC_L1),
    # Pyro
    "Ruin Station": ("Pyro", _PYRO_HUB),
    "Checkmate": ("Pyro", _PYRO_HUB),
    "Orbituary": ("Pyro", _PYRO_HUB),
    "Nyx Gateway (Pyro)": ("Pyro", _PYRO_HUB),
    "Stanton Gateway (Pyro)": ("Pyro", _PYRO_HUB),
    # Nyx
    "Levski": ("Nyx", {"Ice": 10, "Tin": 9, "Taranite": 8, "Iron": 8, "Bexalite": 8,
                       "Corundum": 8, "Titanium": 8, "Borase": 8, "Quartz": 8, "Tungsten": 8,
                       "Hephaestanite": 8, "Silicon": 8, "Copper": 8, "Aluminum": 8,
                       "Beryl": 8, "Agricium": 8, "Laranite": 7, "Quantainium": 5,
                       "Gold": 5, "Lindinium": 4, "Savrilium": 1, "Torite": 1}),
    "Pyro Gateway (Nyx)": ("Nyx", _PYRO_HUB),
    "Stanton Gateway (Nyx)": ("Nyx", _PYRO_HUB),
}

# ---------------------------------------------------------------- 出售
# 只在这 5 个地方卖精炼矿（UEX 终端 id）
SELL_TERMINALS = {
    12: "Area18",
    18: "Lorville",
    89: "New Babbage",
    90: "Orison",
    778: "Levski",
}

# 各城市精炼矿收购价 aUEC/SCU（UEX 快照 2026-10-20）。
# 没有的 = 快照里没抓到；0 = 该城市不收。跑 `python -m sc_mining.uex` 在线补全。
_A, _L, _N, _O, _V = "Area18", "Lorville", "New Babbage", "Orison", "Levski"
CITY_PRICES = {
    "Quantainium": {_A: 150000, _L: 150000, _N: 150000, _O: 170000, _V: 140000},
    "Stileron": {_A: 140000, _L: 140000, _N: 140000, _O: 140000, _V: 140000},
    "Savrilium": {_O: 130000, _V: 110000},
    "Riccite": {_A: 66000, _L: 66000, _N: 66000, _O: 66000, _V: 77000},
    "Lindinium": {_A: 51000, _N: 51000, _O: 51000, _V: 43000},
    "Ouratite": {_A: 46000, _L: 46000, _N: 46000, _O: 46000, _V: 46000},
    "Gold": {_A: 31000, _L: 31000, _N: 30000, _O: 30000, _V: 26000},
    "Taranite": {_A: 27000, _L: 27000, _N: 28000, _O: 28000, _V: 28000},
    "Borase": {_A: 28000, _L: 28000, _N: 28000, _V: 24000},
    "Bexalite": {_A: 28000, _L: 28000, _N: 28000, _V: 27000},
    "Beryl": {_A: 20000, _L: 20000, _N: 20000, _O: 20000, _V: 0},
    "Agricium": {_A: 10000, _L: 10000, _N: 10000, _O: 10000},
    "Tungsten": {_A: 10000, _L: 10000, _N: 10000, _O: 10000},
    "Laranite": {_A: 8500, _L: 8800, _N: 8600, _O: 8500},
    "Titanium": {_A: 8300, _L: 8300, _N: 8300, _O: 8300},
    "Torite": {_A: 7700, _N: 7700, _O: 7700, _V: 6600},
    "Hephaestanite": {_A: 4800, _L: 4800, _N: 5400, _O: 4800},
    "Aslarite": {_A: 5100, _L: 5100, _N: 5100, _O: 5100, _V: 5100},
    "Ice": {_A: 5100, _L: 5100, _N: 5100, _O: 5100},  # 精炼后为 Pressurized Ice
    "Quartz": {_A: 4400, _L: 4400, _N: 4400, _O: 4400, _V: 3500},
    "Aluminum": {_A: 3800, _L: 3800, _N: 3800, _O: 3800, _V: 3200},
    "Copper": {_A: 3700, _N: 3700, _V: 3400},
    "Corundum": {_A: 3700, _N: 3700, _O: 3700},
    "Tin": {_A: 3500, _L: 3500, _N: 3500},
    "Iron": {_A: 3400, _O: 3400},
    "Silicon": {_A: 2400, _L: 2400, _N: 2400, _O: 2400, _V: 2400},
}


def best_price(mineral):
    """返回 (最高收购价, 城市)；5 个城市都不收或没数据时返回 (0, None)"""
    cities = CITY_PRICES.get(mineral, {})
    if not cities:
        return 0, None
    city = max(cities, key=cities.get)
    return cities[city], (city if cities[city] else None)


# 矿价 / 精炼站加成的最新值（data/prices.json，更新数据时从 UEX 下的）：覆盖上面写死的快照（2026-10-28 整体审查：以前只有命令行版用过）
try:
    from .uex import apply_live as _apply_live
    _apply_live(sys.modules[__name__])
except Exception:
    pass
