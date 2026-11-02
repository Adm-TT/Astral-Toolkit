"""发布数据包（不发新版本，不打包进安装包）：先从各数据网站直接更新本机 data/，再打成数据包 + data.json

用法（项目根目录）：
  .venv\\Scripts\\python.exe -X utf8 tools\\make_data_pack.py            先更新数据再打包
  .venv\\Scripts\\python.exe -X utf8 tools\\make_data_pack.py --no-update  用本机现有数据直接打包
  游戏版本变了（掉落数据有新版本）时会自动全速抓一遍掉落明细（约 1.3 万件，对方限流就停）；加 --no-loot 跳过
  环境变量（作者电脑上设）：AT_SRC_DIR = 数据构建脚本的工作目录（里面有 oc_x），AT_DATA_TOOLS = 数据构建脚本所在目录。
  两个都不设就只用网站数据；但本机星图已是游戏数据版、又要去网站更新时会直接停下（不然网站版会盖掉它再打进数据包）
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
    from astral_toolkit.update import data_pack
    from astral_toolkit import run
    import os

    src = os.environ.get("AT_SRC_DIR") or ""
    tools = os.environ.get("AT_DATA_TOOLS") or ""
    oc = (
        bool(src and tools)
        and (Path(src) / "oc_x").exists()
        and (Path(tools) / "starmap_merge.py").exists()
    )
    from astral_toolkit.core import paths

    try:
        game_star = paths.from_game(
            json.loads(paths.data("starmap.json").read_text(encoding="utf-8"))
        )
    except (OSError, ValueError):
        game_star = False
    if (
        game_star and not oc and "--no-update" not in argv
    ):  # 不去网站更新就不会盖掉本机星图
        print(
            "❌ 本机星图是游戏数据版，但 AT_SRC_DIR / AT_DATA_TOOLS 没设好（AT_SRC_DIR 里要有 oc_x，AT_DATA_TOOLS 里要有 starmap_merge.py）："
            "继续的话网站版会盖掉它再打进数据包。设好两个环境变量再跑"
        )
        return 2
    if "--no-update" not in argv:
        # 有构建输入目录才去 starmap.space 下星图（下面数据构建脚本会重新合并，只取自转相位和玩家补充的点）；没有就别拿网站版盖掉游戏数据版
        r = run.update(
            direct=True,
            web_ok=(
                ("astral_toolkit.navigation.navigate", "astral_toolkit.navigation.starmap")
                if oc
                else ()
            ),  # navigate.update 的 __module__ 实际是 starmap：两个名字都给（收口 1）
        )
        bad = [x["title"] for x in r["results"] if not x["ok"]]
        if bad:
            print(f"⚠️ 这几项没更新成功，数据包里是旧数据：{'、'.join(bad)}")
    # 星图：刚从 starmap.space 下的只拿自转相位、玩家补充的点，太空点 / 星球参数 / 有星图记录的地点用游戏数据（2026-10-28）
    import subprocess
    import sys as _sys

    if oc:
        subprocess.run(
            [
                _sys.executable,
                "-X",
                "utf8",
                str(Path(tools) / "starmap_merge.py"),
                "--write",
            ],
            check=True,
            env={
                **os.environ,
                "AT_REPO": str(ROOT),
                "AT_SRC_DIR": src,
            },  # 合并这份仓库（不是别的签出）
        )
    from astral_toolkit.crafting import loot

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
