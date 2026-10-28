"""根据扫描数据推荐：用哪个矿头、功率开多少、贴哪个手持工具。

破碎公式（用户定）：最大可破质量 = 矿头功率 × 模组功率 × (1 − 抗性) × 5
    所需功率   = 0.2 × 质量
    实际输出   = 最大功率 × 模组功率倍率 × (1 − 原矿抗性 × 抗性倍率)
    功率比     = 实际输出 ÷ 所需功率   ≥115% 余量充足，70–114% 需贴工具，<70% 需多人
    各项修正（矿头 / 模组 / 工具）按 (1 + 修正%) 连乘（SCMiner 配置器、grimhex 一致）
    多个矿头同时打 → 实际输出相加（grimhex、AO Gaming 一致）
    自造的矿头：最大 / 最小功率再乘品质倍数（发射器 × 汇流排，见下面「自造矿头」）
"""
import csv
import math
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import combinations

from . import data
from .data import (HEADS, MODULES, GADGETS, SHIPS, DEFAULT_LOADOUTS, DEFAULT_SHIP,
                   BREAK_MODELS, DEFAULT_MODEL, SOLO_RATIO, GADGET_RATIO)


def active_model():
    """返回 (模型名, K)。默认用用户公式；只有打开 AUTO_CALIBRATE 才会改用实测拟合值"""
    default = BREAK_MODELS[DEFAULT_MODEL]
    if data.AUTO_CALIBRATE:
        k = calibrated_k(default)
        if k:
            return "calibrated", k
    return DEFAULT_MODEL, default

# 难度 = 原矿不稳定性 × 不稳定倍率 ÷ 窗口倍率。超过这个值就优先考虑贴稳定类工具。
# TODO 需要用你实际扫到的数值校准
DIFFICULTY_LIMIT = 50.0


def _mult(*mods):
    out = 1.0
    for m in mods:
        out *= 1 + (m or 0) / 100
    return out


# ---------------------------------------------------------------- 自造矿头（1.6.41）
# 矿头都能用蓝图造：框架（铁）只影响耐久；发射器（萨达瑞晶）和汇流排（铜）的品质决定激光功率，
# 每个槽 品质 0 → ×0.8、1000 → ×1.2（线性，数据：scmdb 4.10.2 蓝图），两个槽相乘；品质 500 = ×1 = 商店买的。
# 激光功率在蓝图数据里和武器共用「Impact Force」这个属性名（游戏里采矿激光改叫 Laser Power）。
POWER_PROP = "Impact Force"
STANDARD_Q = 500


@lru_cache(maxsize=None)
def head_blueprint(key):
    """矿头的制造蓝图；没有蓝图（或制造数据读不到）返回 None"""
    h = HEADS.get(key)
    if not h:
        return None
    try:
        from ..crafting.crafting import blueprints
        bps = [b for b in blueprints() if b.get("t") == "mininglaser"]
    except Exception:
        return None
    name, size = h["name"].lower(), f"size{h['size']}"
    return next((b for b in bps if b.get("s") == size and b["n"].lower() in (name, f"{name} mining laser")), None)


@lru_cache(maxsize=None)
def craft_slots(key):
    """自造时影响激光功率的材料槽：({slot, slot_zh, mat, mat_zh, segs}, …)"""
    bp = head_blueprint(key)
    if not bp:
        return ()
    from ..crafting.crafting import group_mods, slot_zh, material_zh
    out = []
    for slot, opts, mods in bp["slots"]:
        segs = group_mods(mods).get(POWER_PROP)
        if segs:
            mat = next((o[1] for o in opts), "")
            out.append({"slot": slot, "slot_zh": slot_zh(slot), "mat": mat, "mat_zh": material_zh(mat), "segs": tuple(segs)})
    return tuple(out)


def _quality(v, default=STANDARD_Q):
    try:
        return max(0, min(1000, int(round(float(v)))))
    except (TypeError, ValueError):
        return default


def clean_craft(key, craft):
    """自造设置整理成合法的：{槽名: 品质 0~1000}，每个影响功率的槽都有，没填的按 500（和商店买的一样）；
    商店买的（None）/ 这个矿头没有蓝图 → None"""
    slots = craft_slots(key)
    if not isinstance(craft, dict) or not slots:
        return None
    return {s["slot"]: _quality(craft.get(s["slot"])) for s in slots}


