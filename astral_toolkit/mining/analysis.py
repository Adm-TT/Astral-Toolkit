"""采矿结果计算（运行结构 RT-B1 / RT-B2，架构稿 §10.2 第 1、2 步）：一块石头的读数 + 输入 → 不可变结果。

只做计算：本模块不 import 线程 / 时钟 / 文件 / 设置 / 数据库 / UI，也不 import 读全局表的 laser / data / refinery。
外部事实由 tasks/mining.py 在一轮开始时取好，作为值从 MiningInputs 进来。排版在 app/presenters/mining.py。"""

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any

from .quality import tier_of

INERT = "Inert Materials"


class Rank(Enum):
    """同一种矿有几种品质时，这一份排第几"""

    HIGH = "high"
    MID = "mid"
    LOW = "low"


def freeze(value):
    """dict / list 递归变成只读的 MappingProxyType / tuple，顺带和原对象断开"""
    if isinstance(value, Mapping):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    return value


@dataclass(frozen=True)
class MiningInputs:
    """一轮计算用到的全部外部东西，开始计算前取好。三类：

    值：取输入那一刻的快照，之后全局表、设置、目标变了也不影响这一轮。
    纯函数（mineral_zh / method_zh / station_zh / gadget_label / goal_text）：同输入同输出，不读设置、用户文件、数据库、
      可变全局。翻译函数第一次调用时读程序自带的只读对照表 sc_glossary.json（lru_cache，运行期不变）。
    算法（refined_plan / refined_scu / recommend）：analyze 调用时显式传 prices / refineries / loadout，
      之后只再读 data.py 的常量表（精炼方式、矿头、模组、工具）和自造矿头功率曲线的缓存
      （laser.craft_slots，来自蓝图，更新数据时清；曲线放进配装事实归后续批次，见 RT-B2 PR）。"""

    at: str  # 显示用的时间
    mineral_zh: Callable[[str], str]
    method_zh: Callable[[str], str]
    station_zh: Callable[[str], str]
    gadget_label: Callable[[str], str]
    goal_text: Callable[..., str]
    prices: Mapping  # 矿 → (最高收购价, 城市)；没有的矿算不收
    refineries: Mapping  # 精炼站 → (星系, {矿: 加成 %})
    loadout: Any  # 配装事实（laser.LoadoutFacts），原样传给 recommend
    refined_plan: Callable[..., list]
    refined_scu: Callable[..., dict]
    recommend: Callable[..., list]  # (质量, 抗性, 不稳定性, loadout=) → 排好的方案
    craft_hints: tuple  # 这块石头的制造提示
    craft_mats: tuple  # ((矿, 蓝图统计), …)，只有蓝图用得到的矿
    goal_targets: tuple  # ((矿, 目标缺口), …)，只有目标还缺的矿
    goals_complete: (
        bool  # 目标查询没有中途出错（出错时 goal_targets 只有前几条，悬浮窗不写目标行）
    )


@dataclass(frozen=True)
class RefineOption:
    method_zh: str
    station_zh: str
    value: float
    scu: float
    fee: float
    hours: float
    bonus: str
    yields: tuple  # ((矿中文名, 精炼后 SCU), …)，只有产出大于 0 的


@dataclass(frozen=True)
class PlanFacts:
    heads: str
    short: str
    summary: str
    ratio: float
    breakable: bool
    comfortable: bool
    throttle: float | None  # 破不开时 None
    gadget_label: str  # 不贴工具时空


@dataclass(frozen=True)
class HighLot:
    """同一种矿有几种品质时，品质最高的那份"""

    zh: str
    q: Any
    scu: float | None
    low_q: Any  # 同种矿最低品质那份的品质


@dataclass(frozen=True)
class CompSub:
    q: Any  # 没认出来 None
    pct: float
    high: bool


@dataclass(frozen=True)
class CompGroup:
    zh: str | None  # 惰性物质 None
    inert: bool
    pct: float
    subs: tuple  # (CompSub, …)，品质从高到低，没认出来的排最后


@dataclass(frozen=True)
class MiningResult:
    rock: str
    mass: Any
    resistance: Any
    instability: Any
    difficulty: str
    total_scu: Any
    cut: bool
    at: str
    minerals: tuple  # ((中文名, 英文名, SCU), …)
    refine: tuple  # (RefineOption, …)
    sell: tuple  # ((矿中文名, 收购城市或 None), …)
    lots: tuple  # 成分表每一份，见 lots()
    inert_pct: float | None  # 惰性物质占比；不到 0.5% 不值得提，为 None
    high_lots: tuple  # (HighLot, …)
    composition: (
        tuple  # (CompGroup, …)，同一种矿合在一起，惰性物质排最后、其余占比大的在前
    )
    lot_refined: tuple  # 和 lots 一一对应：这一份精炼后的 SCU（未取整），没算的 None
    craft: tuple
    craft_mats: tuple
    goals: tuple
    goal_lines: (
        tuple  # 悬浮窗要写的目标行；目标查询中途出错时为空（goals 里可能已有前几条）
    )
    plans: tuple  # (PlanFacts, …)


