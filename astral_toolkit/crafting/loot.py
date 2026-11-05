"""掉落查询：这件东西在哪些地方的箱子里会开出来（数据来自 scl.miao.network，从游戏文件解析的掉落表）

- 物品索引 search.json（约 1.5 MB，1.3 万项，中英文名都有）缓存在 loot_index.json，版本变了自动重下
- 单件物品的掉落详情 q/<uuid>.json：先查 loot_details.zip（作者每个游戏版本全量抓一次、随数据包发布），没有再现取，缓存在 data/loot/ 下
- 概率是该站算出的「单个箱子开出这件东西的最高概率」，只作参考
"""

import json
import re
import urllib.request
from pathlib import Path

from ..catalog.loot import (
    exact_candidates,
    group_info,
    mine_groups,
    partial_hits,
    pick_exact,
    ship_groups,
    summary,
)
from ..contracts.textkeys import fold_mixed_loose as _fold
from ..core.paths import DATA

HERE = Path(__file__).resolve().parent

INDEX = DATA / "loot_index.json"
CACHE_DIR = DATA / "loot"
BASE = "https://scl.miao.network/d/"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Referer": "https://scl.miao.network/",
}
_index = None


def _get(url, timeout=60):
    from ..core.net import read

    return json.loads(
        read(urllib.request.Request(url, headers=UA), timeout=timeout).decode("utf-8")
    )


def latest_version():
    """站点当前的数据版本（例如 4.10.2LIVE）；从首页脚本里的 manifest 地址拿不到时用缓存里的"""
    try:
        from ..core.net import read

        html = read(
            urllib.request.Request("https://scl.miao.network/", headers=UA), timeout=30
        ).decode("utf-8", "replace")
        m = re.search(r"/d/([0-9.]+(?:LIVE|PTU)?)/", html)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def update(version=None, progress=print):
    version = (
        version
        or latest_version()
        or (load_index(False) or {}).get("version")
        or "4.10.2LIVE"
    )
    manifest = _get(f"{BASE}{version}/manifest.json")
    rows = _get(f"{BASE}{version}/search.json", timeout=120)
    data = {"version": manifest.get("version", version), "rows": rows}
    from .. import gamedata
    from ..core.paths import write_json

    with gamedata.updating():  # 掉落索引是游戏数据库的源之一：写完在出口重建（收口 1）
        write_json(INDEX, data, separators=(",", ":"))
    global _index
    _index = data
    if progress:
        progress(f"掉落数据：{data['version']}，{len(rows)} 项")
    return data


def load_index(auto=True):
    global _index
    if _index is None and INDEX.exists():
        _index = json.loads(INDEX.read_text(encoding="utf-8"))
    if _index is None and auto:
        print("第一次用掉落查询，下载物品索引（约 1.5 MB）…")
        try:
            update()
        except Exception as e:
            print(f"掉落数据下载失败（{e}）")
    return _index


def _index_meta(snap=None):
    """游戏数据库里掉落索引的版本信息 {"version": …}；没有掉落索引、或库不可用返回 None"""
    from .. import gamedata
    from ..gamedata import loot as gd_loot

    try:
        return gd_loot.index_meta(snap)
    except gamedata.GamedataError:
        return None


def _wiki_classes(name_en):
    """物品查询（wiki）里这个英文名对应的全部游戏类名（含 alt）；没有返回空集。在 find 里调时用 find 钉住的快照"""
    try:
        from ..gamedata import loot as gd_loot

        return set(gd_loot.wiki_classes(_fold(name_en)))
    except Exception:
        return set()


def find(name_en="", name_zh=""):
    """按名字找物品：[(uuid, 英文名, 中文名, 稀有度)]，完全同名的排前面。
    同名的有好几个实体时，先要物品查询（wiki）里这个名字的类名，再去掉 NPC 专用、测试这些变体，有掉落的在前。
    名字只是开头像 / 包含的（Zeus 探索头盔 → Zeus 探索头盔 Echo）：物品查询里本来就有这个物品时不算。
    数据来自游戏数据库（掉落索引缺了也不在 F8 / 物品页里联网下，更新数据会下）；库不可用时返回空"""
    from .. import gamedata
    from ..gamedata import loot as gd_loot

    ke, kz = _fold(name_en), _fold(name_zh)
    try:
        gamedata.ensure()
        with gamedata.snapshot() as s:  # 精确、wiki 类名、部分匹配钉在同一个版本上
            exact = exact_candidates(gd_loot.exact(ke, kz, s))
            if exact:
                good = _wiki_classes(name_en or exact[0][1])  # 源顺序第一个，排序前取
                return pick_exact(exact, good)
            if name_en and _wiki_classes(name_en):
                return []
            return partial_hits(gd_loot.rows(s), ke, kz)
    except gamedata.GamedataError:
        return []


