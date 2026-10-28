"""Velopack 安装包 + 在线更新包（2026-10-27，老大定：换 Velopack，只下载改过的部分）

用构建环境的 Python 运行（不是项目的 .venv）：
  E:\\Game3\\AT_build\\venv\\Scripts\\python.exe -X utf8 tools\\build_velopack.py [--skip-build] ["更新内容一" "更新内容二" …]

做的事：
1. build_standalone 打出 AT\\（PyInstaller + 外壳 ATShell），--skip-build 就用现成的
2. vpk pack → E:\\Game3\\AT_build\\velopack\\releases\\：
   AT-win-Setup.exe（新玩家装这个）、AT-<版本>-full.nupkg、和上一版比的增量包 AT-<版本>-delta.nupkg、releases.win.json
3. releases.prev.json：只放上一个版本的完整包（AT 设置页「回滚」用）
4. 桥接安装程序 AT_Setup_<版本>.exe（老的 Inno 安装版在线升级用，tools\\AT_bridge.iss）
发布：tools\\publish_hk.py --velopack（要老大点头）
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_standalone as B                                   # noqa: E402

VPK = B.BUILD / "tools" / "vpk" / "vpk.exe"
REL = Path(os.environ.get("AT_VPK_REL") or B.BUILD / "velopack" / "releases")   # AT_VPK_REL：沙盒测试用的另一个文件夹                         # 一直留着：做增量包要有上一版的完整包
PACK_ID = "AT"
TITLE = "AT 星际公民助手"


def version():
    return re.search(r'VERSION = "([^"]+)"', (ROOT / "sc_mining" / "version.py").read_text(encoding="utf-8")).group(1)


def _ver(s):
    return tuple(int(x) for x in re.findall(r"\d+", s)[:3])


def pack(v, notes):
    REL.mkdir(parents=True, exist_ok=True)
    notes_file = B.BUILD / "velopack" / "notes.md"
    notes_file.write_text("\n".join(f"- {n}" for n in notes) or f"AT {v}", encoding="utf-8")
    cmd = [str(VPK), "pack", "--packId", PACK_ID, "--packVersion", v, "--packDir", str(B.OUT), "--mainExe", "AT.exe",
           "--packTitle", TITLE, "--packAuthors", "Adm_TT", "--icon", str(ROOT / "sc_mining" / "app" / "icon.ico"),
           "--outputDir", str(REL), "--channel", "win", "--shortcuts", "Desktop,StartMenuRoot",
           "--releaseNotes", str(notes_file), "--exclude", r".*\.pdb"]
    splash = ROOT / "tools" / "velopack_splash.png"            # 安装时的启动图 + 进度条（tools\make_splash.py，2026-10-27）
    if splash.exists():
        cmd += ["--splashImage", str(splash), "--splashProgressColor", "#c6ab6c"]      # 金（DESIGN.md 主按钮色，2026-10-27 蓝金）
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stdout[-4000:])
    if r.returncode:
        raise SystemExit("❌ vpk pack 失败：\n" + r.stderr[-3000:])


def make_prev():
    """releases.prev.json：只放当前版本前一个的完整包（回滚用）；没有上一版就删掉这个文件"""
    feed = json.loads((REL / "releases.win.json").read_text(encoding="utf-8"))
    fulls = sorted((a for a in feed.get("Assets", []) if a.get("Type") == "Full"), key=lambda a: _ver(a["Version"]))
    out = REL / "releases.prev.json"
    if len(fulls) < 2:
        out.unlink(missing_ok=True)
        print("回滚：还没有上一个版本")
        return None
    prev = fulls[-2]
    if not (REL / prev["FileName"]).exists():
        raise SystemExit(f"❌ 上一版的完整包不在 {REL}：{prev['FileName']}")
    out.write_text(json.dumps({"Assets": [prev]}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"回滚：上一个版本 {prev['Version']}")
    return prev["Version"]


def bridge(v):
    """老 Inno 安装版用的桥接安装程序：搬 userdata → 静默装 Velopack 版 → 卸掉老的 → 打开新的"""
    setup = REL / f"{PACK_ID}-win-Setup.exe"
    out_dir = B.BUILD / "velopack" / "bridge"
    out_dir.mkdir(parents=True, exist_ok=True)
    import hashlib
    sha = hashlib.sha256(setup.read_bytes()).hexdigest()
    tmp = B.BUILD / "velopack" / "bridge_tmp"          # 先编到临时文件夹再复制：输出文件被占用（沙盒映射着、杀毒在扫）时 ISCC 报错 32
    if tmp.exists():
        shutil.rmtree(tmp)
    subprocess.run([str(B.ISCC), "/Q", f"/DMyVersion={v}", f"/DSetupSha256={sha}", f"/DOutDir={tmp}",
                    str(ROOT / "tools" / "AT_bridge.iss")], check=True)
    shutil.copy2(tmp / f"AT_Setup_{v}.exe", out_dir / f"AT_Setup_{v}.exe")
    # 桥接程序认的 AT-win-Setup.exe 校验：publish_hk 发 latest.json 前拿它核对服务器上的那份（二审 2026-10-27）
    (out_dir / f"AT_Setup_{v}.sha256").write_text(sha + "\n", encoding="ascii")
    # 发版时 AT-win-Setup.exe 要传到 AT 服务器 releases/v<版本>/ 和 GitHub 发行版 v<版本>（桥接程序从这两处下载）
    exe = out_dir / f"AT_Setup_{v}.exe"
    print(f"桥接安装程序：{exe}（{exe.stat().st_size / 2 ** 20:,.1f} MB）")
    if exe.stat().st_size >= 100 * 2 ** 20:
        raise SystemExit("❌ 桥接安装程序超过 Gitee 单个附件上限 100 MB")
    return exe


def main(argv):
    skip = "--skip-build" in argv
    notes = [a for a in argv if not a.startswith("--")]
    v = version()
    if not skip:
        B.main()
    if not (B.OUT / "AT.exe").exists() or not (B.OUT / "shell" / "ATShell.exe").exists():
        raise SystemExit(f"❌ {B.OUT} 不完整（缺 AT.exe 或外壳）")
    for old in REL.glob(f"{PACK_ID}-{v}-*.nupkg"):              # 同一版本重打：先删旧的，免得 vpk 报版本已存在
        old.unlink()
    pack(v, notes)
    make_prev()
    bridge(v)
    for f in sorted(REL.iterdir()):
        print(f"  {f.name}  {f.stat().st_size / 2 ** 20:,.1f} MB")


if __name__ == "__main__":
    main(sys.argv[1:])
