"""游戏更新后一键重新解包、生成 AT 用的数据并逐项核对（2026-10-27）。在作者电脑上跑（要装好游戏和 StarBreaker）：
  .venv\\Scripts\\python.exe -X utf8 tools\\unpack_all.py
步骤：从 Data.p4k 取 Game2.dcb → StarBreaker 导出 JSON → 取星系物件容器（socpak）并解开 →
生成 data/mining_rocks.json、data/mining_spots.json、data/starmap_fixes.json → 核对品质档位、飞船截面、物品/掉落、星图。
任何一步出错就停，不会写出半成品；核对有差别的会打印出来，人看过再发数据包"""

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAME = Path(os.environ.get("SC_GAME_DIR", r"D:\StarCitizen\LIVE"))
WORK = Path(os.environ.get("AT_UNPACK_DIR", r"E:\Game3\unpack"))
SB = WORK / "tools" / "starbreaker" / "starbreaker.exe"
PY = sys.executable


def run(*args, **kw):
    print("▶", " ".join(str(a) for a in args), flush=True)
    r = subprocess.run([str(a) for a in args], cwd=str(ROOT), **kw)
    if r.returncode:
        sys.exit(f"❌ 这一步失败了（退出码 {r.returncode}），停下")


def _unzip(f, d):
    """解开 socpak。游戏的 zip 目录里用 /、文件头里用 \\，Python 自带的 extractall 会报「名字不一致」，
    所以这里直接按目录读偏移、自己解压（只认「不压缩」和 deflate 两种）"""
    import struct
    import zlib

    with open(f, "rb") as fh, zipfile.ZipFile(fh) as z:
        for i in z.infolist():
            if i.is_dir():
                continue
            fh.seek(i.header_offset)
            h = fh.read(30)
            if h[:4] != b"PK\x03\x04":
                raise zipfile.BadZipFile(f"{f}: {i.filename} 文件头不对")
            n, m = struct.unpack("<HH", h[26:30])
            fh.seek(n + m, 1)
            raw = fh.read(i.compress_size)
            if i.compress_type == zipfile.ZIP_STORED:
                data = raw
            elif i.compress_type == zipfile.ZIP_DEFLATED:
                data = zlib.decompress(raw, -15)
            else:
                raise zipfile.BadZipFile(
                    f"{f}: {i.filename} 压缩方式 {i.compress_type} 不认识"
                )
            out = d / i.filename.replace("\\", "/")
            if ".." in out.relative_to(d).parts:
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)


