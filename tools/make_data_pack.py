"""发布数据包（不发新版本，不打包进安装包）：先从各数据网站直接更新本机 data/，再打成数据包 + data.json

用法（项目根目录）：
  .venv\\Scripts\\python.exe -X utf8 tools\\make_data_pack.py            先更新数据再打包
  .venv\\Scripts\\python.exe -X utf8 tools\\make_data_pack.py --no-update  用本机现有数据直接打包
  游戏版本变了（掉落数据有新版本）时会自动全速抓一遍掉落明细（约 1.3 万件，对方限流就停）；加 --no-loot 跳过
生成 dist\\data\\AT_data_<版本>.zip、AT_loot_<掉落版本>.zip（掉落明细整包）和 dist\\data\\data.json。
发布步骤（对外发布要负责人点头才跑；Gitee / GitHub 上的 data.json 已不再更新）：
  1. 生成数据包和 data.json（本脚本）
  2. tools\\publish_hk.py dist\\data\\data.json：先把数据包传到 AT 服务器和国内镜像、核对校验，最后才换 data.json
  先传数据包、再更新 data.json，顺序不能反（publish_hk.py 按这个顺序做）。玩家点「更新数据」时读到新的 data.json 就会下载
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(argv):
    from sc_mining.update import data_pack
    from sc_mining import run
    import os

    oc = (Path(os.environ.get("AT_UNPACK_DIR", r"E:\Game3\unpack")) / "oc_x").exists()
    if "--no-update" not in argv:
        # 有解包目录才去 starmap.space 下星图（下面 unpack_starmap 会重新合并，只取自转相位和玩家补充的点）；没有就别拿网站版盖掉解包版
        r = run.update(
            direct=True, web_ok=("sc_mining.navigation.navigate",) if oc else ()
        )
        bad = [x["title"] for x in r["results"] if not x["ok"]]
        if bad:
            print(f"⚠️ 这几项没更新成功，数据包里是旧数据：{'、'.join(bad)}")
    # 星图：刚从 starmap.space 下的只拿自转相位、玩家补充的点，太空点 / 星球参数 / 有星图记录的地点用自己解包的（2026-10-28）
    import subprocess
    import sys as _sys

    if oc:
        subprocess.run(
            [
                _sys.executable,
                "-X",
                "utf8",
                str(ROOT / "tools" / "unpack_starmap.py"),
                "--write",
            ],
            check=True,
        )
    from sc_mining.crafting import loot

    idx = loot.load_index(False) or {}
    if (
        "--no-loot" not in argv
        and idx.get("version")
        and loot.details_version() != idx["version"]
    ):
        # 游戏版本变了（掉落数据有新版本）：全速抓一遍所有物品的掉落明细（用户 2026-10-26 定），约 1.3 万件
        print(
            f"掉落数据有新版本 {idx['version']}（整包是 {loot.details_version() or '无'}），开始抓取掉落明细…"
        )
        try:
            loot.crawl_details()
        except RuntimeError as e:
            print(f"⚠️ {e}；这次数据包沿用旧的掉落明细整包")
    zp, m = data_pack.make(ROOT / "dist" / "data")
    out = zp.parent / "data.json"
    out.write_text(
        json.dumps(m, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"✅ 数据包：{zp}（{zp.stat().st_size / 2**20:.1f} MB）")
    print(f"✅ 版本说明：{out}")
    print(json.dumps(m, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
