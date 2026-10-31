"""汉化包：从 SC 汉化盒子（app.scbox.xkeyc.cn）取最新的简中汉化，然后重建程序里所有中文名

- 版本列表：SCToolBox/api 仓库里的 localizations/chinese_(simplified).json（盒子网页版就是读这个）
- 下载：SCToolBox/LocalizationData 仓库的 /archive/<版本名>.tar.gz，取里面的 global.ini（和盒子 App 一样）
- 固定用「[社区] 简中双语增强汉化」（CNRSUI，物品名是「中文 + 英文」，对照表要靠这个格式）；
  也认得「汉化组双语」（CNEN，「English + 中文」）的格式，以防万一
- 汉化包只是拿来对照中文名，程序不会把它装进游戏
菜单 5 会先跑这一步。
"""

import io
import json
import re
import tarfile
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
ROOT = HERE.parent
from ..core.paths import DATA  # noqa: E402

INI = DATA / "loc" / "global_zh.ini"
STAMP = DATA / "loc" / "version.txt"
HOSTS = ["https://ecdn.git.scbox.xkeyc.cn", "https://git.scbox.xkeyc.cn"]
LIST = "/SCToolBox/api/raw/branch/main/localizations/chinese_(simplified).json"
ARCHIVE = "/SCToolBox/LocalizationData/archive/{}.tar.gz"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SCAssistant/1.0"}
CJK = "\u4e00-\u9fff"


def _get(path, timeout=60):
    last = None
    for host in HOSTS:
        try:
            url = host + urllib.parse.quote(path, safe="/:().,_-")
            from ..core.net import read

            return read(urllib.request.Request(url, headers=UA), timeout=timeout)
        except Exception as e:
            last = e
    raise last


def pick_version(versions, variant="CNRSUI", channel="PU"):
    """在版本列表里挑：启用的、指定频道、版本名含 variant 的，取更新时间最新的"""
    rows = [
        v
        for v in versions
        if v.get("enable")
        and v.get("game_channel") == channel
        and f"_{variant}_" in v.get("versionName", "")
    ]
    return max(rows, key=lambda v: v.get("updateAt", ""), default=None)


def extract_ini(tar_bytes):
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tf:
        for m in tf.getmembers():
            if (
                m.isfile()
                and m.name.lower().endswith("global.ini")
                and "simplified" in m.name.lower()
            ):
                return tf.extractfile(m).read()
        for m in tf.getmembers():
            if m.isfile() and m.name.lower().endswith("global.ini"):
                return tf.extractfile(m).read()
    raise ValueError("汉化包里没有 global.ini")


def update(force=False, progress=print):
    # 下载「社区双语增强」当后备；游戏里装着双语汉化时，中文名以游戏里的为准（names_source）
    variant = "CNRSUI"
    versions = json.loads(_get(LIST))
    v = pick_version(versions, variant)
    if not v:
        raise ValueError(f"汉化盒子里没有 {variant} 版本")
    name = v["versionName"]
    cur = STAMP.read_text(encoding="utf-8").strip() if STAMP.exists() else ""
    if name == cur and INI.exists() and not force:
        progress(f"汉化包已是最新（{name}，{v.get('updateAt')}）")
        return sync_game(progress)
    progress(f"下载汉化包 {name}（{v.get('info')}，{v.get('updateAt')}）…")
    ini = extract_ini(_get(ARCHIVE.format(name), timeout=180))
    INI.parent.mkdir(parents=True, exist_ok=True)
    INI.write_bytes(ini)
    STAMP.write_text(name, encoding="utf-8")
    progress("重建中文名对照…")
    rebuild(progress)
    progress(f"汉化包已更新：{cur or '无'} → {name}")
    return True


# ---------------------------------------------------------------- 重建各处的中文名


def read_ini(path=INI):
    out = {}
    for line in (
        Path(path).read_text(encoding="utf-8-sig", errors="replace").splitlines()
    ):
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.split(",")[0]] = v
    return out


