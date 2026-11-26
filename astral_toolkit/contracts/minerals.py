"""矿物清单：单块原矿的雷达信号值（采矿认信号、交易 / F8 认「这是不是矿」共用）。

原来在 mining/data.py，2026-11-26 拆领域互引时挪到这里（交易不再引用采矿）；mining/data.SIGNATURES 还是同一个 dict。
"""

# 单块原矿的雷达信号值（以 SCMiner 矿物目录为准，4.10.2）。一簇 N 块 = 基础值 × N。
SIGNATURES = {
    "Quantainium": 3170,
    "Stileron": 3185,
    "Savrilium": 3200,
    "Ouratite": 3370,
    "Riccite": 3385,
    "Lindinium": 3400,
    "Beryl": 3540,
    "Taranite": 3555,
    "Borase": 3570,
    "Gold": 3585,
    "Bexalite": 3600,
    "Laranite": 3825,
    "Aslarite": 3840,
    "Titanium": 3855,
    "Tungsten": 3870,
    "Agricium": 3885,
    "Torite": 3900,
    "Hephaestanite": 4180,
    "Tin": 4195,
    "Quartz": 4210,
    "Corundum": 4225,
    "Copper": 4240,
    "Silicon": 4255,
    "Iron": 4270,
    "Aluminum": 4285,
    "Ice": 4300,
}