def main():
    p4k = GAME / "Data.p4k"
    if not p4k.exists() or not SB.exists():
        sys.exit(f"❌ 找不到游戏（{p4k}）或 StarBreaker（{SB}）")
    env = {**os.environ, "SC_DATA_P4K": str(p4k)}
    dcb_dir = WORK / "dcb_json"
    shutil.rmtree(dcb_dir, ignore_errors=True)
    run(SB, "dcb", "extract", "--p4k", p4k, "-o", dcb_dir, "--format", "json", env=env)
    oc, ocx = WORK / "oc", WORK / "oc_x"
    shutil.rmtree(oc, ignore_errors=True)
    shutil.rmtree(ocx, ignore_errors=True)
    run(
        SB,
        "p4k",
        "extract",
        "-o",
        oc,
        "--regex",
        r"(?i)^Data\\ObjectContainers\\PU\\(system|asteroidcluster)\\.*\.socpak$",
        env=env,
    )
    base = oc / "Data" / "ObjectContainers" / "PU"
    for f in base.rglob("*.socpak"):
        rel = (
            f.relative_to(base / "system")
            if (base / "system") in f.parents
            else f.relative_to(base)
        )
        d = ocx / (
            "__".join(rel.with_suffix("").parts) if len(rel.parts) > 1 else rel.stem
        )
        _unzip(f, d)
    rec = dcb_dir / "libs" / "foundry" / "records"
    tools = ROOT / "tools"
    run(
        PY,
        "-X",
        "utf8",
        tools / "unpack_mining.py",
        rec,
        WORK / "mining_db.json",
        ROOT / "data" / "mining_rocks.json",
    )

    def sysx(s):
        hits = sorted(ocx.rglob(f"{s}system.xml"), key=lambda p: len(p.parts))
        if not hits:
            sys.exit(f"❌ 解开的星系文件里找不到 {s}system.xml")
        return hits[0]

    run(
        PY,
        "-X",
        "utf8",
        tools / "unpack_spots.py",
        rec / "starmap" / "pu",
        sysx("pyro"),
        sysx("nyx"),
        ROOT / "data" / "mining_spots.json",
    )
    run(PY, "-X", "utf8", tools / "unpack_starmap_check.py", ocx, "--write")
    run(
        SB,
        "p4k",
        "extract",
        "--p4k",
        p4k,
        "-o",
        WORK / "p4k_out",
        "--filter",
        "Data/Localization/english/global.ini",
        env=env,
    )  # 星图要用当前的 global.ini（老大审查 2026-10-28）
    run(
        PY, "-X", "utf8", tools / "unpack_starmap.py", "--write"
    )  # 星图整表（2026-10-28）：太空点、星球参数、有星图记录的地点
    run(
        PY,
        "-X",
        "utf8",
        tools / "unpack_quality.py",
        rec / "crafting" / "qualityquantization",
    )
    run(PY, "-X", "utf8", tools / "unpack_ships.py", rec)
    run(PY, "-X", "utf8", tools / "unpack_items_check.py", rec)
    run(
        PY, "-X", "utf8", tools / "unpack_item_names.py"
    )  # 只有中文名的物品补英文名（2026-10-27）
    run(
        PY, "-X", "utf8", tools / "unpack_crafting.py", "--compare"
    )  # 制造蓝图 + 任务 / 维科洛兑换（2026-10-28，不等 scmdb）
    run(
        PY, "-X", "utf8", tools / "unpack_items.py", "--write"
    )  # 物品清单 + 可制造成品属性（2026-10-28，不再靠 star-citizen.wiki）
    # 飞船数据包 + AT「随船自带」（2026-10-27）：飞船定义 XML 是 CryXmlB，先转成普通 XML
    vx = (
        WORK
        / "p4k_out"
        / "Data"
        / "Scripts"
        / "Entities"
        / "Vehicles"
        / "Implementations"
        / "Xml"
    )
    run(
        SB,
        "p4k",
        "extract",
        "--p4k",
        p4k,
        "-o",
        WORK / "p4k_out",
        "--filter",
        "Data/Scripts/Entities/Vehicles/Implementations/Xml/**",
        env=env,
    )
    shutil.rmtree(WORK / "vehicles_xml", ignore_errors=True)
    run(SB, "cryxml", "convert-all", "-i", vx, "-o", WORK / "vehicles_xml", env=env)
    run(PY, "-X", "utf8", tools / "unpack_ship_data.py")
    # 打印机（DCHS 计算板、密钥卡）在哪打（2026-10-27）：要派罗的地点物件容器
    loc_oc, locx = WORK / "loc_oc", WORK / "loc_x"
    shutil.rmtree(loc_oc, ignore_errors=True)
    shutil.rmtree(locx, ignore_errors=True)
    run(
        SB,
        "p4k",
        "extract",
        "--p4k",
        p4k,
        "-o",
        loc_oc,
        "--filter",
        "Data/ObjectContainers/PU/loc/mod/pyro/**/*.socpak",
        env=env,
    )
    lb = loc_oc / "Data" / "ObjectContainers" / "PU" / "loc"
    for f in lb.rglob("*.socpak"):
        _unzip(f, locx / f.relative_to(lb).with_suffix(""))
    run(PY, "-X", "utf8", tools / "unpack_printers.py", rec, ocx, locx)
    # 城里导航（四个主城 + 列夫斯基）、医院 / 空港 / 买船找最近（2026-10-27）：城市、商店、空间站、电梯的物件容器
    city_oc, cityx = WORK / "city", WORK / "city_x"
    shutil.rmtree(city_oc, ignore_errors=True)
    shutil.rmtree(cityx, ignore_errors=True)
    for flt in (
        "Data/ObjectContainers/PU/loc/flagship/**/*.socpak",
        "Data/ObjectContainers/PU/Shops/**/*.socpak",
        "Data/ObjectContainers/PU/loc/mod/common/**/*.socpak",
        "Data/ObjectContainers/PU/loc/mod/station/**/*.socpak",
        "Data/ObjectContainers/PU/loc/mod/stanton/**/*.socpak",
        "Data/ObjectContainers/Setup/elevator_setup/**/*.socpak",
        "Data/ObjectContainers/PU/**/rs_*.socpak",
        "Data/ObjectContainers/PU/**/station_ext_*.socpak",
    ):  # 空间站（2026-10-27）
        run(SB, "p4k", "extract", "--p4k", p4k, "-o", city_oc, "--filter", flt, env=env)
    cb = city_oc / "Data" / "ObjectContainers"
    for f in cb.rglob("*.socpak"):
        _unzip(f, cityx / "__".join(f.relative_to(cb).with_suffix("").parts))
    run(PY, "-X", "utf8", tools / "unpack_city.py", cityx, ocx)
    run(
        PY, "-X", "utf8", tools / "unpack_lifts.py", cityx, ocx
    )  # 空间站站内电梯、区域、机库（2026-10-28）
    run(PY, "-X", "utf8", tools / "unpack_amenities.py", rec)
    run(
        PY, "-X", "utf8", tools / "unpack_place_names.py"
    )  # 星图地名补中文（2026-10-27）
    print(
        "✅ 解包完成。上面有「不一样 / 找不到」的逐条看过，再跑 make_data_pack.py 发数据"
    )


if __name__ == "__main__":
    main()