def craft_mult(key, craft):
    """激光功率倍数：各槽按品质查曲线，加成相加（商店买的 = 1）。1.6.47 起相加（以前相乘）：
    数据里没有合并规则，按游戏制造终端、SCM、Crafter 三处一致的「各槽百分比相加」"""
    if not craft:
        return 1.0
    from ..crafting.crafting import curve_value
    out = 1.0
    for s in craft_slots(key):
        out += curve_value(list(s["segs"]), _quality(craft.get(s["slot"]))) - 1
    return out


@dataclass
class HeadSetup:
    key: str
    modules: list
    craft: dict | None = None      # 自造的：{槽名: 品质}；商店买的 None

    @property
    def head(self):
        return HEADS[self.key]

    @property
    def name(self):
        return self.head["name"]

    def power_mult(self):
        return craft_mult(self.key, self.craft)

    @property
    def label(self):
        """方案、悬浮窗里显示的名字（「中文 English」）：自造的后面标功率变化，比如「螺旋 Helix II（自造 +41%）」"""
        from ..core.i18n import gear_label
        if not self.craft:
            return gear_label(self.name)
        return f"{gear_label(self.name)}（自造 {(self.power_mult() - 1) * 100:+.0f}%）"

    def max_power(self):
        return self.head["pmax"] * self.power_mult() * _mult(*(MODULES[m].get("power") for m in self.modules))

    def min_power(self):
        return self.head["pmin"] * self.power_mult() * _mult(*(MODULES[m].get("power") for m in self.modules))

    def res_mods(self):
        return [MODULES[m].get("res") for m in self.modules]

    def instab_mult(self):
        return _mult(self.head["instab"], *(MODULES[m].get("instab") for m in self.modules))

    def window_mult(self):
        return _mult(self.head["window"], *(MODULES[m].get("window") for m in self.modules))

    def rate_mult(self):
        return _mult(self.head["rate"], *(MODULES[m].get("rate") for m in self.modules))


@dataclass
class Plan:
    heads: list            # [HeadSetup]
    gadget: str | None
    mass: float
    k: float               # 当前采用的常数
    model: str             # 当前采用的模型名
    delivered: float       # 满功率实际输出 W
    eff_resistance: list   # 每个矿头的有效抗性
    difficulty: float
    window_mult: float
    rate_mult: float

    @property
    def threshold(self):
        return self.k * self.mass

    def ratio_for(self, k):
        return self.delivered / (k * self.mass) if self.mass else float("inf")

    @property
    def ratio(self):
        return self.ratio_for(self.k)

    @property
    def max_mass(self):
        """满功率最多能破多重：矿头功率 × 模组功率 × (1 − 抗性) ÷ K（K=0.2 即 ×5）"""
        return self.delivered / self.k

    def others(self):
        """其他模型下的功率比，用来对照"""
        return {name: self.ratio_for(k) for name, k in BREAK_MODELS.items() if name != self.model}

    @property
    def breakable(self):
        return self.ratio >= 1.0

    @property
    def comfortable(self):
        return self.ratio >= SOLO_RATIO

    @property
    def throttle(self):
        """建议功率：刚好够破的比例向上取整到 5%，且不低于矿头最小功率"""
        need = 1 / self.ratio if self.ratio else float("inf")
        floor = max(h.min_power() / h.max_power() for h in self.heads)
        return min(1.0, max(math.ceil(need * 20) / 20, floor))

    @property
    def names(self) -> str:
        """「螺旋 Helix II（自造 +41%） + 霍夫斯泰德 Hofstede-S2」"""
        return " + ".join(h.label for h in self.heads)

    def short(self) -> str:
        """悬浮窗用的一行"""
        names = self.names
        g = f"｜使用{gadget_label(self.gadget)}" if self.gadget else ""
        if not self.breakable:
            return f"{names}{g}｜满功率也破不开"
        return f"{names}｜功率 {self.throttle*100:.0f}%{g}"

    def summary(self) -> str:
        names = self.names
        g = gadget_label(self.gadget) if self.gadget else "不使用"
        head = (f"{names}｜手持工具：{g}｜最大可破 {self.max_mass:,.0f} kg"
                f"｜功率比 {self.ratio*100:.0f}%")
        cmp = ""
        if not self.breakable:
            return (f"{head}｜满功率也破不开（需要 {self.threshold:,.0f} W，"
                    f"最多 {self.delivered:,.0f} W）{cmp}")
        tag = "" if self.comfortable else "｜余量偏紧"
        return f"{head}｜功率开到 {self.throttle*100:.0f}%｜难度 {self.difficulty:.1f}{tag}{cmp}"