def minerals_of(scan):
    """这块石头里算钱的矿：{矿: SCU}。没有总 SCU 时为空"""
    return {k: v for k, v in scan.minerals_scu().items() if k not in (INERT, "?")}


def best_quality(composition):
    """每种矿的最高品质：{矿: 品质}，品质都没认出来时为 None"""
    best = {}
    for nm, pct, qq in composition:
        if nm and nm not in (INERT, "?"):
            best[nm] = (
                max(best.get(nm) or 0, qq or 0) if qq is not None else best.get(nm)
            )
    return best


def _price(mineral, inputs: MiningInputs):
    return inputs.prices.get(mineral, (0, None))


def station_bonus(station, minerals, inputs: MiningInputs):
    """精炼站对这块石头里的矿的加成：只有一种值钱的矿写「+3%」，几种不一样就写「铁 +3%、金 -2%」，都是 0 返回空"""
    bonus = inputs.refineries.get(station, ("", {}))[1]
    worth = sorted(minerals, key=lambda m: -(minerals[m] * (_price(m, inputs)[0] or 0)))
    worth = [m for m in worth if (_price(m, inputs)[0] or 0) > 0] or worth
    vals = {m: bonus.get(m, 0) for m in worth}
    if not any(vals.values()):
        return ""
    if len(set(vals.values())) == 1:
        return f"{next(iter(vals.values())):+g}%"  # :+g：UEX 给小数加成时 :+d 会抛错、连崩 3 次关掉采矿助手
    return "、".join(f"{inputs.mineral_zh(m)} {v:+g}%" for m, v in vals.items() if v)


def lots(scan, plan, inputs: MiningInputs):
    """成分表（1.6.42）：石头里的每一份（矿 × 品质、惰性物质）一行。同一种矿有几种品质时标 rank（Rank）；
    tier 是这种矿的第几档（quality.py，4.8 起每种矿只有 7 档）：tier_of 的结果，没有时 None。plan = (精炼方式, 站点)：
    按它算这一份精炼后多少。精炼保留品质、不同品质精炼完还是分开的两份（expcarry、scopique、The Impound），所以按份算。
    返回 (每一份的只读字典, 每一份精炼后 SCU 的未取整值)；惰性物质 zh 为 None。给玩家看的文字由呈现层写"""
    total = scan.total_scu
    groups = defaultdict(list)
    for i, (n, p, q) in enumerate(scan.composition):
        if n and n != INERT:
            groups[n].append(i)
    rank = {}
    for n, idx in groups.items():
        qs = [scan.composition[i][2] for i in idx]
        if len(idx) < 2 or None in qs or len(set(qs)) < 2:
            continue
        order = sorted(idx, key=lambda i: scan.composition[i][2])
        for k, i in enumerate(order):
            rank[i] = (
                Rank.LOW if k == 0 else Rank.HIGH if k == len(order) - 1 else Rank.MID
            )
    rows, amounts = [], []
    for i, (n, p, q) in enumerate(scan.composition):
        inert = n == INERT
        scu = total * p / 100 if total else None
        row = {
            "en": n or "",
            "zh": None if inert else (inputs.mineral_zh(n) if n else "?"),
            "pct": p,
            "scu": round(scu, 4) if scu is not None else None,
            "q": None if inert else q,
            "tier": None,
            "rank": rank.get(i),
            "inert": inert,
            "refined": None,
        }
        t = tier_of(n, q) if (n and not inert and q is not None) else None
        if t:
            row["tier"] = tuple(t[:3])
        v = None
        if not inert and plan and scu is not None and n:
            v = inputs.refined_scu(
                {n: scu}, plan[1], plan[0], refineries=inputs.refineries
            ).get(n, 0.0)
            row["refined"] = round(v, 6)
        rows.append(MappingProxyType(row))
        amounts.append(v)
    return tuple(rows), tuple(amounts)


def inert_share(lot_rows):
    """惰性物质占比；不到 0.5% 返回 None"""
    inert = sum(r["pct"] for r in lot_rows if r["inert"])
    return inert if inert >= 0.5 else None


def high_lots(lot_rows):
    """同一种矿有几种品质时每种矿最高品质那份，配上最低品质"""
    out = []
    for r in lot_rows:
        if r["rank"] is Rank.HIGH:
            low = [
                x["q"] for x in lot_rows if x["en"] == r["en"] and x["rank"] is Rank.LOW
            ]
            out.append(HighLot(r["zh"], r["q"], r["scu"], low[0] if low else None))
    return tuple(out)


