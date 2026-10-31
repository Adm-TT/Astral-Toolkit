"""把 OCR 识别出的文字行解析成扫描数据 / 矿袋数据

HUD 字很小，OCR 常见毛病：标签字认不出、"%" 被认成 "96" / "16"、个别数字认错。
所以解析不完全依赖标签：
- 质量 / 抗性 / 不稳定性：优先按标签；标签认不出时，按面板固定顺序（标题之后、"组成"之前的
  三个数字依次是质量、抗性、不稳定性）
- 成分行：百分比固定两位小数，后面跟的 "96" 之类当成 "%" 处理

OCR 输入格式：[(文字, (x, y), 字高), ...]
"""

import re
from dataclasses import dataclass, field

from ..core.i18n import mineral_en

NUM = r"(\d[\d,]*(?:[.,]\d+)?)"
PCT = r"(\d{1,3}[.,]\d{2})"  # 成分百分比：固定两位小数


def _num(s: str) -> float:
    s = s.strip()
    if re.fullmatch(r"\d+,\d{1,2}", s):  # "43,42" 逗号当小数点
        s = s.replace(",", ".")
    return float(s.replace(",", ""))


def _resistance(token: str):
    """抗性 0–100%。"69%" 可能被认成 "6996" / "6916" / "6946" / "69%6"，取开头合理的部分"""
    m = re.match(r"(\d{1,3})(?:[.,](\d+))?", token)
    if not m:
        return None
    if m.group(2):
        return float(f"{m.group(1)}.{m.group(2)}")
    digits = m.group(1)
    v = float(digits)
    if v <= 100 and "%" in token:
        return v
    for n in (2, 1, 3):  # 去掉被误认的 "%" 尾巴
        if (
            len(digits) > n
            and float(digits[:n]) <= 100
            and token[n : n + 2] in ("96", "16", "46", "%", "9", "%6", "1")
        ):
            return float(digits[:n])
    return v if v <= 100 else None


def rows(items, tol=0.6):
    """把文字框合并成行：两个框中心的 y 相差不超过平均字高 × tol 就算同一行"""
    if not items:
        return []
    items = sorted(items, key=lambda t: t[1][1])
    gap = sum(t[2] for t in items) / len(items) * tol
    groups = [[items[0]]]
    for it in items[1:]:
        if abs(it[1][1] - groups[-1][-1][1][1]) <= gap:
            groups[-1].append(it)
        else:
            groups.append([it])
    return [" ".join(t[0] for t in sorted(g, key=lambda t: t[1][0])) for g in groups]


@dataclass
class Scan:
    rock: str | None = None
    mass: float | None = None
    resistance: float | None = None
    instability: float | None = None
    total_scu: float | None = None
    composition: list = field(default_factory=list)  # [(英文名或 None, 百分比, 品质)]
    difficulty: str | None = (
        None  # 游戏自己的难度评级（按当前激光）：简单/中等/困难/极难/地狱
    )

    @property
    def main_mineral(self):
        """石头标题认不出时，用成分里占比最大的矿"""
        if self.rock:
            return self.rock
        best = max(
            ((p, n) for n, p, _ in self.composition if n and n != "Inert Materials"),
            default=None,
        )
        return best[1] if best else None

    @property
    def complete(self):
        return None not in (self.mass, self.resistance, self.instability)

    @property
    def valid(self):
        """自检：成分百分比加起来应接近 100%，质量、抗性在合理范围。读错的帧不会通过"""
        if not self.complete or not self.total_scu or not self.composition:
            return False
        total = sum(p for _, p, _ in self.composition)
        # 质量下限 1 kg（1.6.71）：地面上的小冰块、小铜矿只有几十到几百 kg（Golem / MOLE 实测 85、319、822），以前 ≥500 才算，这些都被当成读错
        # 质量和总 SCU 对得上（1.6.71）：实测每 SCU 140 kg（冰）到 1,800 kg（量子）；差得离谱的是质量被挡住 / 拼错了
        # （「质量 29」其实是被别的石头标记挡住，「822112.4」是 822 和旁边的 112.4m 拼在一起）
        ratio = self.mass / self.total_scu if self.total_scu else 0
        # 矿名、品质都没读出来的成分行（驾驶位转头看、面板斜着时行对不齐）：这一帧不算读全，免得显示一行「?」
        if any(
            not n and (q is None or not 100 <= q <= 1000)
            for n, _, q in self.composition
        ):
            return False
        # 矿（不是惰性物质）一定带品质。同一种矿两行品质可以一样（塔兰导电石 525、525，2026-10-18 截图），不能拿这个判错
        if any(
            q is None for n, _, q in self.composition if n and n != "Inert Materials"
        ):
            return False
        return (
            abs(total - 100) <= 2
            and self.mass >= 1
            and 0 <= self.resistance <= 100
            and 30 <= ratio <= 5000
        )

    def minerals_scu(self):
        out = {}
        if not self.total_scu:
            return out
        for name, pct, _ in self.composition:
            key = name or "?"
            out[key] = out.get(key, 0) + self.total_scu * pct / 100
        return out


