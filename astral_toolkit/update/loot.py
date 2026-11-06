"""掉落数据更新（目录迁移 Q3 从 crafting/loot.py 拆来）：从 scl.miao.network 下物品索引写 loot_index.json
（游戏数据库的源之一：只把写文件放进更新边界，出口重建库），以及作者发布数据用的掉落明细整包抓取（crawl_details）。
下载经 infrastructure/providers/loot_site.py；整包的读、关和单件缓存在 infrastructure/persistence/loot_details.py；
查掉落在 tasks/catalog_queries/loot.py（那边只查游戏数据库，副本专属矿缺索引、联网时才经 load_index 来这里下）。
"""

import json
from pathlib import Path

from ..core.paths import DATA
from ..infrastructure.providers import loot_site

INDEX = DATA / "loot_index.json"
_index = None


def update(version=None, progress=print):
    version = (
        version
        or loot_site.latest_version()
        or (load_index(False) or {}).get("version")
        or "4.10.2LIVE"
    )
    manifest = loot_site.manifest(version)
    rows = loot_site.search_rows(version)
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


def crawl_details(out=None, workers=16, progress=print):
    """作者发布数据用：全速下载当前版本所有物品的掉落明细，打成 loot_details.zip。
    对方限流或拒绝（HTTP 429 / 403）立即停下，不硬抓；单件失败的跳过（玩家查看时现查）。返回 (成功数, 失败数, 版本)"""
    import urllib.error
    import zipfile
    from concurrent.futures import ThreadPoolExecutor

    from ..infrastructure.persistence import loot_details

    idx = update(progress=None)
    version, rows = idx["version"], idx["rows"]
    out = Path(out or loot_details.DETAILS)
    tmp = out.with_suffix(".part")
    stop: dict[str, str | None] = {"why": None}

    def one(uuid):
        if stop["why"]:
            return uuid, None
        try:
            return uuid, loot_site.item_detail_raw(version, uuid)
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