def composition(lot_rows):
    """矿物组成：同一种矿合在一起，占比相加"""
    groups = {}
    for row in lot_rows:
        g = groups.setdefault(
            None if row["inert"] else row["zh"],
            {"inert": row["inert"], "pct": 0.0, "subs": []},
        )
        g["pct"] += row["pct"] or 0
        if not row["inert"]:
            g["subs"].append(
                CompSub(row["q"], row["pct"] or 0, row["rank"] is Rank.HIGH)
            )
    out = [
        CompGroup(
            zh,
            g["inert"],
            g["pct"],
            tuple(
                sorted(
                    g["subs"],
                    key=lambda x: -int(x.q) if str(x.q).isdigit() else 1,
                )
            ),
        )
        for zh, g in groups.items()
    ]
    # 按显示的两位小数比大小：占比相加有浮点误差，显示一样的不能因为误差换了顺序
    return tuple(sorted(out, key=lambda g: (g.inert, -round(g.pct, 2))))


def _craft_and_goals(scan, lot_rows, inputs: MiningInputs):
    """可制造矿和目标缺口：(可制造矿, 目标, 悬浮窗目标行)。目标没查全或写文字出错就停在那里，已算出的留着。
    inputs 只对应取它的那块 scan：craft_mats 里的矿要在这块石头里找得到品质"""
    mineral_zh = inputs.mineral_zh
    best = best_quality(scan.composition)
    mats = tuple(
        freeze({"en": nm, "zh": mineral_zh(nm), "q": best[nm], **summary})
        for nm, summary in inputs.craft_mats
    )
    goals, lines = [], ()
    try:
        for nm, g in inputs.goal_targets:  # 有品质门槛的按每一份判断
            qq = best[nm]
            mine = [r for r in lot_rows if r["en"] == nm]
            ok = (
                any((r["q"] or 0) >= g["minq"] for r in mine) if g["minq"] > 1 else True
            )
            goals.append(
                freeze(
                    {
                        "en": nm,
                        "zh": g["zh"] or mineral_zh(nm),
                        "short": g["short"],
                        "unit": g["unit"],
                        "minq": g["minq"],
                        "q": qq,
                        "ok": ok,
                        "goals": g["goals"],
                        "text": inputs.goal_text(g, qq, mine),
                    }
                )
            )
        if inputs.goals_complete:
            lines = tuple(x["text"] for x in goals[:2])
    except Exception:
        pass
    return mats, tuple(goals), lines


def plan_facts(p, gadget_label):
    """破碎方案（laser.Plan）→ 结果里存的只读事实"""
    return PlanFacts(
        heads=p.names,
        short=p.short(),
        summary=p.summary(),
        ratio=p.ratio,
        breakable=p.breakable,
        comfortable=p.comfortable,
        throttle=p.throttle if p.breakable else None,
        gadget_label=gadget_label(p.gadget) if p.gadget else "",
    )


def analyze(scan, inputs: MiningInputs, cut=False) -> MiningResult:
    """一块石头的计算结果。cut=True：面板被屏幕右边挡住，品质和总 SCU 读不到，只有破碎方案和成分占比。
    inputs 只对应取它的那块 scan，不能拿去算别的石头"""
    mineral_zh = inputs.mineral_zh
    rock = mineral_zh(scan.main_mineral) if scan.main_mineral else "?"
    minerals = minerals_of(scan)
    refine, sell, first = [], (), None
    if minerals:
        for i, (method, station, value, rscu, fee, hours) in enumerate(
            inputs.refined_plan(
                minerals, prices=inputs.prices, refineries=inputs.refineries
            )
        ):
            bonus = station_bonus(station, minerals, inputs)
            per = inputs.refined_scu(
                minerals, station, method, refineries=inputs.refineries
            )
            refine.append(
                RefineOption(
                    method_zh=inputs.method_zh(method),
                    station_zh=inputs.station_zh(station),
                    value=value,
                    scu=rscu,
                    fee=fee,
                    hours=hours,
                    bonus=bonus,
                    yields=tuple((mineral_zh(k), v) for k, v in per.items() if v > 0),
                )
            )
            if i == 0:
                first = (method, station)
        sell = tuple((mineral_zh(k), _price(k, inputs)[1]) for k in minerals)
    lot_rows, lot_refined = lots(scan, first, inputs)
    craft, mats, goals, goal_lines = (), (), (), ()
    if minerals:
        craft = inputs.craft_hints
        mats, goals, goal_lines = _craft_and_goals(scan, lot_rows, inputs)
    plans = inputs.recommend(
        scan.mass, scan.resistance, scan.instability, loadout=inputs.loadout
    )
    return MiningResult(
        rock=rock,
        mass=scan.mass,
        resistance=scan.resistance,
        instability=scan.instability,
        difficulty=scan.difficulty or "",
        total_scu=scan.total_scu,
        cut=bool(cut),
        at=inputs.at,
        minerals=tuple((mineral_zh(k), k, v) for k, v in minerals.items()),
        refine=tuple(refine),
        sell=sell,
        lots=lot_rows,
        inert_pct=inert_share(lot_rows),
        high_lots=high_lots(lot_rows),
        composition=composition(lot_rows),
        lot_refined=lot_refined,
        craft=craft,
        craft_mats=mats,
        goals=goals,
        goal_lines=goal_lines,
        plans=tuple(plan_facts(p, inputs.gadget_label) for p in plans),
    )