DIFFICULTY = {
    "简单": "简单",
    "EASY": "简单",
    "中等": "中等",
    "MEDIUM": "中等",
    "困难": "困难",
    "HARD": "困难",
    "极难": "极难",
    "CHALLENG": "极难",
    "地狱": "地狱",
    "IMPOSS": "地狱",
}


def parse_scan(lines) -> Scan:
    s = Scan()
    in_comp = False
    pending = []  # 标签没认出来的数字，按顺序补给 质量→抗性→不稳定性
    for line in lines:
        # 1.6.71：同一行里挨着的距离标记（别的石头的「112.4m」「1.2km」）先去掉，不然「质量: 822」会拼成 822112.4
        line = _DIST.sub(" ", line)
        t = line.replace(" ", "").replace("：", ":")
        if not t:
            continue
        if not re.search(r"\d", t) and (
            d := next((v for k, v in DIFFICULTY.items() if k in t.upper()), None)
        ):
            s.difficulty = d
            continue
        if "/" in t or _CARGO.search(
            t
        ):  # 货舱那一行（「0.00/96.00 SCU」，斜杠没认出来也算），不属于扫描面板
            continue
        up = t.upper()
        if "SCU" in up or re.search(r"[5S][C0O]U", up):
            # 总 SCU 固定两位小数。小数点被切块识别拆成两块时行内是「7..84」的样子，先拼回来；
            # 小数点整个丢了（只剩整数，7.84 丢成 84）不采信——那种读数必错，宁可这帧无效
            # （2026-10-24 实测：「组成 (7.84 SCU)」被切成 "(7." ".84" "SCU)"，旧逻辑读出 84）。
            # 整数部分允许千分位（1,234.56）：只认三位的话上千会读成后三位 234.56（1.6.44）
            # 小石头的总量用毫 SCU 写：「599.29m SCU」= 0.59929 SCU（1.6.71，雪地小冰块）
            if mm := re.search(
                r"(\d{1,3}(?:,\d{3})*|\d+)[.,](\d{2})\s*M\s*[5S]?\s*[C0O]\s*U", up
            ):
                s.total_scu = (
                    float(f"{mm.group(1).replace(',', '')}.{mm.group(2)}") / 1000
                )
                in_comp = True
                continue
            m = (
                re.search(
                    r"(\d{1,3}(?:,\d{3})*|\d+)[.,](\d{2})\s*[5S]?\s*[C0O]\s*U", up
                )
                or re.search(r"(\d{1,3})[.,]\s*[.,](\d{2})\s*[5S]?\s*C\s*U", up)
                or (re.search(r"(\d{1,3})[.,](\d{2})\s*5CU", up) if "组" in t else None)
            )
            if m:
                if (
                    s.total_scu is None or "组" in t
                ):  # 先读到的「组成」那行为准，后面别的 SCU 不覆盖
                    s.total_scu = float(f"{m.group(1).replace(',', '')}.{m.group(2)}")
                in_comp = True
                continue
        if in_comp or re.match(PCT, t):
            if m := re.match(PCT + r"(%|96|9/6|%6)?(.*)$", t):
                rest = m.group(3)
                # 「组成」之前的数字行（标签缺失的质量「13,586」）也以「数字.两位小数」开头：
                # 不带 %、96 尾巴和矿名的，不当作成分行，落到下面的顺序补位
                # （2026-10-24：「13,586」被当成 13.58% 成分、质量读出 69）。
                # 「96」只认紧跟在百分比后面的（m.group(2)）：整行里有 96 就算的话，质量「13,596」又会被当成成分（1.6.43）
                if in_comp or m.group(2) or "%" in rest or re.search(r"[一-鿿]", rest):
                    rest = rest.rstrip(".,。，:：;")
                    q = re.search(r"(\d+)$", rest)
                    name_txt = _zh_name(rest[: q.start()] if q else rest)
                    quality = int(q.group(1)) if q else None
                    if "惰" in name_txt or "性物" in name_txt or "情性" in name_txt:
                        name = "Inert Materials"
                    else:
                        name = mineral_en(name_txt, prefer=s.rock) if name_txt else None
                        if name is None and (quality == 0 or "质" in name_txt[-2:]):
                            name = "Inert Materials"  # 惰性物质品质恒为 0
                    s.composition.append((name, _num(m.group(1)), quality))
                    continue
            if in_comp:
                # 「组成」那行之后读不懂的行照旧跳过，不拿去补质量 / 抗性 / 不稳定性（1.6.43）：
                # 成分区多出来的单独数字（品质「662」、行尾的「1」）以前会被当成不稳定性，把读不全的帧变成「有效」
                continue
        # 面板上半部分
        if (
            s.rock is None
            and s.mass is None
            and not re.search(r"\d", _zh_name(t))
            and not any(k in t for k in ("扫", "结", "组成"))
            and len(_zh_name(t)) >= 2
            and (rock := mineral_en(_zh_name(t)))
        ):
            s.rock = rock
            continue
        # 有标签就取标签后面的数字（勘探者驾驶舱里标签左边紧挨着别的 HUD 读数，比如 "0.0"）
        lab = re.search(r"质量?|量:|抗性?|不?稳定性?|定性", t)
        if not lab and s.mass is None and len(t) <= 2:
            continue  # 面板标题上面零碎的 "1"、")"：不是数值
        num = (
            re.search(r"\d[\d.,%]*", t[lab.end() :].translate(_DIGITISH))
            if lab
            else None
        )
        num = num or re.search(r"\d[\d.,%]*", t)
        if not num:
            continue
        token = num.group(0)
        if "质" in t or "量:" in t:
            s.mass = _num(re.match(NUM, token).group(1))
        elif "抗" in t:
            s.resistance = _resistance(token)
        elif "稳" in t or "定性" in t:
            s.instability = _num(re.match(NUM, token).group(1))
        else:
            pending.append(token)
    # "钨" 的金字旁在小字下常被认成 "金"：石头标题是钨矿时，成分里的"金矿"按钨处理
    if s.rock == "Tungsten":
        s.composition = [
            ("Tungsten" if n == "Gold" else n, p, q) for n, p, q in s.composition
        ]
    s.composition = _fix_by_tiers(s.composition, s.rock)
    names = {n for n, _, _ in s.composition if n and n != "Inert Materials"}
    if s.rock and names and s.rock not in names:
        s.rock = None  # 标题认成了成分里没有的矿：多半是旁边别的石头的标记（「铁原矿 139.6m」），不采信
    for token in pending:  # 标签缺失时按顺序补
        if s.mass is None:
            s.mass = _num(re.match(NUM, token).group(1))
        elif s.resistance is None:
            s.resistance = _resistance(token)
        elif s.instability is None:
            s.instability = _num(re.match(NUM, token).group(1))
    return s


