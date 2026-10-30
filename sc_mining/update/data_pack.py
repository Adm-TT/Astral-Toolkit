"""数据包（2026-10-26 用户定）：矿价、制造蓝图、维科洛兑换、星图、商店、掉落等数据由作者整理好放到 Gitee，玩家「更新数据」时从 Gitee 下载，
国内也能稳定下载；数据和程序版本分开发布（更新数据不用发新版本）。

- 先读自己服务器（dl.astral-trade.com，2026-10-27）上的 data.json，再试国内镜像（COS，2026-10-29）、Gitee、GitHub，版本比本地新就下载数据包、核对大小和 SHA-256，只解出下面列的文件
- 三处都连不上：返回 None，调用方改从各数据网站直接更新（和以前一样）
- 汉化包不在数据包里：SC汉化盒子本来就是国内服务器，照旧直接下载
- 作者用 tools/make_data_pack.py 生成数据包和 data.json

data.json：{"version": "2026.10.26-1310", "date": "2026-10-26", "game": "4.10.2",
            "file": "AT_data_2026.10.26-1310.zip", "size": 123, "sha256": "…",
            "urls": ["https://gitee.com/…/AT_data_….zip", "https://github.com/…/AT_data_….zip"],
            "loot": {"version": "4.10.2LIVE", "file": "AT_loot_4.10.2LIVE.zip", "size": …, "sha256": "…", "urls": […]}}
"""
import hashlib
import json
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

from ..core.paths import DATA
from . import update_check as U

# 数据包里的文件（都在 data/ 下）：都是从国外网站下载或用它们生成的
FILES = ("prices.json", "shops.json", "crafting.json", "wikelo.json", "starmap.json", "loot_index.json",
         "item_stats.json", "wiki_items.json", "ship_signatures.json", "mining_rocks.json", "mining_spots.json", "starmap_fixes.json", "city_places.json",
         "zh_only_names.json", "ship_items.json", "print_spots.json", "place_amenities.json", "places_extra_zh.json",
         "station_lifts.json")   # 解包：雷达石头表、挖矿点、星图改正、城里目的地（2026-10-27）
STAMP = DATA / "data_pack.json"            # 本地数据包版本（随数据一起，升级装回安装包里的数据时也一起装回）
NAME = re.compile(r"^AT_data_[\w.-]+\.zip$")
LOOT_NAME = re.compile(r"^AT_loot_[\w.-]+\.zip$")
MAX_BYTES = 120 * 2 ** 20


def manifest_urls():
    out = []
    if U.OWN:
        out.append((U.OWN_NAME, f"https://{U.OWN}/data.json"))
    if U.COS:
        out.append((U.COS_NAME, f"https://{U.COS}/data.json"))
    if U.GITEE:
        out.append(("Gitee", f"https://gitee.com/{U.GITEE}/raw/master/data.json"))
    if U.GITHUB:
        out.append(("GitHub", f"https://raw.githubusercontent.com/{U.GITHUB}/main/data.json"))
    return out


def local_version():
    try:
        return json.loads(STAMP.read_text(encoding="utf-8")).get("version", "")
    except (OSError, ValueError):
        return ""


def parse(raw):
    d = json.loads(raw)
    v, name, sha = str(d.get("version") or ""), str(d.get("file") or ""), str(d.get("sha256") or "").lower()
    if not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}(-\d{4})?", v) or not NAME.match(name) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("数据包信息不完整")
    urls = [u for u in d.get("urls") or [] if isinstance(u, str) and U._host_ok(u)]
    if not urls:
        raise ValueError("没有可用的下载地址")
    out = {"version": v, "date": str(d.get("date") or ""), "game": str(d.get("game") or ""), "file": name,
           "size": int(d.get("size") or 0), "sha256": sha, "urls": urls, "loot": None}
    lt = d.get("loot")                      # 掉落明细整包（可选，单独一个文件：只在游戏版本变了才需要重下）
    if isinstance(lt, dict):
        lname, lsha = str(lt.get("file") or ""), str(lt.get("sha256") or "").lower()
        lurls = [u for u in lt.get("urls") or [] if isinstance(u, str) and U._host_ok(u)]
        if LOOT_NAME.match(lname) and re.fullmatch(r"[0-9a-f]{64}", lsha) and lurls and lt.get("version"):
            out["loot"] = {"version": str(lt["version"]), "file": lname, "size": int(lt.get("size") or 0),
                           "sha256": lsha, "urls": lurls}
    return out


def fetch(timeout=8):
    """读 data.json：几处同时问，取版本最新的一份（Codex 2026-10-27）。(info, None) 或 (None, 原因)"""
    errs, best = [], None
    for where, raw in U._fetch_all(manifest_urls(), timeout):
        try:
            if isinstance(raw, Exception):
                raise raw
            info = parse(raw)
            info["source"] = where
            if best is None or info["version"] > best["version"]:
                best = info
        except Exception as e:
            errs.append(f"{where}：{e}")
    if best:
        return best, None
    return None, "；".join(errs) or "未设置数据包地址"


