"""从 star-citizen.wiki API（游戏 p4k 解包）拉物品清单，存成 data/wiki_items.json（1.6.48 起随程序附带）

在你电脑上：python tools\\build_wiki_items.py      → 约 2～3 分钟（127 页，每页 100 个）
每个物品记：英文名 n、类型 t、尺寸 s、厂商 mfr、游戏内部类名 cls（汉化包的键名里也有，按它把汉化包的英文名对到 wiki 正名）、
描述 d（游戏官方中文说明，没有中文的用英文；去掉占位符）。同名多件只留一条，其余类名记在 alt 里。
中文名不从这里取（wiki 的中文字段是说明 / 占位，靠不住），中文名只信汉化包。
"""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "wiki_items.json"
API = "https://api.star-citizen.wiki/api/v2/items"
HEADERS = {"Accept": "application/json", "User-Agent": "Dubhe/1.0 (+star citizen mining assistant)"}


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=40) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def clean(d):
    d = (d or "").replace("\r", "").strip()
    d = re.sub(r"\n{3,}", "\n\n", d)
    return "" if d.startswith("<=") or d.startswith("(PH)") else d[:500]


def main():
    seen, out, page, t0, ver = {}, [], 1, time.time(), ""
    while True:
        d = get(f"{API}?limit=100&page={page}")
        for x in d["data"]:
            n = (x.get("name") or "").strip()
            ver = ver or x.get("version") or ""
            if not n or (re.fullmatch(r"[a-z0-9_]+", n) and "_" in n):      # 内部占位名：mount_gimbal_mining_golem
                continue
            desc = x.get("description") or {}
            e = {"n": n, "t": x.get("type") or x.get("classification") or "", "s": x.get("size"),
                 "mfr": (x.get("manufacturer") or {}).get("name") or "", "cls": (x.get("class_name") or "").lower(),
                 "d": clean(desc.get("zh_CN")) or clean(desc.get("en_EN"))}
            k = n.lower()
            if k in seen:
                seen[k].setdefault("alt", []).append(e["cls"])
                if not seen[k]["d"] and e["d"]:
                    seen[k]["d"] = e["d"]
                continue
            seen[k] = e
            out.append(e)
        if page >= d["meta"]["last_page"]:
            break
        page += 1
        if page % 20 == 0:
            print(f"{page}/{d['meta']['last_page']} {time.time() - t0:.0f}s", flush=True)
    OUT.write_text(json.dumps({"version": ver, "source": "star-citizen.wiki", "fetched": time.strftime("%Y-%m-%d"), "items": out},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"写入 {OUT}：{len(out)} 个物品，{sum(1 for e in out if e['d'])} 个有描述，版本 {ver}，用时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