_failed = {}  # 下载失败的物品 → 时间：10 分钟内不再重试（断网时每次都要等超时）


# ---------------------------------------------------------------- 掉落明细整包（2026-10-26 用户定）
# 作者每次游戏版本更新时把 1.3 万件物品的掉落明细全抓一遍，打成 loot_details.zip 随数据包发布，
# 国内玩家查看掉落不用再连国外；整包里没有的（抓失败的）照旧现查。玩家这边不解压，直接从压缩包里读
DETAILS = DATA / "loot_details.zip"
_zip = {"z": None, "mtime": None, "version": None}
_zip_lock = __import__("threading").Lock()


def details_version(path=None):
    """整包对应的掉落数据版本（4.10.2LIVE）；没有整包返回空"""
    import zipfile

    p = Path(path or DETAILS)
    try:
        with zipfile.ZipFile(p) as z:
            return z.read("version.txt").decode("utf-8").strip()
    except Exception:
        return ""


def _from_zip(uuid, version):
    import zipfile

    try:
        mt = DETAILS.stat().st_mtime
    except OSError:
        return None
    with _zip_lock:
        if _zip["mtime"] != mt:
            if _zip["z"]:
                _zip["z"].close()
            try:
                z = zipfile.ZipFile(DETAILS)
                _zip.update(
                    z=z, mtime=mt, version=z.read("version.txt").decode("utf-8").strip()
                )
            except Exception:
                _zip.update(z=None, mtime=mt, version=None)
        z = _zip["z"]
        if not z or _zip["version"] != version:
            return None
        try:
            return json.loads(z.read(f"{uuid}.json").decode("utf-8"))
        except KeyError:
            return None


def close_bundle():
    """关掉正在读的整包（Windows 上打开着的文件不能替换：更新整包前先调）"""
    with _zip_lock:
        if _zip["z"]:
            _zip["z"].close()
        _zip.update(z=None, mtime=None, version=None)


def crawl_details(out=None, workers=16, progress=print):
    """作者发布数据用：全速下载当前版本所有物品的掉落明细，打成 loot_details.zip。
    对方限流或拒绝（HTTP 429 / 403）立即停下，不硬抓；单件失败的跳过（玩家查看时现查）。返回 (成功数, 失败数, 版本)"""
    import zipfile
    import urllib.error
    from concurrent.futures import ThreadPoolExecutor
    from ..core.net import read

    idx = update(progress=None)
    version, rows = idx["version"], idx["rows"]
    out = Path(out or DETAILS)
    tmp = out.with_suffix(".part")
    ua = {**UA, "User-Agent": UA["User-Agent"] + " AT-Astral-Toolkit/data-mirror"}
    stop = {"why": None}

    def one(uuid):
        if stop["why"]:
            return uuid, None
        try:
            return uuid, read(
                urllib.request.Request(f"{BASE}{version}/q/{uuid}.json", headers=ua),
                timeout=30,
            )
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                stop["why"] = f"对方返回 HTTP {e.code}，已停止"
            return uuid, None
        except Exception:
            return uuid, None

    ok = bad = 0
    with (
        zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z,
        ThreadPoolExecutor(workers) as ex,
    ):
        z.writestr("version.txt", version)
        for i, (uuid, body) in enumerate(ex.map(one, [r[0] for r in rows]), 1):
            if body:
                try:
                    json.loads(body.decode("utf-8"))
                    z.writestr(f"{uuid}.json", body)
                    ok += 1
                except ValueError:
                    bad += 1
            else:
                bad += 1
            if progress and i % 1000 == 0:
                progress(f"掉落明细：{i}/{len(rows)}（失败 {bad}）")
    if stop["why"]:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"掉落明细没抓完：{stop['why']}（已抓 {ok} 件），整包没有生成"
        )
    tmp.replace(out)
    if progress:
        progress(
            f"掉落明细整包：{version}，{ok} 件，失败 {bad} 件，{out.stat().st_size / 2**20:.1f} MB"
        )
    return ok, bad, version


class Pending(Exception):
    """掉落明细本机没有，要上网取（online=False 时抛出，调用方后台再取）"""


_UUID_RE = re.compile(r"[0-9A-Za-z\-]{1,64}")
_VER_RE = re.compile(r"\w[\w.\-]{0,63}")


