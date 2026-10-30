"""发版本时生成在线更新用的版本说明 latest.json（不打包进安装包）

用法：
  .venv\\Scripts\\python.exe -X utf8 tools\\make_manifest.py dist\\Dubhe_1.7.1.zip [--installer 路径\\AT_Setup_1.7.1.exe] "更新内容一" "更新内容二"
  .venv\\Scripts\\python.exe -X utf8 tools\\make_manifest.py --installer 路径\\AT_Setup_1.7.1.exe "更新内容一"
  （压缩包版已停止维护：可以只给安装程序，清单顶层不写 file，源码版当作没有新版本；latest.json 生成在安装程序旁边）
生成 dist\\latest.json（--installer：同一版本的独立安装程序，安装版在线升级用；1.7.0 起每次都带）。发布步骤：
  1. 在 Gitee、GitHub 的仓库各建一个发行版，标签 v1.7.1，上传 Dubhe_1.7.1.zip 和 AT_Setup_1.7.1.exe
  2. 把 latest.json 提交到两个仓库的根目录（Gitee 是 master 分支，GitHub 是 main 分支）
  玩家的 AT 读到新的 latest.json 就会提示新版本。先传安装包、再更新 latest.json，顺序不能反
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sc_mining import update_check  # noqa: E402


def current_online():
    """三处里 (kill_rev, 版本) 最大的那份 latest.json；都读不到返回 None"""
    from sc_mining.upgrade import ver
    best = None
    for _, raw in update_check._fetch_all(update_check.manifest_urls(), 8):
        try:
            d = json.loads(raw)
            key = (update_check._rev(d.get("kill_rev")), ver(str(d.get("version") or "")))
        except Exception:
            continue
        if "disabled" in d and not isinstance(d["disabled"], list):
            raise SystemExit("❌ 网上有一份 latest.json 的 disabled 不是列表（应写成 [ {...} ]），先改好再生成")
        if key[1] != (0, 0, 0) and (best is None or key > best[0]):
            best = (key, d)
    return best[1] if best else None


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    if not update_check.enabled():
        print("❌ sc_mining/update_check.py 里的 GITEE / GITHUB 仓库地址还没填")
        return 1
    rest, installer = list(argv), None
    if "--installer" in rest:
        i = rest.index("--installer")
        installer = Path(rest[i + 1])
        del rest[i:i + 2]
    zip_path = Path(rest.pop(0)) if rest and rest[0].lower().endswith(".zip") else None
    if zip_path is None and installer is None:
        print("❌ 至少要给 Dubhe_x.y.z.zip 或 --installer AT_Setup_x.y.z.exe")
        return 1
    fresh = "--fresh" in rest
    rest = [a for a in rest if a != "--fresh"]
    keep = None if fresh else current_online()
    if keep is None and not fresh:
        print("❌ 读不到网上现在的 latest.json（要把远程关功能的 disabled / kill_rev 带上）。确定网上没有再加 --fresh")
        return 1
    if keep and keep.get("disabled"):
        print(f"带上远程关功能：kill_rev={keep.get('kill_rev', 0)}，{json.dumps(keep['disabled'], ensure_ascii=False)}")
    if zip_path and installer and installer.resolve().parent != zip_path.resolve().parent:
        import shutil                                  # 发布脚本按清单旁边找文件：桥接安装程序复制到压缩包旁边
        shutil.copy2(installer, zip_path.parent / installer.name)
        side = installer.with_suffix(".sha256")          # 桥接程序要下载的 AT-win-Setup.exe 的校验，发布前核对用
        if side.exists():
            shutil.copy2(side, zip_path.parent / side.name)
        installer = zip_path.parent / installer.name
    m = update_check.make_manifest(zip_path, notes=rest, installer=installer, keep=keep)
    if zip_path:                                       # 生成的文件自己先过一遍检查：源码版那一项
        update_check.parse(json.dumps(m), frozen=False)
    if installer:                                      # 安装版那一项
        update_check.parse(json.dumps(m), frozen=True)
    out = (zip_path or installer).parent / "latest.json"
    out.write_text(json.dumps(m, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"✅ 已生成 {out}")
    print(json.dumps(m, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