def wiki_class_names():
    """wiki 物品清单里 {游戏内部类名(小写): wiki 英文名}（1.6.49，按类名把汉化包的英文名对到 wiki 正名）"""
    try:
        from ..crafting.itemsearch import wiki_items
    except Exception:
        return {}
    out = {}
    for w in wiki_items():
        for c in [w.get("cls") or ""] + list(w.get("alt") or []):
            if c:
                out.setdefault(c, w["n"])
    return out


ALIASES = {}  # zh2en_items 顺带记下来：{汉化包里的英文写法: wiki 正名}（写错 / 过时的，搜旧写法也能找到）


def zh2en_items(ini, wiki_cls=None):
    """物品名：「中文\\nEnglish」或「中文English」→ {中文: English}（交易查价、截图对照用）。
    wiki_cls（{类名: wiki 英文名}，None = 自动取）：键名 item_Name_<类名> 能对上 wiki 时以 wiki 正名为准——汉化包里有 37 条英文写错或过时
    （「CF-227 Bulldog Repeater」游戏现在叫 Badger、「Monolith Arms」→ Monolith Armor Arms），商店 / 掉落数据都挂在正名下（1.6.49）；
    汉化包的写法记进 ALIASES"""
    zh2en = {}
    ALIASES.clear()
    if wiki_cls is None:
        wiki_cls = wiki_class_names()

    def add(zh, en, cls=""):
        zh, en = zh.strip(' "“”'), en.strip(' "')
        if (
            zh.startswith("[") or "|" in zh
        ):  # 「RN-7s\n[流速氢1.65 | 血量9000]」：第二行是属性，不是中文名（1.6.48）
            return
        if (
            zh
            and en
            and re.search(f"[{CJK}]", zh)
            and not re.search(f"[{CJK}]", en)
            and len(en) >= 2
        ):
            real = wiki_cls.get(cls) if cls else None
            if real and real.lower() != en.lower() and not re.search(f"[{CJK}]", real):
                ALIASES[en] = real
                en = real
            zh2en.setdefault(zh, en)

    def add_mod(zh, en, cls=""):
        # 采矿模组的键是 item_Mining_Modules_…_Name，值「净采 模组Clearcut\n[属性]」：英文补上 Module，和 wiki / 游戏里的全名一致（1.6.48）
        add(zh, en if "module" in en.lower() else f"{en} Module", cls)

    def add_laser(zh, en, cls=""):
        # 采矿激光器「柳叶刀 MH1 型采矿激光器Lancet MH1」：商店数据里叫 Lancet MH1 Mining Laser（2026-10-28）
        add(zh, en if "laser" in en.lower() else f"{en} Mining Laser", cls)

    for k, v in ini.items():
        kl = k.lower()
        tail_name = kl.startswith("item_") and kl.endswith(
            "_name"
        )  # item_Cargo_…_Name、item_Mining_…_Name、item_fuelpod_…_Name（1.6.48）
        mining = kl.startswith(
            "item_mining_"
        )  # 采矿模组 / 激光器有一半的键不带 _Name（item_Mining_Modules_Passive_Rieger_C3；2026-10-28 老大 F8 反馈）
        if (
            not (
                kl.startswith("item_name")
                or kl.startswith("items_commodities")
                or kl.startswith("item_short")
                or tail_name
                or mining
            )
            or "desc" in kl
        ):
            continue
        if kl.startswith("item_short") or kl.endswith("_short") or kl.endswith("_shop"):
            continue  # 简称：后面带的是尺寸、型号代码（「视差步枪HD」），不是英文名（1.6.41）
        cls = (
            kl[len("item_name") :].lstrip("_") if kl.startswith("item_name") else ""
        )  # item_Name_<类名>：wiki 的 class_name
        put_ = (
            add_mod
            if ("mining_modules" in kl or "mining_consumable" in kl)
            else add_laser
            if "mining_mininglaser" in kl
            else add
        )
        put = lambda zh, en, _c=cls, _f=put_: _f(zh, en, _c)  # noqa: E731
        v = re.sub(r"<[^>]+>", "", v)
        parts = v.split("\\n")
        first = parts[0].strip()
        if (
            len(parts) >= 2
            and re.fullmatch(r"[\x20-\x7e]+", first)
            and re.search(f"[{CJK}]", parts[1])
        ):
            put(parts[1].strip(), first)  # 汉化组双语（CNEN）：「English\n中文」
            continue
        if (
            len(parts) >= 2
            and re.fullmatch(r"[\x20-\x7e]+", parts[1].strip())
            and re.search(f"[{CJK}]", first)
            and not parts[1].strip().startswith("[")
        ):  # 第二行是「[属性]」的不是英文名（1.6.49）
            en = parts[1].strip()
            put(
                first[: -len(en)].strip()
                if first.endswith(en) and len(first) > len(en)
                else first,
                en,
            )
            continue
        m = re.fullmatch(
            f'(.*[{CJK}][^A-Za-z]*?)\\s*([A-Za-z0-9"][A-Za-z0-9 \\-\'".()/&]*)', first
        )
        if m:
            put(m.group(1), m.group(2))
    return zh2en


