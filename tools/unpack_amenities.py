"""地点有什么设施（2026-10-27，导航「医院 / 空港 / 买船」找最近的用）：游戏星图记录（starmap/pu/**）里的 amenities
→ data/place_amenities.json：[{"en", "zh", "kinds": [医院, 空港, 买船], "ref": 导航目标}]
ref：{"poi": 星图地点名} / {"point": 星图里的点（拉格朗日点、跳跃点）} / {"body": 星球（绕行星轨道的站）} / {"city": 城市}
（starmap.space 的星图里没有休息站本身，只有它们所在的拉格朗日点 / 跳跃点；记录名 rr_arc_l1 = ARC L1）
用法：python tools/unpack_amenities.py [records 目录]"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sc_mining.localization import read_ini  # noqa: E402

WORK = Path(r"E:\Game3\unpack")
EN_INI = WORK / "p4k_out" / "Data" / "Localization" / "english" / "global.ini"
ZH_INI = ROOT / "data" / "loc" / "global_zh.ini"
OUT = ROOT / "data" / "place_amenities.json"
# 游戏的设施种类（starmapamenitytypes 的 name）→ 导航的三类
KINDS = {"Hospital": "医院", "Clinic": "医院",
         "Hangar S": "空港", "Hangar M": "空港", "Hangar L": "空港", "Hangar XL": "空港",
         "Landing Pad S": "空港", "Landing Pad M": "空港", "Landing Pad L": "空港", "Landing Pad XL": "空港",
         "Buy Vehicles": "买船", "Buy and Rent Vehicles": "买船"}
LAG = {"arc": "ARC", "cru": "CRU", "hur": "HUR", "mic": "MIC"}
JUMP = {"stantonpyro": "Stanton-Pyro Jump Point", "stantonterra": "Jumppoint Terra", "stantonmagnus": "Jumppoint Magnus",
        "pyrostanton": "Pyro-Stanton Jump Point", "pyronyx": "Pyro - Nyx Jump Point", "nyxpyro": "Jumppoint_Nyx_Pyro",
        "nyxcastra": "Nyx - Castra Jump Point"}
# 星门站本身在星图里的编号（站离跳跃点 40–52 km，按跳跃点导航「最近医院」会差这么多，2026-10-30）。
# 星门站的名字各星系重名（两个 Nyx Gateway……），只能按编号找；老版本 AT 不认编号，照旧用 point
GATEWAY = {"stantonpyro": "LOC_rs_ext_stan-pyro_jp1", "stantonterra": "LOC_rs_ext_stan-terra_jp1",
           "stantonmagnus": "LOC_rs_ext_stan-magnus_jp1", "pyrostanton": "rs_ext_pyro-stan_jp1",
           "pyronyx": "rs_ext_pyro-nyx_jp", "nyxpyro": "rs_ext_nyx-pyro_jp1", "nyxcastra": "rs_ext_nyx-castra_jp1"}
ORBIT = {"hur": "Hurston", "arc": "ArcCorp", "cru": "Crusader", "mic": "Microtech",
         "p1": "Pyro1", "p2": "Monox", "p3": "Bloom", "p4": "Pyro4", "p5": "Pyro5", "p6": "Terminus"}
LEO_PLANET = {"hur": "stanton1", "cru": "stanton2", "arc": "stanton3", "mic": "stanton4"}   # 星球的物件容器
_LEO = {}


def leo_local(code):
    """绕星球轨道的站在星球容器里的位置（千米，和星图地点的 x/y/z 一样是相对星球的）：
    Everus Harbor 这种星图地点表里没有的，靠它定位（二审 2026-10-27）"""
    stem = LEO_PLANET.get(code)
    if not stem:
        return None
    if not _LEO:
        try:
            sys.path.insert(0, str(ROOT / "tools"))
            import unpack_city
            _LEO["idx"] = unpack_city.index([WORK / "city_x", WORK / "oc_x"])
        except Exception as e:
            print(f"⚠ 读不到星球容器（{e}），轨道站只按名字找")
            _LEO["idx"] = {}
    f = _LEO["idx"].get(stem)
    if not f:
        return None
    m = re.search(r'<Child [^>]*?name="[^"]*/rs_ext_' + code + r'-leo1\.socpak"[^>]*?pos="([^"]+)"',
                  f.read_text(encoding="utf-8", errors="ignore"), re.I)
    return [round(float(v) / 1000, 3) for v in m.group(1).split(",")] if m else None


CITY = {"nyx_levski": "Levski", "stanton1_lorville": "Lorville", "stanton2_orison": "Orison", "stanton3_area18": "Area18",
        "stanton4_newbabbage": "NewBabbage"}


def ref_of(rec, name):
    r = rec.lower()
    if r in CITY:
        return {"city": CITY[r]}
    m = re.fullmatch(r"rr_(arc|cru|hur|mic)_l(\d)", r)
    if m:
        return {"point": f"{LAG[m[1]]} L{m[2]}"}
    m = re.fullmatch(r"rr_p(\d)_l(\d)", r)
    if m:
        return {"point": f"PYR{m[1]} L{m[2]}"}
    m = re.fullmatch(r"rr_jp_(\w+)", r)
    if m and m[1] in JUMP:
        return {"point": JUMP[m[1]], "point_id": GATEWAY[m[1]]}
    m = re.fullmatch(r"rr_(hur|arc|cru|mic|p\d)_leo", r)
    if m:
        # rr_*_leo（绕星球轨道的站）：先按名字找星图地点；Everus Harbor 星图地点表里没有，用星球容器里的位置。
        # 以前给 {"body": 星球} 会指到星球中心（二审 2026-10-27）。都没有导航那边就不列
        loc = leo_local(m[1])
        return {"poi": name, "body": ORBIT[m[1]], "local": loc} if loc else {"poi": name}
    return {"poi": name}


def main():
    rec = Path(sys.argv[1]) if len(sys.argv) > 1 else WORK / "dcb_json" / "libs" / "foundry" / "records"
    types = json.loads((rec / "starmapamenitytypes" / "starmapamenitytypes.json").read_text(encoding="utf-8"))
    tname = {a["_RecordId_"]: a["name"] for a in types["_RecordValue_"]["amenityTypes"]}
    en = {k.lower(): v.split("\\n")[0].strip() for k, v in read_ini(EN_INI).items()}
    zh = {k.lower(): v.split("\\n")[0].strip() for k, v in read_ini(ZH_INI).items()}
    rows = []
    for f in sorted((rec / "starmap" / "pu").rglob("*.json")):
        if "template" in f.stem:
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))["_RecordValue_"]
        except (OSError, ValueError, KeyError):
            continue
        ams = d.get("amenities") or []
        kinds = sorted({KINDS[tname[a.get("_RecordId_")]] for a in ams
                        if isinstance(a, dict) and tname.get(a.get("_RecordId_")) in KINDS})
        if not kinds:
            continue
        key = (d.get("name") or "").lstrip("@").lower()
        name = en.get(key)
        if not name or name.startswith("@") or "UNINITIALIZED" in name.upper() or "PLACEHOLDER" in name.upper():
            continue
        rows.append({"en": name, "zh": zh.get(key, ""), "kinds": kinds, "rec": f.stem, "ref": ref_of(f.stem, name)})
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    print(f"✅ 有医院 / 空港 / 买船的地点 {len(rows)} 个 → {OUT}")
    print("  ", dict(Counter(k for r in rows for k in r["kinds"])), dict(Counter(next(iter(r["ref"])) for r in rows)))


if __name__ == "__main__":
    main()
