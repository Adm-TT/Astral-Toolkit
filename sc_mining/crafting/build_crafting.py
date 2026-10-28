"""把 scmdb 的蓝图 + 任务数据压缩成 crafting.json（程序直接读这个）

在你电脑上：python -m sc_mining.build_crafting   → 联网检查 scmdb 新版本，有就下载并重建
开发时：    python -m sc_mining.build_crafting <蓝图json> <任务json> <global.ini 或 names_zh.json> <输出>
中文名来自用户的汉化包；随程序附带的 names_zh.json 是从汉化包里摘出来的子集。
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from ..core import paths

HERE = Path(__file__).resolve().parent
SCMDB = "https://scmdb.net/data/"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/130.0 Safari/537.36", "Accept": "application/json", "Referer": "https://scmdb.net/"}
RES_FIX = {"Pressurized Ice": "Ice"}          # 与矿物表统一
CJK = "\u4e00-\u9fff"


def _load_names(path):
    """返回 (全部键值 {小写键: 文本}, 物品名行 {小写键: 文本})"""
    path = Path(path)
    if path.suffix == ".json":
        d = json.loads(path.read_text(encoding="utf-8"))
        return {**d["items"], **d["keys"]}, d["items"]
    ini = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            ini[k.split(",")[0].lower()] = v
    items = {k: v for k, v in ini.items() if k.startswith(("item_name", "item_mining", "item_short", "item_cargo"))}
    return ini, items


def _item_names(items):
    """物品名行 → {英文名(小写): 中文名}"""
    zh = {}
    for val in items.values():
        parts = val.split("\\n")
        first = parts[0].strip()
        if len(parts) >= 2 and re.search(f"[{CJK}]", first) and re.fullmatch(r"[\x20-\x7e]+", parts[1].strip()):
            en = parts[1].strip()
            # 只有中文名后面正好接着英文名时才去掉英文，"焦糊 快子加农炮 (S1)" 这种保持原样
            cn = first[: -len(en)].strip() if first.endswith(en) and len(first) > len(en) else first
            zh.setdefault(en.lower(), cn)
        # "冰川Glacier\n[冷却 S1 军用 A]" / "螺旋 II 型采矿激光器Helix II"：中文后面直接跟英文名
        m = re.fullmatch(f"(.*[{CJK}][^A-Za-z]*?)\\s*([A-Za-z][A-Za-z0-9 \\-'.]*)", first)
        if m:
            cn, en = m.group(1).strip(), m.group(2).strip()
            for variant in (en, en.replace("-", ""), en + " Mining Laser", en + " Module", en + " Mining Module"):
                zh.setdefault(variant.lower(), cn)
    return zh


def _strip_en(first, rest, en):
    """「低温之星SL CryoStarSL」「激流Torrent」「岩层 头盔\\nStrata Helmet」→ 只留中文名（含 SL、-Go 这类后缀）"""
    if not re.search(f"[{CJK}]", first):
        return ""
    if rest and re.fullmatch(r"[\x20-\x7e]+", rest) and first.endswith(rest) and len(first) > len(rest):
        return first[: -len(rest)].strip()
    if rest and re.fullmatch(r"[\x20-\x7e]+", rest):
        return first
    low = first.lower()
    for cand in (en, en.replace(" ", ""), en.replace("-", ""), en.replace(" ", "").replace("-", "")):
        if cand and low.endswith(cand.lower()) and len(first) > len(cand):
            return first[: -len(cand)].strip()
    m = re.fullmatch(f"(.*[{CJK}][^A-Za-z]*?)\\s*([A-Za-z][A-Za-z0-9 \\-'.]*)", first)
    cn = m.group(1).strip() if m else first
    return re.sub(f"([{CJK}])[A-Za-z][A-Za-z' ]*([”\"'])", r"\1\2", cn)      # 6MA “科赞Kozane” → 6MA “科赞”


def class_zh(ini, tag, en):
    """按蓝图的物品类名查汉化包里这件物品自己的名字（游戏里显示的就是这一条），查不到返回 None"""
    c = tag.replace("BP_CRAFT_", "").lower()
    base = c[:-7] if c.endswith("_scitem") else c
    for k in (c, base, base + "_scitem"):
        for pre in ("item_name", "item_name_"):
            v = ini.get(pre + k)
            if v:
                parts = v.split("\\n")
                return _strip_en(parts[0].strip(), parts[1].strip() if len(parts) > 1 and not parts[1].startswith("[") else "", en)
    return None


BUILD_LOCK = __import__("threading").RLock()      # build / update / localization.rebuild 不同时写 crafting.json（2026-10-28）


def build(bp_path, merged_path, names_path, out_path):
    bp = json.loads(Path(bp_path).read_text(encoding="utf-8"))
    merged = json.loads(Path(merged_path).read_text(encoding="utf-8"))
    ini, items = _load_names(names_path)
    zh = _item_names(items)

    def zh_lookup(name):
        key = name.lower()
        return zh.get(key) or zh.get(key.replace("-", "")) or zh.get(key.replace(" ", "")) or ""

    def _pick_zh(b, name):
        """舰船部件按类名取（同名不同物品时名字查会张冠李戴，比如量子驱动器 Torrent 被当成采矿模组「洪流」）；
        护甲、武器按英文名取（蓝图类名常指向某个涂装版本），名字查不到再按类名补"""
        by_cls = class_zh(ini, b["tag"], name)
        if b["gear"] == "vehiclegear" and by_cls:
            return by_cls
        return zh_lookup(name) or by_cls or ""

    def ini_text(key):
        if not key:
            return ""
        v = ini.get(key.lstrip("@").lower(), "")
        v = re.sub(r"\\n\[.*$", "", v).replace("\\n", " ")
        v = re.sub(r"<[^>]+>", "", v)                 # 去掉 <EM4> 之类的排版标签
        return v.replace("[蓝图]", "").strip()

    # 蓝图来源：任务 → 蓝图池 → 蓝图
    sources = defaultdict(list)
    for c in merged["contracts"]:
        for r in c.get("blueprintRewards") or []:
            for b in merged["blueprintPools"].get(r["blueprintPool"], {}).get("blueprints", []):
                sources[b["blueprintRecord"]].append(
                    [ini_text(c.get("titleLocKey") or c.get("titleKey")) or c.get("title") or "",
                     ini_text(c.get("contractorNameKey")) or c.get("contractorName") or "",
                     ini_text(c.get("missionTypeKey")) or c.get("missionType") or "",
                     "/".join(c.get("systems") or []), round(r.get("chance", 1), 3)])

    out = []
    for b in bp["blueprints"]:
        t = b["tiers"][0]
        slots = []
        for s in t["slots"]:
            opts = []
            for o in s["options"]:
                name = o.get("resourceName") or o.get("itemName")
                opts.append([o["type"][0], RES_FIX.get(name, name), o["quantity"], o["minQuality"]])
            # 品质分段：[属性, 起始品质, 结束品质, 起始倍率, 结束倍率, 是否加法]
            mods = [[m["propertyName"], m["startQuality"], m["endQuality"], m["modifierAtStart"],
                     m["modifierAtEnd"], bool(m.get("additive"))] for m in (s.get("modifiers") or [])]
            slots.append([s["name"], opts, mods])
        # 同一任务（标题+发布方+类型）合并星系
        merged_src = {}
        for title, who, kind, systems, chance in sources.get(b["guid"], []):
            e = merged_src.setdefault((title, who, kind), [title, who, kind, set(), chance])
            e[3].update(x for x in systems.split("/") if x)
            e[4] = max(e[4], chance)
        uniq = [[ti, w, k, "/".join(sorted(sy)), ch] for ti, w, k, sy, ch in merged_src.values()]
        name = (b.get("productName") or b["tag"].replace("BP_CRAFT_", "")).replace("\xa0", " ")
        out.append(dict(
            n=name, z=_pick_zh(b, name), g=b["gear"], t=b["type"], s=b["subtype"], u=b.get("productEntityClass") or "",
            m=b.get("manufacturer") or "", sec=t["craftTimeSeconds"], d=bool(b.get("isDefault")),
            slots=slots, src=uniq[:12], nsrc=len(uniq)))

    data = dict(version=bp["version"], source=merged.get("source") or "scmdb.net", dismantle_efficiency=bp["dismantle"]["efficiency"],
                dismantle_blacklist=[x["name"] for x in bp["dismantle"]["blacklistedResources"]],
                blueprints=out, names=_names_tag(names_path))
    import os
    tmp = Path(out_path).with_name(f".{Path(out_path).stem}.{os.getpid()}.tmp")   # 先写临时文件再换，AT 开着时读到的不会是半个文件
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(out_path)
    finally:
        tmp.unlink(missing_ok=True)
    print(f"{len(out)} 份蓝图；{sum(1 for x in out if x['z'])} 份有中文名；"
          f"{sum(1 for x in out if x['src'])} 份有任务来源")


def _fetch(name):
    import urllib.request
    from ..core.net import read
    return read(urllib.request.Request(SCMDB + name, headers=UA), timeout=60)


def _names_tag(p):
    """中文名来自哪份汉化（换了汉化包就要重建）"""
    try:
        from ..update.localization import names_tag
        return names_tag(Path(p))
    except Exception:
        return str(p)


def pick_live(versions):
    """scmdb 的版本列表里挑正式服（LIVE）的最新一个：列表第一个常常是测试服 PTU（2026-10-27 发现：玩家在 4.10.2 正式服，
    制造、维科洛却用了 4.10.3-ptu 的数据）。只认正式服；一个都没有返回 None（保留现有数据，不拿测试服的顶上）"""
    live = [v for v in versions if "-live." in str(v).lower()]
    return max(live, key=_ver_key) if live else None


def _ver_key(s):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)-(\w+)\.(\d+)", str(s))
    return (tuple(int(x) for x in m.groups()[:3]), int(m.group(5))) if m else ((0,), 0)


def latest_live(files):
    """本地 scmdb 文件里挑正式服的最新一个（按版本号排，不按文件名字母排）；没有正式服的返回 None"""
    live = [f for f in files if "-live." in Path(f).name.lower()]
    return max(live, key=_ver_key) if live else None


def live_version(path):
    """crafting_blueprints-4.10.2-live.12913470.json → 4.10.2-live.12913470"""
    m = re.search(r"-(\d+\.\d+\.\d+-\w+\.\d+)\.json$", str(path))
    return m.group(1) if m else None


def unpacked():
    """我们自己解包出来的蓝图 + 任务文件（tools/unpack_crafting.py，2026-10-28 起优先于 scmdb）：(蓝图文件, 任务文件, 版本)；没有返回 None"""
    d = paths.data("unpack")
    bp = latest_live(d.glob("crafting_blueprints-*.json")) if d.exists() else None
    if not bp:
        return None
    merged = bp.with_name(bp.name.replace("crafting_blueprints-", "merged-"))
    return (bp, merged, live_version(bp)) if merged.exists() else None


def update():
    """重建 crafting.json：有自己解包的数据就用它；没有才去 scmdb 看有没有新版本"""
    with BUILD_LOCK:
        return _update()


def _update():
    own = unpacked()
    if own:
        bp, merged, ver = own
        out = paths.data("crafting.json")
        old = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        from ..update.localization import names_source
        if old.get("version") == ver and old.get("source") == "unpack" and old.get("names") == _names_tag(names_source()):
            print(f"制造数据已是最新（解包 {ver}）")
            return
        build(bp, merged, names_source(), out)
        from .wikelo import build as build_wikelo
        print(f"维科洛兑换：{build_wikelo(merged, names_source())} 个")
        print(f"制造数据已更新（解包 {ver}）")
        return
    ver = pick_live([v["version"] for v in json.loads(_fetch("versions.json"))])
    if not ver:
        print("scmdb 现在没有正式服（LIVE）的数据，制造数据先不动")
        return
    out = paths.data("crafting.json")
    old = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    cur = old.get("version")
    from ..update.localization import names_source
    if ver == cur and old.get("names") == _names_tag(names_source()) and all("u" in x for x in old.get("blueprints", [])[:1]):
        print(f"制造数据已是最新（{ver}）")
        return
    if ver == cur:
        print("游戏里的汉化变了，按它重建蓝图中文名…")
    raw = paths.data("scmdb")
    raw.mkdir(parents=True, exist_ok=True)
    files = []
    for name in (f"crafting_blueprints-{ver}.json", f"merged-{ver}.json"):
        if (raw / name).exists():
            files.append(raw / name)
            continue
        print(f"下载 {name} …")
        (raw / name).write_bytes(_fetch(name))
        files.append(raw / name)
    from ..update.localization import names_source
    build(files[0], files[1], names_source(), out)
    from .wikelo import build as build_wikelo
    print(f"维科洛兑换：{build_wikelo(files[1], names_source())} 个")
    print(f"制造数据已更新：{cur} → {ver}")


if __name__ == "__main__":
    if len(sys.argv) == 5:
        build(*sys.argv[1:5])
    else:
        update()