PLACE_CODE = re.compile(
    r"^(rr_|pyro|nyx|stanton|asteroidcluster|ooc_|.*jumppoint)", re.I
)
PLACE_SKIP = re.compile(r"desc|mission|contract|_title|_obj", re.I)


def place_codes(ini):
    """地点代号 → 中文名（RR_P1_L2、Pyro5d、Pyro_JumpPoint_Stanton…），只要中文第一行。随安装包带一份
    data/place_codes_zh.json：新装还没下汉化包时，派罗地名也不显示成 PYR3 这种代号（Codex 2026-10-27 补审）"""
    return {
        k.lower(): v.split("\\n")[0].strip()
        for k, v in ini.items()
        if PLACE_CODE.match(k) and not PLACE_SKIP.search(k) and v.strip()
    }


def places(ini):
    """地名：{英文名去符号小写: 中文名}（导航用）"""
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())  # noqa: E731
    out = {}
    for k, v in ini.items():
        if k.lower().endswith("desc") or len(v) > 80:
            continue
        v = re.sub(r"<[^>]+>", "", v)
        m = re.fullmatch(
            f"(.*?[{CJK}][^\\\\]*?)\\s*[\\(（]([A-Za-z0-9][^()（）]*)[\\)）]\\s*(?:[\\(（].*[\\)）])?",
            v,
        ) or re.fullmatch(f"(.*?[{CJK}].*?)\\\\n([A-Za-z0-9][\\x20-\\x7e]*)", v)
        if m:
            zh, en = m.group(1).strip(), m.group(2).strip()
        else:  # 汉化组双语（CNEN）：「English [中文]」或「English\n中文」
            m = re.fullmatch(
                f"([A-Za-z0-9][\\x20-\\x7e]*?)\\s*\\[([^\\]]*[{CJK}][^\\]]*)\\]", v
            ) or re.fullmatch(f"([A-Za-z0-9][\\x20-\\x7e]*?)\\\\n(.*?[{CJK}].*)", v)
            if not m:
                continue
            en, zh = m.group(1).strip(), m.group(2).strip()
        if re.search(f"[{CJK}]", zh) and not re.search(f"[{CJK}]", en) and len(en) > 2:
            out.setdefault(norm(en), zh)
    return out


