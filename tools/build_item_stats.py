"""把可制造物品的成品基础数值从 star-citizen.wiki API（游戏 p4k 解包数据）拉下来，存成 data/item_stats.json

在你电脑上：python tools\\build_item_stats.py            → 全部可制造物品（约 1600 个，几分钟）
            python tools\\build_item_stats.py 3bcde69d-…  → 只拉这几个 uuid（调试）
玩家不联网：这是构建步骤，结果随程序附带。按 uuid 存，和 scmdb 蓝图的 productEntityClass 对得上。
每个物品记：名字、尺寸、等级、类别、类型、厂商，以及各属性数据段原样（durability / shield / mining_laser / suit_armor …），
制造页按 scmdb 的 property_key 到这些数据段里取基础值。
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "item_stats.json"
API = "https://api.star-citizen.wiki/api/v2/items"
HEADERS = {"Accept": "application/json", "User-Agent": "Dubhe/1.0 (+star citizen mining assistant)"}


def get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except Exception as e:                     # 网络抖一下：等一会再试  # noqa: F841
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


KEEP = ("durability", "shield", "mining_laser", "vehicle_weapon", "personal_weapon", "suit_armor", "clothing",
        "temperature_resistance", "radiation_resistance", "gforce_resistance", "cooler", "power_plant", "quantum_drive",
        "ammunition", "magazine", "distortion", "emission", "temperature", "radar", "tractor_beam", "salvage_head", "fuel")


def pick(d):
    """只留和属性有关的数据段，原样存（属性对应关系在程序里做，不在这里猜）"""
    secs = {k: d[k] for k in KEEP if isinstance(d.get(k), dict) and d[k]}
    for k, v in d.items():                      # 没列到的、但看着像属性的数据段也留下（下次核对）
        if k not in secs and isinstance(v, dict) and v and k not in (
                "description", "dimension", "manufacturer", "entity_tag_map", "uex_prices", "base_variant", "blueprint",
                "inventory", "resource_network", "variants", "images", "shops", "interactions", "link"):
            secs[k] = v
    return {"n": d.get("name"), "size": d.get("size"), "grade": d.get("grade"), "cls": d.get("class"),
            "type": d.get("type"), "sub": d.get("sub_type"), "mass": d.get("mass"), "ver": d.get("version"),
            "mfr": (d.get("manufacturer") or {}).get("name"), "s": secs}


def main(argv):
    out = {}
    if argv:
        uuids = argv
    else:
        uuids, page = [], 1
        while True:
            l = get(f"{API}?limit=100&page={page}&filter[is_craftable]=1")  # noqa: E741
            uuids += [x["uuid"] for x in l["data"]]
            if page >= l["meta"]["last_page"]:
                break
            page += 1
        print(f"可制造物品 {len(uuids)} 个", flush=True)
    t0 = time.time()
    for i, u in enumerate(uuids, 1):
        try:
            d = get(f"{API}/{u}")["data"]
            out[u] = pick(d)
        except Exception as e:
            out[u] = {"err": repr(e)}
        if i % 100 == 0:
            print(f"{i}/{len(uuids)} {time.time() - t0:.0f}s", flush=True)
    ver = next((v["ver"] for v in out.values() if v.get("ver")), "")
    OUT.write_text(json.dumps({"version": ver, "source": "star-citizen.wiki", "fetched": time.strftime("%Y-%m-%d"), "items": out},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    bad = sum(1 for v in out.values() if "err" in v)
    print(f"写入 {OUT}：{len(out)} 个，出错 {bad}，版本 {ver}，用时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main(sys.argv[1:])
