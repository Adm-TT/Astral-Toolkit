"""掉落查询：这件东西在哪些地方的箱子里会开出来（数据来自 scl.miao.network，从游戏文件解析的掉落表）

- 物品索引 search.json（约 1.5 MB，1.3 万项，中英文名都有）缓存在 loot_index.json，版本变了自动重下
- 单件物品的掉落详情 q/<uuid>.json：先查 loot_details.zip（作者每个游戏版本全量抓一次、随 Gitee 数据包发布），没有再现取，缓存在 data/loot/ 下
- 概率是该站算出的「单个箱子开出这件东西的最高概率」，只作参考
"""
import json
import re
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
from .paths import DATA
INDEX = DATA / "loot_index.json"
CACHE_DIR = DATA / "loot"
BASE = "https://scl.miao.network/d/"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
      "Referer": "https://scl.miao.network/"}
_index = None


def _get(url, timeout=60):
    from .net import read
    return json.loads(read(urllib.request.Request(url, headers=UA), timeout=timeout).decode("utf-8"))


def _fold(s):
    return re.sub(r"[^a-z0-9一-鿿]", "", (s or "").lower().replace("l", "i"))


def latest_version():
    """站点当前的数据版本（例如 4.10.2LIVE）；从首页脚本里的 manifest 地址拿不到时用缓存里的"""
    try:
        from .net import read
        html = read(urllib.request.Request("https://scl.miao.network/", headers=UA), timeout=30).decode("utf-8", "replace")
        m = re.search(r"/d/([0-9.]+(?:LIVE|PTU)?)/", html)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def update(version=None, progress=print):
    version = version or latest_version() or (load_index(False) or {}).get("version") or "4.10.2LIVE"
    manifest = _get(f"{BASE}{version}/manifest.json")
    rows = _get(f"{BASE}{version}/search.json", timeout=120)
    data = {"version": manifest.get("version", version), "rows": rows}
    from .paths import write_json
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


_folded = {"of": None, "rows": []}


def _folded_rows(idx):
    """索引里每个物品的名字先折叠好存着（以前每查一次要折叠 2 万多次）"""
    if _folded["of"] is not idx:
        _folded.update(of=idx, rows=[(u, en, zh, rar, _fold(en), _fold(zh), (cls or "").lower(), n or 0)
                                     for u, en, cls, rar, n, zh in idx["rows"]])
    return _folded["rows"]


# 同名的「变体」：NPC 专用、不显示的、测试 / 枪械游戏模式、低模、模板……玩家拿不到，掉落不算它的（2026-10-24 全量核对：
# 「Citadel 胸甲」对到了 _ai_exclusive、「FSK-8 战斗刀」对到了 _gungame）
_VARIANT = re.compile(r"(_ai_exclusive|^nodraw_|_gungame|_debug|_lowpoly|_template|_dummy|_atls|_securitynetwork|"
                      r"_hair_extension|_salvation_|_active$)")


def _wiki_classes(name_en):
    """物品查询（wiki）里这个英文名对应的全部游戏类名；没有返回空集"""
    try:
        from .itemsearch import wiki_items
        k = _fold(name_en)
        out = set()
        for w in wiki_items():
            if _fold(w.get("n")) == k:
                out.add((w.get("cls") or "").lower())
                out.update(c.lower() for c in w.get("alt") or [])
        return out - {""}
    except Exception:
        return set()


def find(name_en="", name_zh=""):
    """按名字找物品：[(uuid, 英文名, 中文名, 稀有度)]，完全同名的排前面。
    同名的有好几个实体时，先要物品查询（wiki）里这个名字的类名，再去掉 NPC 专用、测试这些变体，有掉落的在前。
    名字只是开头像 / 包含的（Zeus 探索头盔 → Zeus 探索头盔 Echo）：物品查询里本来就有这个物品时不算"""
    idx = load_index(False)                       # 索引缺了也不在 F8 / 物品页里联网下（更新数据会下）
    if not idx:
        return []
    ke, kz = _fold(name_en), _fold(name_zh)
    exact, part = [], []
    for u, en, zh, rar, fe, fz, cls, n in _folded_rows(idx):
        if (ke and fe == ke) or (kz and fz == kz):
            exact.append((u, en, zh, rar, cls, n))
        elif (ke and len(ke) >= 6 and fe.startswith(ke)) or (ke and len(ke) >= 5 and ke in fe) or (kz and len(kz) >= 3 and kz in fz):
            part.append((u, en, zh, rar, cls, n))
    if exact:
        good = _wiki_classes(name_en or (exact[0][1] if not name_en else ""))
        pick = [h for h in exact if h[4] in good] or [h for h in exact if not _VARIANT.search(h[4])] or exact
        pick.sort(key=lambda h: -h[5])
        return [h[:4] for h in pick]
    if name_en and _wiki_classes(name_en):
        return []
    part = [h for h in part if not _VARIANT.search(h[4])]
    return [h[:4] for h in part[:5]]