def rebuild(progress=print):
    src = names_source()
    if src.suffix != ".ini":
        return
    ini = read_ini(src)
    from ..core.paths import write_json

    write_json(
        DATA / "zh_names.json", zh2en_items(ini), separators=(",", ":")
    )  # 原子写：中途被结束不会留半个文件（2026-10-28）
    write_json(DATA / "name_aliases.json", ALIASES, separators=(",", ":"))
    write_json(DATA / "places_zh.json", places(ini), separators=(",", ":"))
    write_json(DATA / "place_codes_zh.json", place_codes(ini), separators=(",", ":"))
    try:
        from ..navigation import position

        position.reset_names()
    except Exception:
        pass
    try:
        from ..trade import names

        names.table.cache_clear()
        names._index.cache_clear()
    except Exception:
        pass
    # 制造蓝图和维科洛兑换：用本地已有的数据 + 新汉化重建（2026-10-28 审查：先看自己解包的，没有才用 scmdb）
    from ..crafting.build_crafting import (
        latest_live,
        live_version,
        unpacked,
        BUILD_LOCK,
    )

    own = unpacked()
    if own:
        bp, merged = own[0], own[1]
    else:
        raw = DATA / "scmdb"
        bp = latest_live(
            raw.glob("crafting_blueprints-*.json")
        )  # 只用正式服（以前按文件名排，会挑到测试服 PTU）
        merged = (
            raw / f"merged-{live_version(bp)}.json" if bp and live_version(bp) else None
        )  # 和蓝图同一个版本
        merged = merged if merged and merged.exists() else None
    if bp and merged:
        from ..crafting.build_crafting import build
        from ..crafting.wikelo import build as build_wikelo

        with (
            BUILD_LOCK
        ):  # 和 build_crafting.update 可能同时跑（run.update 并行），别一起写同一个文件
            build(bp, merged, src, DATA / "crafting.json")
            progress(f"维科洛兑换：{build_wikelo(merged, src)} 个")
    from .data_pack import clear_caches

    clear_caches()


GAME_STAMP = DATA / "loc" / "game_version.txt"


def game_ini():
    """玩家游戏里装着的简中汉化（LIVE/data/Localization/chinese_(simplified)/global.ini）。
    名字以它为准（2026-10-23 用户要求：和游戏内汉化一致）；只认双语包（物品名里带英文），纯中文包对不上英文名就不用"""
    cands = []
    try:
        from ..core import settings

        log = settings.load().get("game_log") or ""
        if log:
            cands.append(Path(log).parent)
    except Exception:
        pass
    cands += [
        Path(r"C:\Program Files\Roberts Space Industries\StarCitizen\LIVE"),
        Path(r"D:\StarCitizen\LIVE"),
        Path(r"D:\Roberts Space Industries\StarCitizen\LIVE"),
    ]
    for d in cands:
        p = d / "data" / "Localization" / "chinese_(simplified)" / "global.ini"
        try:
            if p.is_file() and _bilingual(p):
                return p
        except OSError:
            continue
    return None


def _bilingual(p):
    n = both = 0
    with open(p, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            if line.lower().startswith("item_name") and "=" in line:
                v = line.split("=", 1)[1]
                if re.search(f"[{CJK}]", v):
                    n += 1
                    both += bool(re.search(r"[A-Za-z]{3,}", v))
                if n >= 400:
                    break
    return n >= 50 and both / n >= 0.5


def names_tag(p):
    """一份汉化的身份：游戏里的按路径+大小+修改时间，下载的按版本名"""
    p = Path(p)
    if p == INI:
        return "pack:" + (
            STAMP.read_text(encoding="utf-8").strip() if STAMP.exists() else ""
        )
    if p.suffix == ".ini" and p.exists():
        return "game:" + game_stamp(p)
    return "bundled"


def game_stamp(p):
    st = p.stat()
    return f"{p}|{st.st_size}|{int(st.st_mtime)}"


def sync_game(progress=print):
    """游戏里的汉化变了（换了汉化包或汉化更新了）就用它重建所有中文名；没变不动。返回是否重建了"""
    p = game_ini()
    if not p:
        return False
    stamp = game_stamp(p)
    if GAME_STAMP.exists() and GAME_STAMP.read_text(encoding="utf-8").strip() == stamp:
        return False
    progress(f"按游戏里的汉化重建中文名：{p}")
    rebuild(progress)
    GAME_STAMP.parent.mkdir(parents=True, exist_ok=True)
    GAME_STAMP.write_text(stamp, encoding="utf-8")
    return True


def names_source():
    """重建中文名用哪份汉化：游戏里装着的双语汉化 > 下载的社区汉化包 > 随程序带的子集"""
    return game_ini() or (INI if INI.exists() else HERE / "names_zh.json")
