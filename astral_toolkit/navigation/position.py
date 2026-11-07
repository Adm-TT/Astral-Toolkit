"""你现在大概在哪：不用打字，从游戏日志 Game.log 里取（打开个人/本地库存时游戏会记下地点）

- 打开某地的库存：「requested inventory for Location[Stanton4_NewBabbage]」→ 你在新巴贝奇
- 之后走动、开本地库存：「Update Inventory Location ... -> [编号]」，认识的编号就更新位置
位置换算成星系坐标（starmap.space 的星体/拉格朗日点数据），用来给商店按远近排序。
"""

import json
import math
from functools import lru_cache
import re
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INV = re.compile(r"^<([^>]+)>.*requested inventory for Location\[([^\]]+)\]")
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}
PLANET_CODE = {
    "ARC": "Stanton3",
    "HUR": "Stanton1",
    "CRU": "Stanton2",
    "MIC": "Stanton4",
}
JUMP = {
    "StantonPyro": "Stanton-Pyro Jump Point",
    "PyroStanton": "Pyro-Stanton Jump Point",
    "PyroNyx": "Pyro - Nyx Jump Point",
    "NyxPyro": "Jumppoint_Nyx_Pyro",
}


def find_point(name=None, internal=None):
    """星图里的点 {n,i,sys,t,x,y,z}：先按内部名（不分大小写），再按名字（小写去非字母数字）；同名取源里第一个"""
    from ..gamedata import starmap as gd_starmap

    if internal:
        p = gd_starmap.point_by_internal(internal)
        if p:
            return p
    if name:
        nl = re.sub(r"[^a-z0-9]", "", name.lower())
        p = gd_starmap.point_by_name(nl)
        if p:
            return p
        m = re.fullmatch(r"pyro(i{1,3}|iv|v|vi)", nl)
        if m:
            return find_point(internal=f"Pyro{ROMAN[m.group(1).upper()]}")
    return None


def shop_point(fields):
    """商店位置 → 星图点（卫星/拉格朗日点/行星）。目录迁移 Q2 从 crafting/shops 搬来：只用 find_point，本来就是星图这边的事"""
    system, planet, orbit, moon, station, city = (list(fields) + [""] * 6)[:6]
    if moon:
        p = find_point(name=moon)
        if p:
            return p
    m = re.search(r"Lagrange Point (\d)", orbit or "")
    if m and planet:
        base = find_point(name=planet)
        if base:
            iname = base["i"]
            pm = re.fullmatch(r"(?i)pyro(\d)", iname)
            # 斯坦顿的星球现在叫 OOC_Stanton_3_ArcCorp，它的拉格朗日点叫 OOC_Stanton3_L4：以前只按「星球内部名_L4」找，
            # 斯坦顿的拉格朗日站商店算远近时被放到了星球中心（2026-11-07 跟着斯坦顿地点一起修）
            sm = re.match(r"(?i)OOC_Stanton_(\d)_", iname)
            if pm:
                internal = f"P{pm.group(1)}_L{m.group(1)}"
            elif sm:
                internal = f"OOC_Stanton{sm.group(1)}_L{m.group(1)}"
            else:
                internal = f"{iname}_L{m.group(1)}"
            p = find_point(internal=internal)
            if p:
                return p
    for name in (planet, station, system and system + " Star"):
        if name:
            p = find_point(name=name)
            if p:
                return p
    return None


def from_code(code):
    """日志里的地点代码 → 星图点。
    斯坦顿的星图内部名改过：星球 / 卫星现在叫 OOC_Stanton_4_Microtech、OOC_Stanton_1b_Aberdeen，拉格朗日点叫
    OOC_Stanton1_L1；日志里还是旧代码（Stanton4_NewBabbage、RR_HUR_L1）。先按旧内部名找（老数据），找不到再按现在的
    叫法找——以前只按旧名找，斯坦顿全对不上：物品查询不按远近排、盘点认不出地点（2026-11-07 老大在新巴贝奇发现）"""
    m = re.match(r"RR_(ARC|HUR|CRU|MIC)_L(\d)", code)
    if m:
        old = f"{PLANET_CODE[m.group(1)]}_L{m.group(2)}"
        return find_point(internal=old) or find_point(internal="OOC_" + old)
    m = re.match(r"RR_P(\d)_L(\d)", code)
    if m:
        return find_point(internal=f"P{m.group(1)}_L{m.group(2)}")
    m = re.match(r"RR_JP_(\w+)", code)
    if m and m.group(1) in JUMP:
        return find_point(name=JUMP[m.group(1)])
    m = re.match(r"(Stanton\d[a-z]?|Pyro\d[a-z]?|Nyx\d?)", code, re.I)
    if m:
        return find_point(internal=m.group(1)) or _ooc_body(m.group(1))
    if code.startswith("Delamar") or "Levski" in code:
        return find_point(name="Delamar")
    return None