def _download(info, dest, progress):
    errs = []
    for url in info["urls"]:
        where = U.where(url)
        try:
            progress(f"正在下载数据包（{where}）…")
            h, n = hashlib.sha256(), 0
            with U._open(url, 30) as r, open(dest, "wb") as f:
                while True:
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    n += len(chunk)
                    if n > MAX_BYTES:
                        raise ValueError("文件大小异常")
                    h.update(chunk)
                    f.write(chunk)
            if info["size"] and n != info["size"]:
                raise ValueError("文件大小不符，下载不完整")
            if h.hexdigest() != info["sha256"]:
                raise ValueError("文件校验不符")
            return
        except Exception as e:
            errs.append(f"{where}：{e}")
            progress(f"{where} 下载失败：{e}")
    raise ValueError("；".join(errs))


CACHE_HOOKS = []          # 别的模块（tasks.goals、tasks.navigation，import 时）登记自己的清缓存函数：data_pack.CACHE_HOOKS.append(fn)


def clear_caches():
    """数据文件换了之后把各模块的内存缓存清掉（2026-10-28 审查：更新数据后制造 / 维科洛 / 库存地点 / 物品属性重启前都是旧的）"""
    def _clear(mod, *names):
        try:
            m = __import__(f"sc_mining.{mod}", fromlist=names)
            for n in names:
                f = getattr(m, n, None)
                if hasattr(f, "cache_clear"):
                    f.cache_clear()
        except Exception:
            pass
    from ..core import paths
    paths.clear_json_cache()
    _clear("trade.names", "table", "_index")
    _clear("crafting", "data", "_keys")
    _clear("crafting.wikelo", "load")
    _clear("crafting.stockplaces", "places", "_index")
    _clear("mining.laser", "head_blueprint", "craft_slots")
    _clear("crafting.itemstats", "data")
    _clear("mining.shipsig", "ships")
    try:
        from ..crafting import loot
        loot._index = None                        # 掉落索引
        loot._folded.update(of=None, rows=[])
    except Exception:
        pass
    try:
        from ..mining import data
        from . import uex
        uex.apply_live(data)                      # 矿价 / 精炼站加成（prices.json）→ 内置表（2026-10-28 整体审查：以前窗口从没读过它）
    except Exception:
        pass
    _clear("crafting.goals", "where_to_get")
    try:
        from ..crafting import shops
        shops._data = None                        # 商店表（shops.load 只在 _data 为 None 时读文件）
    except Exception:
        pass
    for fn in list(CACHE_HOOKS):
        try:
            fn()
        except Exception:
            pass


def install(zip_path, info=None):
    """把数据包里列在 FILES 的文件装进 data/（先全部解到临时目录、检查是合法 JSON，再逐个替换）。返回装了几个。
    每个文件记一行账（原来有没有、备份在哪、换上没）；中途出错按账本回退：原来有的换回备份，原来没有的删掉；
    回退也没成的文件，备份留在临时目录里不删、报错时写明路径（老大审查 2026-10-28 第 4 条）"""
    tmp = Path(tempfile.mkdtemp(prefix="at_data_"))
    keep = False
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = {Path(n).name: n for n in z.namelist() if not n.endswith("/")}
            got = [f for f in FILES if f in names]
            if not got:
                raise ValueError("数据包里没有数据文件")
            for f in got:
                (tmp / f).write_bytes(z.read(names[f]))
                json.loads((tmp / f).read_text(encoding="utf-8"))      # 坏文件不装
        DATA.mkdir(parents=True, exist_ok=True)
        from ..crafting.build_crafting import BUILD_LOCK
        with BUILD_LOCK:                          # 和汉化包重建制造表不同时写同一批文件（二审 2026-10-28）
            table = {f: {"existed": (DATA / f).exists(), "backup": None, "replaced": False} for f in got}
            try:
                for f in got:
                    row = table[f]
                    if row["existed"]:
                        shutil.copyfile(DATA / f, tmp / f"{f}.old")
                        row["backup"] = tmp / f"{f}.old"
                    shutil.copyfile(tmp / f, DATA / f".{f}.new")
                    _replace_retry(DATA / f".{f}.new", DATA / f)
                    row["replaced"] = True
            except Exception as e:
                failed = _restore(table, got)
                try:
                    clear_caches()                # 换回去的也要让程序重读
                except Exception:
                    pass
                if failed:
                    keep = True                   # 没换回去的文件，备份留着别删
                    raise ValueError(f"数据装到一半出错（{e}），其中 {len(failed)} 个文件没能换回旧的（{'、'.join(failed[:3])}），"
                                     f"旧文件留在 {tmp}，再点一次「更新数据」通常能修好") from e
                raise
        if info:
            STAMP.write_text(json.dumps({k: info.get(k) for k in ("version", "date", "game")}, ensure_ascii=False), encoding="utf-8")
        clear_caches()                          # 新数据马上生效，不用重启（2026-10-28 审查：以前只清了中英对照表）
        return len(got)
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)