def verdict(ratio: float) -> str:
    """SCMiner 的单激光判定档位"""
    if ratio >= SOLO_RATIO:
        return "单人可破"
    if ratio >= GADGET_RATIO:
        return "需要贴工具"
    return "需要多人"


def clean_loadout(ship, lo):
    """把配置整理成合法的：矿头尺寸对得上船、模组数量不超过槽数、魔像只能用 Pitman、人数在范围内"""
    spec = SHIPS[ship]
    default = DEFAULT_LOADOUTS[ship]
    heads = []
    raw = (lo or {}).get("heads") or default["heads"]
    for i in range(spec["heads"]):
        key, mods = (raw[i] if i < len(raw) else default["heads"][min(i, len(default["heads"]) - 1)])
        if spec.get("fixed"):
            key = spec["fixed"]
        h = HEADS.get(key)
        if not h or h["size"] != spec["size"] or (h.get("ship") and h["ship"] != ship):
            key = default["heads"][min(i, len(default["heads"]) - 1)][0]
            h = HEADS[key]
        mods = [m for m in (mods or []) if m in MODULES][:h["slots"]]
        heads.append([key, mods])
    crew = int((lo or {}).get("crew") or default["crew"])
    out = {"heads": heads, "crew": max(1, min(crew, spec["crew_max"], spec["heads"]))}
    raw_craft = (lo or {}).get("craft") or []
    craft = [clean_craft(key, raw_craft[i] if i < len(raw_craft) else None) for i, (key, _) in enumerate(heads)]
    if any(craft):                 # 有自造的矿头才记（老配置、出厂配置都没有这一项）
        out["craft"] = craft
    return out


def gadget_label(key):
    """手持工具「萨比尔 Sabir」"""
    from ..core.i18n import gear_label
    return gear_label(GADGETS[key]["name"])


def chosen_ship():
    """用户选过的船；还没选过返回 None"""
    from ..core import settings
    ship = settings.load().get("mining_ship")
    return ship if ship in SHIPS else None


def current_ship():
    return chosen_ship() or DEFAULT_SHIP


def ship_loadout(ship=None):
    """(船, 整理好的配置)：用户改过就用改过的，没改过用默认"""
    from ..core import settings
    ship = ship if ship in SHIPS else current_ship()
    saved = (settings.load().get("mining_loadouts") or {}).get(ship)
    return ship, clean_loadout(ship, saved)


def loadout():
    _, lo = ship_loadout()
    craft = lo.get("craft") or [None] * len(lo["heads"])
    return [HeadSetup(k, mods, craft[i]) for i, (k, mods) in enumerate(lo["heads"])]


def max_active_heads():
    return ship_loadout()[1]["crew"]


def evaluate(heads, gadget, mass, resistance_pct, instability, k=None, model=None):
    """resistance_pct：扫描显示的抗性百分比（如 35 表示 35%）；k 不给就用当前模型"""
    if k is None:
        model, k = active_model()
    r = resistance_pct / 100
    g = GADGETS.get(gadget, {}) if gadget else {}
    delivered, effs = 0.0, []
    for h in heads:
        head_res = h.head["res"] if data.APPLY_HEAD_RES else 0
        eff_r = min(max(r * _mult(head_res, *h.res_mods(), g.get("res")), 0.0), 0.99)
        effs.append(eff_r)
        delivered += h.max_power() * (1 - eff_r)

    # 多矿头时取各矿头不稳定/窗口倍率的平均
    instab = sum(h.instab_mult() * _mult(g.get("instab")) for h in heads) / len(heads)
    window = sum(h.window_mult() * _mult(g.get("window")) for h in heads) / len(heads)
    rate = sum(h.rate_mult() * _mult(g.get("rate")) for h in heads) / len(heads)
    difficulty = instability * instab / window
    return Plan(heads, gadget, mass, k, model or "custom", delivered, effs, difficulty, window, rate)


