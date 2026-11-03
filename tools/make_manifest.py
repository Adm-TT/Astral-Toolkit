"""发版本时生成在线更新用的版本说明 latest.json（不打包进安装包）

用法：
  .venv\\Scripts\\python.exe -X utf8 tools\\make_manifest.py --version 1.7.1 [--out 文件夹] "更新内容一" "更新内容二"
  .venv\\Scripts\\python.exe -X utf8 tools\\make_manifest.py --installer 路径\\AT_Setup_1.7.1.exe "更新内容一"
    （只发安装版：清单顶层不写 file；桥接安装程序 installer 保留到 1.1.4 发版后再删）
生成 latest.json。清单里带冻结的 kill_rev / disabled，只给 ≤1.1.1 老客户端看；
本工具不再联网读旧清单，也不再检查 kill_rev 一致性。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from astral_toolkit.update import update_check  # noqa: E402


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    rest, installer, version, out_dir = list(argv), None, None, None
    for flag in ("--installer", "--version", "--out"):
        if flag in rest:
            i = rest.index(flag)
            if i + 1 >= len(rest):
                print(f"❌ {flag} 后面要跟值")
                return 1
            val = rest[i + 1]
            del rest[i : i + 2]
            if flag == "--installer":
                installer = Path(val)
            elif flag == "--version":
                version = val
            else:
                out_dir = Path(val)
    if "--fresh" in rest:
        print(
            "❌ --fresh 已删除：清单里的 kill_rev / disabled 是冻结常量，不再读网上旧清单"
        )
        return 1
    if any(a.lower().endswith(".zip") for a in rest):
        print("❌ 不再支持 Dubhe_*.zip：压缩包版已退役")
        return 1
    if not installer and not version:
        print("❌ 至少要给 --version x.y.z 或 --installer AT_Setup_x.y.z.exe")
        return 1
    try:
        m = update_check.make_manifest(notes=rest, installer=installer, version=version)
    except ValueError as e:
        print(f"❌ {e}")
        return 1
    update_check.parse(json.dumps(m), velopack=True)
    if installer:
        update_check.parse(json.dumps(m), frozen=True, velopack=False)
    out = (
        out_dir
        or (
            installer.parent
            if installer
            else Path(__file__).resolve().parent.parent / "dist"
        )
    ) / "latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(m, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"✅ 已生成 {out}")
    print(json.dumps(m, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