_DIGITISH = str.maketrans(
    {"G": "6", "O": "0", "o": "0", "l": "1", "I": "1", "B": "8", "Z": "2"}
)  # 标签后面的数字里形近的字母（「抗性: G2%」）
_DIST = re.compile(
    r"(?<![\d.,])\d+(?:[.,]\d+)?\s*[kK]?[mM](?!\s*[5S][C0O]U)(?![A-Za-z])"
)
_CARGO = re.compile(r"\d[.,]\d{2}\D{0,2}\d{1,3}[.,]\d{2}[5S]?[C0O]U", re.I)


def _zh_name(txt):
    """矿名后面带的英文名去掉：游戏里有的标题写成「欧拉特烃OURATITE」（1.6.71，沙漠样本）"""
    out = re.sub(r"[A-Za-z][A-Za-z0-9]{2,}$", "", txt)
    return out if re.search(r"[一-鿿]", out) else txt


def _tiers(name):
    from .quality_tiers import TIERS

    return TIERS.get({"Ice": "Pressurized Ice"}.get(name, name))


def _fix_by_tiers(comp, rock):
    """4.8 起每种矿只有固定几档品质（quality_tiers.py）。用它：
    ①矿名没认出来、但品质只对得上这块石头里某一种矿的档位 → 补上矿名（「8.23% ??? 588」，同石头里只有艾格瑞有 588）；
    ②品质多认了一位（「5882」）、和这种矿某一档只差一个字 → 改成那一档"""
    from .quality_tiers import TIERS

    owners = lambda q: [
        m for m, ts in TIERS.items() if q in ts[:-1]
    ]  # 哪几种矿有这一档（1000 每种都有，不算）  # noqa: E731
    ice = lambda m: {"Pressurized Ice": "Ice"}.get(m, m)  # noqa: E731
    # 第一遍：有矿名的行，品质不在这种矿的档位里 → 改品质（差一个字）或改矿名（品质只有另一种矿有）
    named = []
    comp = [(n or None, p, q) for n, p, q in comp]  # 空字符串矿名当没认出
    for n, p, q in comp:
        if (
            q is not None
            and n
            and n != "Inert Materials"
            and (ts := _tiers(n))
            and q not in ts
        ):
            near = [t for t in ts if _one_edit(str(q), str(t))]
            own = owners(q)
            if len(own) == 1 and not near:
                # 品质正好是另一种矿独有的一档、和这种矿哪一档都不沾边：矿名认错了（锡认成金、钨认成砬兰石）
                n = ice(own[0])
            elif len(near) == 1 and not own:
                q = near[0]
            # 两种说法都说得通（铜 597：可能是铜 593 读错一位，也可能是别的矿）：不猜，按读到的原样显示，不改成别的矿
        named.append((n, p, q))
    # 第二遍：矿名没认出来的行，按品质档位补矿名
    present = {n for n, _, _ in named if n and n != "Inert Materials"} | (
        {rock} if rock else set()
    )
    has_inert = any(n == "Inert Materials" for n, _, _ in named)
    out = []
    for k, (n, p, q) in enumerate(named):
        if n is None and q is not None and q > 0:
            # 一块石头里同一种矿最多两份（高、低品质）：已经有两行的矿不再往上补（已经补过的行 + 后面本来就有名字的行）
            room = [
                m
                for m in present
                if sum(1 for x, _, _ in out + named[k + 1 :] if x == m) < 2
            ]
            cands = [m for m in room if q in (_tiers(m) or ())]
            count = lambda m: sum(1 for x, _, _ in out + named[k + 1 :] if x == m)  # noqa: E731
            if not cands:  # 这种石头本来会出的矿（解包的成分表）里只有一种有这一档：火神石石头只出火神石、石英、硅，510 → 硅
                can = [
                    m
                    for m in _rock_contains(rock)
                    if q in (_tiers(m) or ()) and count(m) < 2
                ]
                if len(can) == 1:
                    cands = can
            if not cands:  # 品质认错一位：石头里还有空位的矿，某一档只差一个字
                near = [
                    (m, t)
                    for m in room
                    for t in (_tiers(m) or ())
                    if _one_edit(str(q), str(t))
                ]
                if len(near) == 1:
                    cands, q = [near[0][0]], near[0][1]
            # 全游戏只有一种矿有这一档（钨 530）：知道这种石头会出哪些矿时，只认在里面的（独立审查 2026-10-27：
            # 不限的话「错一位」的读数会补成手采 / 车挖的矿）
            rc = _rock_contains(rock)
            if (
                not cands
                and len(owners(q)) == 1
                and count(ice(owners(q)[0])) < 2
                and (not rc or ice(owners(q)[0]) in rc)
            ):
                cands = [ice(owners(q)[0])]
            if len(cands) == 1:
                n = cands[0]
        elif n is None and q == 0 and not has_inert:
            n, has_inert = (
                "Inert Materials",
                True,
            )  # 品质读到 0、名字没认出：惰性物质那行（矿名品质都没读到的不猜，可能是漏读的值钱矿）
        out.append((n, p, q))
    return out