_failed = {}                 # 下载失败的物品 → 时间：10 分钟内不再重试（断网时每次都要等超时）


# ---------------------------------------------------------------- 掉落明细整包（2026-10-26 用户定）
# 作者每次游戏版本更新时把 1.3 万件物品的掉落明细全抓一遍，打成 loot_details.zip 随数据包放到 Gitee，
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
                _zip.update(z=z, mtime=mt, version=z.read("version.txt").decode("utf-8").strip())
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
    from .net import read
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
            return uuid, read(urllib.request.Request(f"{BASE}{version}/q/{uuid}.json", headers=ua), timeout=30)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                stop["why"] = f"对方返回 HTTP {e.code}，已停止"
            return uuid, None
        except Exception:
            return uuid, None

    ok = bad = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z, ThreadPoolExecutor(workers) as ex:
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
        raise RuntimeError(f"掉落明细没抓完：{stop['why']}（已抓 {ok} 件），整包没有生成")
    tmp.replace(out)
    if progress:
        progress(f"掉落明细整包：{version}，{ok} 件，失败 {bad} 件，{out.stat().st_size / 2 ** 20:.1f} MB")
    return ok, bad, version


class Pending(Exception):
    """掉落明细本机没有，要上网取（online=False 时抛出，调用方后台再取）"""


def detail(uuid, online=True):
    idx = load_index(False) or {}
    version = idx.get("version", "4.10.2LIVE")
    hit = _from_zip(uuid, version)                  # 先查整包（Gitee 数据包带来的）
    if hit is not None:
        return hit
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f = CACHE_DIR / f"{version}_{uuid}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
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
    f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return d


PLACED = "直接刷在场景里（不在箱子里）"


def summary(d, top=5):
    """掉落详情 → [(地区, 最高单箱概率, 箱子/位置说明)]，按概率排"""
    out = []
    for r in d.get("regions") or []:
        best = r.get("best") or 0
        cs = sorted(r.get("containers") or [], key=lambda c: c.get("openp") or c.get("p") or 0, reverse=True)
        where = ""
        if cs:
            c = cs[0]
            where = c.get("loc") or ""
            raw = (d.get("raw") or "").split(".")[-1].lower()
            name = (c.get("name") or "").split(" · ")[0].strip()
            if raw and name.lower() == raw:            # 「容器」就是物品自己：直接刷在场景里（奖励室架子上、地上），不在箱子里
                box = PLACED
            else:
                box = re.sub(r"^Lootable_(Generated_)?Container_?", "", c.get("name") or "").replace("_", " ").strip()
            where = "｜".join(x for x in (where, box) if x)
        out.append((r.get("name") or r.get("id"), best, where))
    out.sort(key=lambda x: x[1], reverse=True)
    return out[:top]


# 副本专属矿：不会从箱子里开出来，只能在副本里开采（用户 2026-10-24 告知；掉落站把手采物品挂在挖矿宝石掉落表上，
# 那张表游戏文件里有、实际不刷）。值 = 开采点（可开采岩石）的类名前缀，排除的前缀
INSTANCE_ORES = {
    "carinite": ("mineablerock_fps_carinite", "mineablerock_fps_carinite_pure"),
    "carinitepure": ("mineablerock_fps_carinite_pure", None),
    "janalite": ("mineablerock_fps_janalite", None),
    "jaclium": ("mineablerock_fps_jaclium", None),
    "saldynium": ("mineablerock_fps_saldynium", None),
}
_INSTANCE_ZH = {"科力晶": "carinite", "科力晶（纯）": "carinitepure", "科力晶(纯)": "carinitepure", "纯科力晶": "carinitepure", "纯净科力晶": "carinitepure",
                "加纳石": "janalite", "杰金": "jaclium", "杰金矿石": "jaclium", "烁迪银": "saldynium", "烁迪银矿石": "saldynium"}


def instance_ore(name_en="", name_zh=""):
    """是不是副本专属矿：返回 INSTANCE_ORES 的键，不是返回 None"""
    k = re.sub(r"[^a-z]", "", (name_en or "").lower().replace("(ore)", ""))
    if k in INSTANCE_ORES:
        return k
    return _INSTANCE_ZH.get((name_zh or "").replace(" ", ""))