def _replace_retry(src, dst):
    """换名：被别的线程读着时会失败，稍等再试（和 paths.write_json 一样）"""
    import time as _t
    for i in range(6):
        try:
            src.replace(dst)
            return
        except PermissionError:
            if i == 5:
                raise
            _t.sleep(0.05)


def _restore(table, order):
    """按账本回退：换上了的——原来有的换回备份、原来没有的删掉。返回没回退成的文件名"""
    failed = []
    for f in reversed(order):
        row = table[f]
        if not row["replaced"]:
            continue
        try:
            if row["existed"]:
                shutil.copyfile(row["backup"], DATA / f".{f}.back")
                _replace_retry(DATA / f".{f}.back", DATA / f)
                if (DATA / f).stat().st_size != Path(row["backup"]).stat().st_size:
                    raise OSError("换回去的大小不对")
            else:
                (DATA / f).unlink()
        except OSError:
            failed.append(f)
    for f in order:                               # 没换上的 .new / .back 半成品：清掉
        for tail in (".new", ".back"):
            try:
                (DATA / f".{f}{tail}").unlink()
            except OSError:
                pass
    return failed


def _update_loot(info, progress):
    """掉落明细整包：本地版本和数据包里的不一样才下载（约 25 MB），下载后检查是压缩包、版本对得上再替换"""
    from ..crafting import loot
    lt = info.get("loot")
    if not lt:
        return
    cur = loot.details_version()
    if cur == lt["version"]:
        return
    tmp = Path(tempfile.mkdtemp(prefix="at_lootdl_"))
    try:
        z = tmp / lt["file"]
        _download(lt, z, progress)
        if loot.details_version(z) != lt["version"]:
            raise ValueError("掉落明细整包版本不符")
        DATA.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(z, DATA / ".loot_details.zip.new")
        loot.close_bundle()                     # Windows：正在读的文件不能替换
        (DATA / ".loot_details.zip.new").replace(loot.DETAILS)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    progress(f"掉落明细已更新：{cur or '无'} → {lt['version']}")


def update(progress=print):
    """「更新数据」：从 AT 服务器 / Gitee / GitHub 下数据包。返回 True = 已是最新或已更新；None = 连不上数据包地址（调用方改从各网站更新）。
    数据包本身坏了（校验不符等）抛 ValueError"""
    info, err = fetch()
    if not info:
        progress(f"⚠️ 数据包无法下载（{err}），改从各数据网站更新")
        return None
    cur = local_version()
    if cur and cur > info["version"]:                # 网上的比本地还旧：掉落整包也别跟着退回去（Codex 2026-10-27）
        progress(f"数据已是最新（数据包 {cur}）")
        return True
    if cur and cur == info["version"]:
        progress(f"数据已是最新（数据包 {cur}）")
    else:
        tmp = Path(tempfile.mkdtemp(prefix="at_datadl_"))
        try:
            z = tmp / info["file"]
            try:
                _download(info, z, progress)
            except Exception as e:                # 附件下不到（国内连 GitHub 附件常失败）：和 data.json 读不到一样，退回各网站直连
                progress(f"⚠️ 数据包下载失败（{e}），改从各数据网站更新")
                return None
            n = install(z, info)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        progress(f"数据包已更新：{cur or '无'} → {info['version']}（{n} 个文件{('，游戏版本 ' + info['game']) if info['game'] else ''}）")
    try:
        _update_loot(info, progress)
    except Exception as e:                      # 掉落明细没下成：查看掉落时照旧现查，不算数据包失败
        progress(f"掉落明细未更新：{e}（查看掉落时改为联网查询）")
    return True


def make(out_dir, date=None):
    """作者发布数据用：把本机 data/ 里的这些文件打成数据包 + data.json。返回 (zip 路径, data.json 内容)"""
    stamp = time.strftime("%Y.%m.%d-%H%M") if date is None else date
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"AT_data_{stamp}.zip"
    zp = out_dir / name
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in FILES:
            p = DATA / f
            if p.exists():
                json.loads(p.read_text(encoding="utf-8"))
                z.write(p, f)
    try:
        from ..mining.data import GAME_VERSION
    except Exception:
        GAME_VERSION = ""
    tag = f"data-{stamp}"
    urls = U.release_urls(tag, name)
    m = {"version": stamp, "date": stamp[:10].replace(".", "-"), "game": GAME_VERSION, "file": name,
         "size": zp.stat().st_size, "sha256": U._sha256(zp), "urls": urls}
    from ..crafting import loot
    lv = loot.details_version()
    if lv:                                      # 掉落明细整包：单独一个文件，和数据包放在同一个发行版里
        lname = f"AT_loot_{lv}.zip"
        shutil.copyfile(loot.DETAILS, out_dir / lname)
        m["loot"] = {"version": lv, "file": lname, "size": (out_dir / lname).stat().st_size,
                     "sha256": U._sha256(out_dir / lname), "urls": [u.rsplit("/", 1)[0] + "/" + lname for u in urls]}
    parse(json.dumps(m))
    STAMP.write_text(json.dumps({k: m[k] for k in ("version", "date", "game")}, ensure_ascii=False), encoding="utf-8")
    return zp, m