def _rock_contains(rock):
    """这种石头里会出的矿（data/mining_rocks.json 的 contains，解包成分表）；不知道返回空"""
    if not rock:
        return []
    try:
        from .mining_area import rocks_table

        return list((rocks_table().get("contains") or {}).get(rock) or [])
    except Exception:
        return []


def _one_edit(a, b):
    """两串数字只差一个字（多一位 / 少一位 / 错一位）"""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) < len(b):
        a, b = b, a
    return any(a[:i] + a[i + 1 :] == b for i in range(len(a)))


MOLE_CAPACITY = 96.0


def parse_bag(lines, capacity=MOLE_CAPACITY):
    """矿袋：返回 ({英文矿名: SCU}, 已用, 容量)。
    数量固定两位小数；"SCU" 常被认成 "5CU"，"96" 常被认成 "%"，容量认不出时用 MOLE 的 96"""
    bag, used, cap = {}, None, None
    for line in lines:
        t = line.replace(" ", "").upper()
        # 按原始空格分隔取数，避免把旁边的杂字粘成一个大数
        if (
            "/" not in line
            and "货舱" in t
            and len(two := re.findall(r"(?<![\d.,])\d{1,3}[.,]\d{2}(?![\d])", line))
            >= 2
        ):
            line = f"{two[0]} / {two[1]}"  # 勘探者的 "6.49 / 60.00 SCU" 斜杠常认不出来
        if "/" in line and (
            m := re.search(
                r"(?<![\d.,])(\d{1,3}[.,]\d{2})\s*/\s*(\d{1,3}(?:[.,]\d+)?)?", line
            )
        ):
            used = _num(m.group(1))
            cap = (
                _num(m.group(2))
                if m.group(2) and _num(m.group(2)) >= used
                else capacity
            )
            if abs(cap - capacity) <= max(
                2, capacity * 0.07
            ):  # "96" 常被认成 95/98：贴近船的容量就按船的容量
                cap = capacity
            continue
        if m := re.match(r"(.*?)(\d+[.,]\d{2})[S5]?C?U?$", t):
            name_txt = re.sub(r"[^\u4e00-\u9fff]", "", m.group(1))
            if not name_txt:
                continue
            if "惰" in name_txt or "性物" in name_txt or "情性" in name_txt:
                name = "Inert Materials"
            else:
                name = mineral_en(name_txt)
            if name:
                bag[name] = bag.get(name, 0) + _num(m.group(2))
    if used is not None:  # 单项不可能超过已用量，超过的是误读，丢掉
        bag = {k: v for k, v in bag.items() if v <= used + 0.01}
    return bag, used, cap