def _ooc_body(old):
    """旧的斯坦顿星球 / 卫星内部名（Stanton4、Stanton1b）→ 星图里现在叫 OOC_Stanton_4_Microtech 的那个点
    （卫星的编号带字母，不会认成星球）；不是斯坦顿、星图里没有给 None。给出去的是一份新的，调用方改了不碰缓存"""
    m = re.fullmatch(r"stanton(\d[a-z]?)", old, re.I)
    if not m:
        return None
    p = _ooc_bodies(_data_version()).get(m.group(1).lower())
    return dict(p) if p else None


@lru_cache(maxsize=1)
def _ooc_bodies(_version):
    """星图里 OOC_Stanton_<编号>_<名字> 的点按编号（4、1b）排成表，按库版本缓存、只留当前版本；同编号取源里第一个"""
    from ..gamedata import starmap as gd_starmap

    out = {}
    for p in gd_starmap.data_dict()["points"]:
        m = re.match(r"OOC_Stanton_(\d[a-z]?)_", p.get("i") or "", re.I)
        if m:
            out.setdefault(m.group(1).lower(), p)
    return out


def _place_zh(key="", prefix=None):
    """places_zh 里的中文（只看这一份，不看 places_extra_zh——以前就只读 places_zh.json）：key 精确查；
    prefix 取以它开头的最短键。查不到、游戏数据库不可用返回 None（以前读不到文件就是空表）"""
    from ..gamedata import GamedataError, places

    try:
        if prefix is not None:
            return places.zh_by_prefix(prefix)
        return places.zh_of(key)
    except GamedataError:
        return None


def _zh_name(name):
    k = re.sub(r"[^a-z0-9]", "", name.lower())
    return _place_zh(k) or _place_zh(re.sub(r"station$", "", k)) or name


def _station_at(internal):
    """星图内部点（P1_L2）上建的空间站名，没有返回空：查 _station_table"""
    try:
        table = _station_table(_data_version())
    except _ScanStopped as e:
        table = e.table
    return table.get(internal, "")


class _ScanStopped(Exception):
    """站名表扫到一半出错，带着出错前扫到的那部分（抛出去的 lru_cache 不缓存，下次重扫）"""

    def __init__(self, table):
        super().__init__()
        self.table = table


@lru_cache(maxsize=1)
def _station_table(_version):
    """星图内部点 → 建在这个点上的空间站名（没有站名用城市名），按库版本缓存、只留当前版本。
    以前每查一个点从头扫一遍商店表、每行都查星图库，全局搜索第一次要等 4 秒；现在整张表扫一遍，
    同样的位置只算一次星图点（几千行商店只有几十种位置）。同一个点有几行取源顺序第一行。
    中途出错：这次用出错前扫到的、后面的当没有（以前从头找，出错前找到的照返回，之后的返回空）；
    出错可能是一时的，不缓存、下次重扫"""
    table, seen = {}, {}
    try:
        from ..gamedata import shops as gd_shops

        for r in gd_shops.lagrange_rows():  # 轨道带 Lagrange、有站名的商店行
            f = r.fields
            key = tuple(f)
            if key not in seen:
                seen[key] = shop_point(f)
            p = seen[key]
            if p and p["i"] not in table:
                table[p["i"]] = f[4] or f[5]
    except Exception as e:
        raise _ScanStopped(table) from e
    return table


def place_name(code):
    """日志里的地点代码 → 具体地点的中文名：Stanton4_NewBabbage → 新巴贝奇，RR_ARC_L1 → 弧 L1 广袤森林站"""
    return _place_name(code, _data_version())