def _rank(p: Plan):
    if not p.breakable:          # 都破不开时，把最接近的排前面
        return (1, -p.ratio)
    return (
        0,
        p.difficulty > DIFFICULTY_LIMIT,
        not p.comfortable,           # 先保证功率比 ≥115%
        len(p.heads),                # 再尽量一个人打
        p.gadget is not None,        # 再尽量不贴工具
        p.difficulty,
    )


def recommend(mass, resistance_pct, instability, top=3):
    setups = loadout()
    model, k = active_model()
    plans = []
    for n in range(1, max_active_heads() + 1):
        for combo in combinations(setups, n):
            for gadget in [None, *GADGETS]:
                plans.append(evaluate(list(combo), gadget, mass, resistance_pct, instability,
                                      k=k, model=model))
    plans.sort(key=_rank)
    return plans[:top]


# ---------------------------------------------------------------- 用实测结果校准 K
# 用游戏内实测结果校准破碎常数 K（所需功率 = K × 质量）
# 
# 每次破石头后记一条：质量、抗性、用了哪些矿头/工具、功率开到多少、破没破开。
# - 破开了：K ≤ 实际输出 × 功率 ÷ 质量（上限）
# - 满功率没破开：K > 实际输出 ÷ 质量（下限）
# 取所有上限中最小、下限中最大，中点就是校准值。记录存在本地 observations.csv。

from ..core.paths import USER as _USER
LOG = _USER / "observations.csv"
FIELDS = ["mass", "resistance", "heads", "gadget", "throttle", "broke", "game_forecast"]
MIN_OBS = 3  # 至少几条记录才启用校准值


def record(mass, resistance, heads, gadget, throttle, broke, game_forecast=""):
    """heads 用逗号分隔的 key，如 "helix_ii,hofstede_s2"；throttle 为 0~1"""
    new = not LOG.exists()
    with open(LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(dict(mass=mass, resistance=resistance, heads=heads, gadget=gadget or "",
                        throttle=throttle, broke=int(bool(broke)), game_forecast=game_forecast))


def _rows():
    if not LOG.exists():
        return []
    with open(LOG, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def bounds():
    """返回 (下限, 上限, 记录数)，没有对应约束时为 None"""
    setups = {s.key: s for s in loadout()}
    lo, hi, n = None, None, 0
    for r in _rows():
        # 记录里的矿头现在的配置里没有（比如换了船）：按不带模组的矿头算，记录不白费
        heads = [setups.get(k) or HeadSetup(k, []) for k in r["heads"].split(",") if k in setups or k in HEADS]
        if not heads:
            continue
        p = evaluate(heads, r["gadget"] or None, float(r["mass"]), float(r["resistance"]), 0, k=1.0)
        delivered_per_kg = p.delivered / float(r["mass"])
        n += 1
        if r["broke"] == "1":
            k_max = delivered_per_kg * float(r["throttle"])
            hi = k_max if hi is None else min(hi, k_max)
        elif float(r["throttle"]) >= 0.99:
            lo = delivered_per_kg if lo is None else max(lo, delivered_per_kg)
    return lo, hi, n


def calibrated_k(default: float):
    """有足够且自洽的记录时返回校准后的 K，否则返回 None。
    只有单边约束时，在默认值和约束之间取保守的那个。"""
    lo, hi, n = bounds()
    if n < MIN_OBS or (lo is None and hi is None):
        return None
    if lo is not None and hi is not None:
        if lo > hi:  # 记录互相矛盾，先不用
            return None
        return (lo + hi) / 2
    if hi is not None:          # 只有成功记录：K 不会超过 hi
        return min(default, hi)
    return max(default, lo)     # 只有失败记录：K 至少是 lo