def detail(uuid, online=True):
    version = (_index_meta() or {}).get("version", "4.10.2LIVE")
    # 要拼进缓存路径和网址：只认字母数字、点、横线，别让 ..\ 之类跑到缓存目录外面
    if not isinstance(uuid, str) or not _UUID_RE.fullmatch(uuid):
        raise ValueError("物品编号格式不对")
    if not isinstance(version, str) or not _VER_RE.fullmatch(version):
        raise ValueError("掉落数据版本号格式不对")
    hit = _from_zip(uuid, version)  # 先查整包（数据包带来的）
    if hit is not None:
        return hit
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f = CACHE_DIR / f"{version}_{uuid}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (
            ValueError
        ):  # 半个文件（旧版直接写、写到一半被结束）：删掉当没有，别永远卡在坏缓存上
            f.unlink(missing_ok=True)
    if not online:
        raise Pending()
    import time as _t

    if _t.time() - _failed.get(uuid, 0) < 600:
        raise OSError("网络不通，稍后再试")
    try:
        d = _get(f"{BASE}{version}/q/{uuid}.json", timeout=15)
    except Exception:
        _failed[uuid] = _t.time()
        raise
    from ..core.paths import write_json

    write_json(f, d)  # 先写临时文件再换名，不留半个文件
    return d


# 副本专属矿：不会从箱子里开出来，只能在副本里开采（用户 2026-10-24 告知；掉落站把手采物品挂在挖矿宝石掉落表上，
# 那张表游戏文件里有、实际不刷）。值 = 开采点（可开采岩石）的类名前缀，排除的前缀
INSTANCE_ORES = {
    "carinite": ("mineablerock_fps_carinite", "mineablerock_fps_carinite_pure"),
    "carinitepure": ("mineablerock_fps_carinite_pure", None),
    "janalite": ("mineablerock_fps_janalite", None),
    "jaclium": ("mineablerock_fps_jaclium", None),
    "saldynium": ("mineablerock_fps_saldynium", None),
}
_INSTANCE_ZH = {
    "科力晶": "carinite",
    "科力晶（纯）": "carinitepure",
    "科力晶(纯)": "carinitepure",
    "纯科力晶": "carinitepure",
    "纯净科力晶": "carinitepure",
    "加纳石": "janalite",
    "杰金": "jaclium",
    "杰金矿石": "jaclium",
    "烁迪银": "saldynium",
    "烁迪银矿石": "saldynium",
}


def instance_ore(name_en="", name_zh=""):
    """是不是副本专属矿：返回 INSTANCE_ORES 的键，不是返回 None"""
    k = re.sub(r"[^a-z]", "", (name_en or "").lower().replace("(ore)", ""))
    if k in INSTANCE_ORES:
        return k
    return _INSTANCE_ZH.get((name_zh or "").replace(" ", ""))


def mine_info(key, top=5, online=True):
    """副本专属矿的开采点：{name, mine: True, note, groups: [{p, box, regions}], more}"""
    from .. import gamedata
    from ..gamedata import loot as gd_loot

    want, skip = INSTANCE_ORES[key]
    try:
        gamedata.ensure()
        with gamedata.snapshot() as s:  # 索引版本和石头行钉同一个版本
            has = (
                gd_loot.index_meta(s) is not None
            )  # 库在、只是没有掉落索引（有索引、只是没有行不算）
            rocks = gd_loot.by_cls_prefix(want, s) if has else ()
        if not has:
            if not online:
                return None
            load_index(
                True
            )  # 联网下一份（在快照外）：update() 在更新边界里，写完重建库
            with (
                gamedata.snapshot() as s
            ):  # 重建后的新版本；若外面还钉着旧快照就还是旧的，下次再查
                if gd_loot.index_meta(s) is None:
                    return None
                rocks = gd_loot.by_cls_prefix(want, s)
    except (
        gamedata.GamedataError
    ):  # 库不可用：不在查询路径里读 JSON / 联网（收口 2，待做 ⑮）
        return None
    rocks = [r for r in rocks if not (skip and r.cls_lower.startswith(skip))]
    best = {}  # 地区 → (概率, 位置说明)
    for r in rocks:
        try:
            d = detail(r.uuid, online)
        except Pending:
            return {"pending": True}
        except Exception as e:
            return {"error": f"开采点数据暂时取不到（{e}）"}
        for region, p, where in summary(d, top=99):
            loc = where.split("｜")[0] if where else ""
            if region not in best or p > best[region][0]:
                best[region] = (p, loc)
    rows, more = mine_groups(best, top)
    from ..core.i18n import mineral_zh

    en = {"carinitepure": "Carinite (Pure)"}.get(key, key.capitalize())
    zh = mineral_zh(en) if key != "carinitepure" else "科力晶（纯）"
    return {
        "name": zh,
        "en": en,
        "mine": True,
        "src": "scl.miao.network 开采点出现概率",
        "note": "副本专属矿：不会从箱子里开出来，只能开采",
        "groups": rows,
        "more": more,
    }