def _data_version():
    """缓存按游戏数据库版本分开：汉化包更新时 reset_names 在 updating() 里、库还没换代，
    这时别的线程查到的旧名记在旧版本下，换代后自然查新库"""
    from ..gamedata import GamedataError, version

    try:
        return version()
    except GamedataError:
        return None


@lru_cache(maxsize=256)
def _place_name(code, _version):
    m = re.match(r"RR_(ARC|HUR|CRU|MIC)_L(\d)", code)
    if m:
        return (
            ini_name(f"RR_{m.group(1)}_L{m.group(2)}")
            or _place_zh(prefix=f"{m.group(1).lower()}l{m.group(2)}")
            or f"{m.group(1)}-L{m.group(2)}"
        )
    m = re.match(r"RR_P(\d)(?:_L(\d))?", code)
    if m:
        # 派罗：汉化包里有每个站的正式名（RR_P1_L2 → 焰联-远程站-1-2，RR_P3 → 轨道讣闻站）；
        # 没有的再从商店数据里找建在这个点上的空间站；都没有就用汉化包里拉格朗日点本身的叫法（派1 PYR1 L1）
        k, l = m.group(1), m.group(2)  # noqa: E741
        hit = ini_name(f"RR_P{k}_L{l}" if l else f"RR_P{k}")
        if hit:
            return hit
        if l:
            station = _station_at(f"P{k}_L{l}")
            if station:
                return _zh_name(station)
            return ini_name(f"Pyro{k}_L{l}") or f"PYR{k}-L{l}"
        return ini_name(f"Pyro{k}") or f"PYR{k}"
    m = re.match(r"RR_JP_(\w+)", code)
    if m:
        name = JUMP.get(m.group(1), m.group(1))
        return _place_zh(re.sub(r"[^a-z0-9]", "", name.lower())) or name
    rest = code.split("_", 1)[1] if "_" in code else code
    hit = _place_zh(re.sub(r"[^a-z0-9]", "", rest.lower()))
    if hit:
        return hit
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", rest).replace("_", " ")


_LOOSE = [
    (
        re.compile(r"RR[\W_]*P[\W_]*(\d)[\W_]*L[\W_]*(\d)", re.I),
        lambda m: f"RR_P{m.group(1)}_L{m.group(2)}",
    ),
    (
        re.compile(r"RR[\W_]*P[\W_]*(\d)(?![\W_]*L)(?![\d])", re.I),
        lambda m: f"RR_P{m.group(1)}",
    ),  # 轨道讣闻站、废墟空间站
    (
        re.compile(r"RR[\W_]*(ARC|HUR|CRU|MIC)[\W_]*L[\W_]*(\d)", re.I),
        lambda m: f"RR_{m.group(1).upper()}_L{m.group(2)}",
    ),
]


_ini_cache = {}
BELT_ZH = {
    "keeger": "基格小行星带",
    "glaciem": "冰川环带",
}  # 汉化包的叫法（Nyx_Glaciem… → 冰川环带）


def ini_name(key):
    """汉化包（data/loc/global_zh.ini）里按代码查地名，只要中文那一段：
    「死局空间站 (Checkmate)」「派罗 I (Pyro I)」→ 去掉括号里的英文；「弧 L1 广袤森林站\\nARC-L1 …」→ 只要第一行"""
    if "ini" not in _ini_cache:
        table = {}
        try:
            from ..update.localization import read_ini

            table.update(
                {k.lower(): v.split("\\n")[0].strip() for k, v in read_ini().items()}
            )
        except Exception:
            pass
        _ini_cache["ini"] = table
    ini = _ini_cache["ini"]
    k = re.sub(r"\s+", "_", (key or "").strip()).lower()
    v = _ini_get(ini, k) or _ini_get(ini, k + ",p") or ""
    return re.sub(r"\s*[（(][^（）()]*[A-Za-z][^（）()]*[）)]\s*$", "", v).strip()


