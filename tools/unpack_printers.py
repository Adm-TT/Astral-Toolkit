"""打印机刷的东西在哪打（2026-10-27）：DCHS 计算板、密钥卡、钥匙卡这类在固定的打印机上打印。

做法：
1. 游戏数据库里的打印机（entities/scitem/gameplayinteractables/gpi_itemspawner_printcooldown_*）→ 打印什么物品；
2. 解开的星系 / 地点物件容器里找这些打印机摆在哪个容器；
3. 容器顺着 <Child name="xxx.socpak"> 往上找，一直到星系（pyrosystem 等）；到不了星系的（没摆进游戏的）不算；
4. 链上认出空间站 / 小行星基地，用汉化包里的地名（RR_P2_L4 = 死局空间站 (Checkmate) 等）。

输出 data/print_spots.json：{"items": {英文名: {"zh": 中文名, "class": 类名, "where": [地点…]}}}
用法：python tools/unpack_printers.py [records 目录] [星系容器目录] [地点容器目录]
"""
import collections
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sc_mining.update.localization import read_ini  # noqa: E402

WORK = Path(r"E:\Game3\unpack")
OUT = ROOT / "data" / "print_spots.json"
EN_INI = WORK / "p4k_out" / "Data" / "Localization" / "english" / "global.ini"
ZH_INI = ROOT / "data" / "loc" / "global_zh.ini"
SYSTEMS = {"pyrosystem", "stantonsystem", "nyxsystem"}
# 汉化组没翻、我们自己翻的词（都在 翻译对照\自译对照_词表.csv 里给老大纠错）
SELF = {"Contested Zone Rewards Room": "争夺区奖励房"}

PRINTER = re.compile(rb"gpi_itemspawner_printcooldown[a-z0-9_]*", re.I)
CHILD = re.compile(rb'<Child [^>]*?name="([^"]+?\.socpak)"', re.I)
REF = re.compile(r"libs/foundry/records/(entities/scitem/[^\"]+?\.json)")


def _loc(path):
    try:
        return {k.lower(): v for k, v in read_ini(path).items()}
    except OSError:
        return {}


def _place_name(v):
    """「焰联-监管控制站-3-4\\nPYAM-SUPVISR-3-4」→「焰联-监管控制站-3-4 (PYAM-SUPVISR-3-4)」"""
    a, _, b = v.partition("\\n")
    return f"{a.strip()} ({b.strip()})" if b.strip() else a.strip()


def printers(rec):
    """打印机名 → [物品记录文件]"""
    out = {}
    for f in sorted((rec / "entities" / "scitem" / "gameplayinteractables").glob("gpi_itemspawner_printcooldown*.json")):
        refs = sorted(set(REF.findall(f.read_text(encoding="utf-8"))))
        out[f.stem.lower()] = [rec / r for r in refs if "gameplayinteractables" not in r]
    return out


def item_name(f, en, zh):
    try:
        d = json.loads(f.read_text(encoding="utf-8"))["_RecordValue_"]
    except (OSError, ValueError, KeyError):
        return None, None
    for c in d.get("Components") or []:
        if c and c.get("_Type_") == "SAttachableComponentParams":
            k = (((c.get("AttachDef") or {}).get("Localization") or {}).get("Name") or "").lstrip("@").lower()
            return (en.get(k) or "").split("\\n")[0].strip() or None, (zh.get(k) or "").split("\\n")[0].strip() or None
    return None, None


def scan(roots):
    """(打印机 → {摆放容器}, 子容器 → {父容器})"""
    files = [f for r in roots if r.exists() for f in r.rglob("*")
             if f.is_file() and f.suffix.lower() in (".soc", ".xml") and not f.name.endswith("_editor.xml")]

    def one(f):
        try:
            b = f.read_bytes()
        except OSError:
            return f, set(), set()
        hits = {m.group(0).decode().lower() for m in PRINTER.finditer(b)}
        kids = set()
        if f.suffix.lower() == ".xml":
            kids = {PurePosixPath(m.group(1).decode(errors="replace").replace("\\", "/")).stem.lower() for m in CHILD.finditer(b)}
        return f, hits, kids

    placed, parents = collections.defaultdict(set), collections.defaultdict(set)
    with ThreadPoolExecutor(32) as ex:
        for f, hits, kids in ex.map(one, files):
            cont = f.parent.name.lower().removesuffix(".socpak") if f.suffix.lower() == ".soc" else f.stem.lower()
            for k in kids:
                parents[k].add(f.stem.lower())
            for h in hits:
                placed[h].add(cont)
    return placed, parents


def chains(n, parents, seen=()):
    ps = parents.get(n)
    if not ps or n in seen or len(seen) > 12:
        return [[n]]
    return [[n] + c for p in sorted(ps) for c in chains(p, parents, seen + (n,))]


def site(chain, zh, en):
    """一条容器链 → 地名；认不出返回 None"""
    room = chain[0]
    kind = ""
    if "cz_rewards" in room:
        kind = " " + SELF["Contested Zone Rewards Room"]
    elif "contestedzone" in room or "opendungeon" in room:
        kind = " " + _place_name(zh.get("contestedzone") or en.get("contestedzone") or "Contested Zone")
    asteroid = any(c.startswith("ab_") for c in chain)
    for c in chain:
        key = None
        m = re.fullmatch(r"rs_ext_pyro(\d)_l(\d)", c)
        if m:
            key = f"rr_p{m[1]}_l{m[2]}"
        m = m or re.fullmatch(r"rs_ext_pyro(\d)_leo", c)
        if m and not key:
            key = f"rr_p{m[1]}"
        m2 = re.fullmatch(r"pyro(\d)_l(\d)", c)
        if not key and m2 and asteroid:
            key = f"asteroidbase_p{m2[1]}_l{m2[2]}"
        if key:
            v = zh.get(key) or en.get(key)
            return _place_name(v) + kind if v else None
    return None


def main():
    rec = Path(sys.argv[1]) if len(sys.argv) > 1 else WORK / "dcb_json" / "libs" / "foundry" / "records"
    roots = [Path(a) for a in sys.argv[2:4]] or [WORK / "oc_x", WORK / "loc_x"]
    en, zh = _loc(EN_INI), _loc(ZH_INI)
    prn = printers(rec)
    placed, parents = scan(roots)
    items, odd = {}, []
    for p, files in prn.items():
        where = set()
        for cont in placed.get(p, ()):
            for c in chains(cont, parents):
                if c[-1] not in SYSTEMS:
                    continue                       # 没摆进星系（没上线的）
                s = site(c, zh, en)
                if s:
                    where.add(s)
                else:
                    odd.append(" ← ".join(c))
        if not where:
            continue
        for f in files:
            n_en, n_zh = item_name(f, en, zh)
            if not n_en:
                continue
            it = items.setdefault(n_en, {"zh": n_zh, "class": f.stem, "where": []})
            it["where"] = sorted(set(it["where"]) | where)
    OUT.write_text(json.dumps({"_说明": "打印机打印的物品 → 在哪打印（tools/unpack_printers.py 从解包生成）", "items": items},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in sorted(items.items()):
        print(f"  {v['zh'] or k}（{k}）：{'；'.join(v['where'])}")
    for o in sorted(set(odd)):
        print("  ⚠ 认不出地名：", o)
    print(f"打印物品 {len(items)} 种 → {OUT}")


if __name__ == "__main__":
    main()