def mine_info(key, top=5, online=True):
    """副本专属矿的开采点：{name, mine: True, note, groups: [{p, box, regions}], more}"""
    idx = load_index(online)
    if not idx:
        return None
    want, skip = INSTANCE_ORES[key]
    rocks = [r for r in _folded_rows(idx) if r[6].startswith(want) and not (skip and r[6].startswith(skip))]
    best = {}                                      # 地区 → (概率, 位置说明)
    for r in rocks:
        try:
            d = detail(r[0], online)
        except Pending:
            return {"pending": True}
        except Exception as e:
            return {"error": f"开采点数据暂时取不到（{e}）"}
        for region, p, where in summary(d, top=99):
            loc = where.split("｜")[0] if where else ""
            if region not in best or p > best[region][0]:
                best[region] = (p, loc)
    groups = {}
    for region, (p, loc) in best.items():
        groups.setdefault((round(p, 6), loc), []).append(region)
    rows = [{"p": p, "box": loc, "regions": regions}
            for (p, loc), regions in sorted(groups.items(), key=lambda kv: -kv[0][0])[:top]]
    shown = sum(len(r["regions"]) for r in rows)
    from .i18n import mineral_zh
    en = {"carinitepure": "Carinite (Pure)"}.get(key, key.capitalize())
    zh = mineral_zh(en) if key != "carinitepure" else "科力晶（纯）"
    return {"name": zh, "en": en, "mine": True, "src": "scl.miao.network 开采点出现概率", "note": "副本专属矿：不会从箱子里开出来，只能开采",
            "groups": rows, "more": max(0, len(best) - shown)}


def ship_mineral(name_en="", name_zh=""):
    """是不是船挖矿物（量子矿、石英、塔兰导电石…）：返回英文矿名，不是返回 None。
    船挖矿物至少 1/8 SCU，太大进不了战利品箱，掉落站列的开箱掉落实际开不出来（用户 2026-10-24）"""
    try:
        from .data import SIGNATURES
        from .i18n import mineral_en
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
    from .i18n import mineral_zh
    from .locations import where, zh_name
    groups = {}
    for pct, loc in where(mineral):
        groups.setdefault(round(pct / 100, 6), []).append(zh_name(loc))
    rows = [{"p": p, "box": "", "regions": regions} for p, regions in sorted(groups.items(), key=lambda kv: -kv[0])[:top]]
    shown = sum(len(r["regions"]) for r in rows)
    total = sum(len(v) for v in groups.values())
    zh = {"Pressurized Ice": "高压冰"}.get(mineral) or mineral_zh(mineral)
    return {"name": zh, "en": mineral, "mine": True, "src": "SCMiner 船挖地点",
            "note": "船挖矿物：太大进不了战利品箱，只能用船开采" + ("" if rows else "（暂无地点数据）"),
            "groups": rows, "more": max(0, total - shown)}


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
    groups = {}                                  # 概率和箱子一样的地点合成一行
    for region, p, where in summary(d, top=99):
        box = where.split("｜")[-1] if where else ""
        groups.setdefault((round(p, 6), box), []).append(region)
    if not groups:
        return None
    rows = [{"p": p, "box": box, "regions": regions, "placed": box == PLACED}
            for (p, box), regions in sorted(groups.items(), key=lambda kv: -kv[0][0])[:top]]
    shown = sum(len(r["regions"]) for r in rows)
    return {"name": zh or en, "en": en, "uuid": u, "groups": rows,
            "more": max(0, len(d.get("regions") or []) - shown)}


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
            lines.append(f"    {g['p'] * 100:.2f}%｜" + "、".join(g["regions"][:6]) + (f"｜{g['box']}" if g["box"] else ""))
        return "\n".join(lines)
    lines = [f"  掉落（{d['name']}，scl.miao.network，单个箱子开出的最高概率）："]
    for g in d["groups"]:
        regions = g["regions"]
        names = "、".join(regions[:6]) + (f" 等 {len(regions)} 类" if len(regions) > 6 else "")
        lines.append(f"    {g['p'] * 100:.2f}%" + (f"｜{g['box']}" + ("" if g.get("placed") else " 箱") if g["box"] else "") + f"｜{names}")
    if d["more"] > 0:
        lines.append(f"    …还有 {d['more']} 类地点概率更低")
    return "\n".join(lines)