def _ini_get(ini, k):
    """汉化包里有就用汉化包的；没有再查随安装包带的地点代号表 place_codes_zh（新装还没下汉化包时也有中文名）。
    以前两份合成一张表、汉化包盖过代号表，查法等价；游戏数据库不可用时当作没有代号表"""
    if k in ini:
        return ini[k]
    from ..gamedata import GamedataError, places

    try:
        return places.code_zh(k)
    except GamedataError:
        return None


def reset_names():
    """汉化包更新后清掉地名缓存，这次运行里马上用上新地名"""
    _ini_cache.clear()
    _place_name.cache_clear()
    _station_table.cache_clear()
    _ooc_bodies.cache_clear()


def _ini_label(code):
    """汉化包里按地点代码直接查：AsteroidCluster_MiningBase_Stanton01_Medium_01 → 采矿基地 #IGB-FXW"""
    hit = ini_name(code)
    if hit:
        return hit
    key = re.sub(r"\s+", "_", code.strip()).lower()
    m = re.match(
        r"asteroidcluster_miningbase_([a-z]+)_([a-z]+)", key
    )  # 尼克斯这种没有逐个命名的采矿基地
    if m:
        sysname, belt = m.group(1), m.group(2)  # noqa: F841
        return f"采矿基地（{BELT_ZH.get(belt, belt.capitalize() + '小行星带')}）"
    return ""


def _body_label(code):
    """星图里星球的内部代号（Pyro5d、Stanton2b、nyx3）→ 中文名"""
    try:
        from . import navigate as n

        key = code.strip().lower()
        for p in n.load().get("points") or []:
            if (p.get("i") or "").lower() == key and p.get("t") in ("Planet", "Star"):
                return n.point_zh(p)
    except Exception:
        pass
    return ""


def display_label(location):
    """右上角「Current player location」那段 → 具体地点中文名。
    OCR 常把下划线认成空格、丢字（RR P2 L4 CLINIC(LZ:R P24)），先按宽松写法认拉格朗日点空间站：
    RR_P2_L4 → 死局空间站；其他地点用括号里的 LZ：(LZ: Stanton4 NewBabbage) → 新巴贝奇；
    再到汉化包里按代码直接查（2026-10-26，尼克斯的采矿基地这类）"""
    loc = location or ""
    main = re.sub(r"\s*\(.*$", "", loc).strip()
    for text in (main, loc):
        for pat, code in _LOOSE:
            m = pat.search(text)
            if m:
                return place_name(code(m))
    direct = _ini_label(main)
    if direct:
        return direct
    body = _body_label(main)  # 星球代号：Pyro5d → 法伊罗
    if body:
        return body
    m = re.search(
        r"\(\s*L\w*\s*:\s*([^)]+)\)?", loc
    )  # (LZ: Stanton4 NewBabbage) → 新巴贝奇
    if m:
        name = place_name(
            re.sub(r"\s+", "_", m.group(1).strip(), count=1).replace(" ", "")
        )
        if name:
            return name
    return main


_log_cache = {}
CHUNK = 4_000_000
QINV = re.compile(
    r"^<([^>]+)>.*<Query Inventory> Request\[\d+\] Inventory\[\d+:Location:(\d+)\]"
)
UPD = re.compile(
    r"^<([^>]+)>.*<Update Inventory Location>.*Location \[(\d+)\] -> \[(\d+)\]"
)


def _ids():
    """地点编号 → 地点代码（810966700 → RR_P2_L4）。开个人库存时日志里两个挨着出现，学到了就永久记住"""
    if "ids" not in _log_cache:
        try:
            from ..core.paths import USER

            _log_cache["ids"] = json.loads(
                (USER / "location_ids.json").read_text(encoding="utf-8")
            )
        except Exception:
            _log_cache["ids"] = {}
    return _log_cache["ids"]


def _save_ids():
    try:
        from ..core.paths import USER, write_json

        write_json(USER / "location_ids.json", _ids(), indent=1)
    except Exception:
        pass