def ship_mineral(name_en="", name_zh=""):
    """是不是船挖矿物（量子矿、石英、塔兰导电石…）：返回英文矿名，不是返回 None。
    船挖矿物至少 1/8 SCU，太大进不了战利品箱，掉落站列的开箱掉落实际开不出来（用户 2026-10-24）"""
    try:
        from ..mining.data import SIGNATURES
        from ..core.i18n import mineral_en
    except Exception:
        return None
    base = re.sub(r"\s*\(.*?\)", "", name_en or "").strip().lower()
    names = {k.lower(): k for k in SIGNATURES}
    names["pressurized ice"] = "Pressurized Ice"
    if base in names:
        return names[base]
    if name_zh and not name_en:
        m = mineral_en(name_zh, fuzzy=False, ship_only=True)
        return m if m in SIGNATURES else None
    return None


def ship_info(mineral, top=5):
    """船挖矿物的挖矿地点（SCMiner 的船挖地点数据）：格式同 info，多 mine=True、note、src"""
    from ..core.i18n import mineral_zh
    from ..mining.locations import where, zh_name

    pairs = [(pct, zh_name(loc)) for pct, loc in where(mineral)]
    rows, more = ship_groups(pairs, top)
    zh = {"Pressurized Ice": "高压冰"}.get(mineral) or mineral_zh(mineral)
    return {
        "name": zh,
        "en": mineral,
        "mine": True,
        "src": "SCMiner 船挖地点",
        "note": "船挖矿物：太大进不了战利品箱，只能用船开采"
        + ("" if rows else "（暂无地点数据）"),
        "groups": rows,
        "more": more,
    }


def info(name_en="", name_zh="", top=5, online=True):
    """掉落（窗口用）：{name, groups: [{p, box, regions}], more} 或 None；取不到数据时 {error}。
    副本专属矿（科力晶、加纳石、杰金、烁迪银）返回开采点：多一个 mine=True、note。
    online=False：明细本机没有就返回 {pending: True}，不上网等（2026-10-28 用户反馈物品查询卡 10 秒）"""
    key = instance_ore(name_en, name_zh)
    if key:
        return mine_info(key, top, online)
    ship = ship_mineral(name_en, name_zh)
    if ship:
        return ship_info(ship, top)
    hits = find(name_en, name_zh)
    if not hits:
        return None
    u, en, zh, rar = hits[0]
    try:
        d = detail(u, online)
    except Pending:
        return {"pending": True}
    except Exception as e:
        return {"error": f"掉落数据暂时取不到（{e}）"}
    grouped = group_info(d, top)  # 概率和箱子一样的地点合成一行
    if grouped is None:
        return None
    rows, more = grouped
    return {
        "name": zh or en,
        "en": en,
        "uuid": u,
        "groups": rows,
        "more": more,
    }


def text(name_en="", name_zh="", top=5):
    """一段「哪里能开出来」的说明；没有掉落返回空字符串"""
    d = info(name_en, name_zh, top)
    if not d:
        return ""
    if "error" in d:
        return "  " + d["error"]
    if d.get("mine"):
        if not d["groups"]:
            return f"  {d['note']}"
        lines = [f"  {d['note']}（{d['name']}，{d['src']}）："]
        for g in d["groups"]:
            lines.append(
                f"    {g['p'] * 100:.2f}%｜"
                + "、".join(g["regions"][:6])
                + (f"｜{g['box']}" if g["box"] else "")
            )
        return "\n".join(lines)
    lines = [f"  掉落（{d['name']}，scl.miao.network，单个箱子开出的最高概率）："]
    for g in d["groups"]:
        regions = g["regions"]
        names = "、".join(regions[:6]) + (
            f" 等 {len(regions)} 类" if len(regions) > 6 else ""
        )
        lines.append(
            f"    {g['p'] * 100:.2f}%"
            + (f"｜{g['box']}" + ("" if g.get("placed") else " 箱") if g["box"] else "")
            + f"｜{names}"
        )
    if d["more"] > 0:
        lines.append(f"    …还有 {d['more']} 类地点概率更低")
    return "\n".join(lines)
