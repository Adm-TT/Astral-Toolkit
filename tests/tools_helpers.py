"""test_tools_*.py 几个文件共用的造数据帮手（从 test_tools.py 拆出，CL-C3）。不是测试文件，run_all 不跑它"""

import json


def _shops_db(monkeypatch, tmp_path, data, starmap=None, copy=()):
    """商店查询走游戏数据层（批 1）：把假商店表写成 shops.json、在临时目录建库，只把库目录指过去；
    paths.DATA 不动（别的数据照旧读真实 data/）。
    starmap：假星图（批 2 起 find_point 走库），给了就一起写成 starmap.json 建进库；copy：再拷进去一起建库的源文件"""
    from astral_toolkit import gamedata
    from astral_toolkit.core import paths
    from astral_toolkit.gamedata import _build, _paths, _ready

    src = tmp_path / "gamedata_src"
    src.mkdir(exist_ok=True)
    (src / "shops.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    if starmap is not None:
        (src / "starmap.json").write_text(
            json.dumps(starmap, ensure_ascii=False), encoding="utf-8"
        )
    for f in copy:
        (src / f.name).write_bytes(f.read_bytes())
    for name in (
        "crafting.json",
        "wikelo.json",
        "item_stats.json",
        "print_spots.json",
        "ship_items.json",
    ):  # 制造 / 维科洛 / 物品属性也走库了（批 3）：这几份照旧用真实 data/ 的（没有就缺着，和以前读不到文件一样）
        if (paths.DATA / name).exists():
            (src / name).write_bytes((paths.DATA / name).read_bytes())
    monkeypatch.setattr(_paths, "gamedata_dir", lambda: src / "gamedata")
    monkeypatch.setattr(
        _build, "gamedata_dir", lambda: src / "gamedata"
    )  # _build 在 import 时绑了名字：清理旧库的 glob 不能扫到真实 data/gamedata（控制台复审第 11 条）
    real = paths.DATA
    paths.DATA = src  # 只在建库这一下读临时目录的源
    try:
        gamedata.rebuild()
    finally:
        paths.DATA = real
    # 记成已核对：查询时 ensure() 会按 paths.DATA（真实 data/）的源核对，别拿真实源把临时库重建掉
    monkeypatch.setattr(_ready, "_state", {"done": str(src / "gamedata")})