class _LogState:
    """顺着日志读，记最后一次知道的地点。三种信号：
    - 开个人库存：requested inventory for Location[RR_P2_L4]（直接给地点代码）
    - 紧接着的 Query Inventory ...:Location:810966700 → 学到「810966700 就是 RR_P2_L4」
    - 开本地库存、走进别的区域时：Update Inventory Location ... Location [A] -> [B]，B 认识就更新位置；
      不认识（比如进了飞船）就保持原来的地点——除非退出游戏或死亡，玩家很少一下子跑很远"""

    def __init__(self):
        self.last = None  # (时间戳, 地点代码)
        self.pending = None  # 刚开库存的地点代码，等下一行告诉我们它的编号
        self.learned = False

    def feed(self, line):
        if "Inventory" not in line:
            return
        m = INV.match(line)
        if m:
            self.last = (_ts(m.group(1)), m.group(2))
            self.pending = m.group(2)
            return
        m = QINV.match(line)
        if m and self.pending:
            ids = _ids()
            if ids.get(m.group(2)) != self.pending:
                ids[m.group(2)] = self.pending
                self.learned = True
            self.pending = None
            return
        m = UPD.match(line)
        if m:
            code = _ids().get(m.group(3))
            if code:
                self.last = (_ts(m.group(1)), code)


def _read_forward(path, start, state):
    """从 start 往后读到最后一个完整行，返回读到哪（下次从这里接着读，不会把半行切断）"""
    with open(path, "rb") as f:
        f.seek(start)
        pos, rest = start, b""
        while True:
            block = f.read(CHUNK)
            if not block:
                break
            block = rest + block
            cut = block.rfind(b"\n")
            if cut < 0:
                rest = block
                continue
            for raw in block[:cut].split(b"\n"):
                if b"Inventory" in raw:
                    state.feed(raw.decode("utf-8", "replace").strip())
            pos += (
                cut + 1
            )  # pos = block 第一个字节（即上一轮剩下的 rest）在文件里的位置；以前多减了 len(rest)（审查 2026-10-31）
            rest = block[cut + 1 :]
    return pos


def _hit(last):
    if not last:
        return None
    t, code = last
    p = from_code(code)
    return (t, place_name(code) or _zh(p), p) if p else None


def from_log(path=None, tail=None):
    """游戏日志里你最近所在的地点：(时间戳, 具体地点中文名, 星图点) 或 None。
    第一次从头读一遍；之后只读日志新增的部分（很快）。这次游戏还没有位置信号就用上一次游戏的日志"""
    from ..system.gamelog import find_log

    path = Path(path) if path else find_log()
    if not path or not Path(path).exists():
        return None
    size = Path(path).stat().st_size
    c = _log_cache
    if (
        c.get("path") != str(path) or c.get("pos", 0) > size
    ):  # 换了日志 / 游戏重开（日志变小）
        c.update(path=str(path), pos=0, state=_LogState())
    if size > c["pos"]:
        c["pos"] = _read_forward(path, c["pos"], c["state"])
        if c["state"].learned:
            c["state"].learned = False
            _save_ids()
    return _hit(c["state"].last) or _from_backups(path)


_backup_cache = {}


def _from_backups(path):
    d = Path(path).parent / "logbackups"
    try:
        logs = sorted(d.glob("*.log"), key=lambda q: q.stat().st_mtime, reverse=True)[
            :3
        ]
    except Exception:
        return None
    for q in logs:
        key = (str(q), q.stat().st_size)
        if key not in _backup_cache:
            st = _LogState()
            _read_forward(q, 0, st)
            if st.learned:
                _save_ids()
            _backup_cache[key] = st.last
        if _backup_cache[key]:
            return _hit(_backup_cache[key])
    return None


def _ts(text):
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _zh(p):
    try:
        from .navigate import BODY_ZH

        return BODY_ZH.get(p["n"], p["n"])
    except Exception:
        return p["n"]


def current():
    """你现在在哪：只用游戏日志里最近一次「打开库存」的地点（最准、每次都有）。
    返回 dict(sys, x, y, z, label, age 秒) 或 None"""
    hit = from_log()
    if not hit:
        return None
    t, label, p = hit
    return dict(
        t=t,
        sys=p["sys"],
        x=p["x"],
        y=p["y"],
        z=p["z"],
        label=label,
        age=time.time() - t,
    )


def distance(here, p):
    """两个位置的距离（米）；不同星系当作很远"""
    if here["sys"] and p["sys"] and here["sys"] != p["sys"]:
        return 1e15
    return math.dist((here["x"], here["y"], here["z"]), (p["x"], p["y"], p["z"]))
