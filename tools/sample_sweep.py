"""稳定性测试：把电脑里所有截图样本过一遍 AT 的每个读屏功能，看会不会出错、认出了什么、花了多久

用法（在项目根目录）：.venv\\Scripts\\python.exe -X utf8 tools\\sample_sweep.py [输出.md]
  样本：tests\\samples、userdata\\shots\\{live,hover}（项目和「下载」里的天枢）、项目资料\\测试数据（含子文件夹，不含工作台报告）、游戏 ScreenShots。
  不扫 Windows 截图文件夹（老大 11-09 定：那里混着私人截图，游戏截图挑进 测试数据\\Windows截图挑选）
  每张图依次跑：扫描面板（screen.analyse）、雷达信号（signals.find_signatures）、物品说明框（_read_tooltip）、
  右上角调试信息（displayinfo）。只在本机跑，不上传任何图片。
  结果写到 测试数据\\稳定性测试_<时间>.md（汇总 + 每张图一行）和同名 .json（明细）
  汇总结论里统计「物品说明框停在哪一档」：标题带 title / 说明框带 body / 全高条带 full / 整屏
  （2026-11-04 起 _read_tooltip 是高度阶段级联，区域标签形如 "30-50%@title"）
"""

import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
HOME = Path(os.environ.get("USERPROFILE", str(Path.home())))
SOURCES = [
    ("测试样本", ROOT / "tests" / "samples"),
    ("项目·采矿助手截图", ROOT / "userdata" / "shots" / "live"),
    ("项目·F8截图", ROOT / "userdata" / "shots" / "hover"),
    (
        "下载天枢·采矿助手截图",
        HOME / "Downloads" / "Dubhe_1.6.2" / "userdata" / "shots" / "live",
    ),
    (
        "下载天枢·F8截图",
        HOME / "Downloads" / "Dubhe_1.6.2" / "userdata" / "shots" / "hover",
    ),
    ("测试数据", Path(r"E:\Claude公主的书\项目资料\测试数据")),
    ("游戏截图", Path(r"D:\StarCitizen\LIVE\ScreenShots")),
]
EXT = {".png", ".jpg", ".jpeg"}


def files():
    seen = set()
    for label, d in SOURCES:
        if not d.is_dir():
            continue
        # 测试数据按子文件夹放（识别样本、盘点样本、历史截图…）：往下找；工作台报告里是画了框的缩略图，不要
        files = d.rglob("*") if label == "测试数据" else d.iterdir()
        for p in sorted(files):
            if "工作台报告" in p.parts:
                continue
            if p.suffix.lower() in EXT and p.stat().st_size > 10_000:
                key = (p.name, p.stat().st_size)
                if key in seen:  # 两个天枢里同一张图只跑一次
                    continue
                seen.add(key)
                yield label, p


def run(fn):
    t = time.time()
    try:
        return fn(), None, time.time() - t
    except Exception as e:
        return (
            None,
            f"{type(e).__name__}: {e}｜{traceback.format_exc().splitlines()[-3].strip()}",
            time.time() - t,
        )


STAGE_NAMES = {"title": "标题带", "body": "说明框带", "full": "全高条带"}


def stage_of(where):
    """识别区域标签 → 高度阶段名：title / body / full / 整屏；认不出返回 None。
    where 是 _read_tooltip 第三项：2026-11-04 起形如 "30-50%@title"、"50-70%@full"、"整屏"，
    以前只有 "30-50%" / "整屏"（旧标签归不了档，不计入统计）"""
    if not where:
        return None
    if where == "整屏":
        return "整屏"
    stage = where.rpartition("@")[2]
    return stage if stage in STAGE_NAMES else None


def one(label, p):
    from PIL import Image
    from astral_toolkit.mining import screen, signals
    from astral_toolkit.navigation import displayinfo
    from astral_toolkit.tasks import mining as S, hover as _H

    img = Image.open(p).convert("RGB")
    W, H = img.size
    r = {"src": label, "file": p.name, "size": f"{W}x{H}", "err": {}, "ms": {}}
    small = W < 900 or H < 500  # F8 存的说明框小图：只跑物品识别
    if not small:
        v, e, dt = run(lambda: screen.analyse(img))
        r["ms"]["扫描"] = round(dt * 1000)
        if e:
            r["err"]["扫描"] = e
        elif v:
            scan = v
            if scan.mass is not None or scan.composition:
                r["scan"] = {
                    "rock": scan.rock,
                    "mass": scan.mass,
                    "res": scan.resistance,
                    "inst": scan.instability,
                    "scu": scan.total_scu,
                    "valid": scan.valid,
                    "comp": [(n, pct, q) for n, pct, q in scan.composition],
                }
                if scan.valid:
                    v2, e2, _ = run(lambda: S.scan_view(scan))
                    if e2:
                        r["err"]["扫描结果页"] = e2
        v, e, dt = run(lambda: signals.find_signatures(img))
        r["ms"]["信号"] = round(dt * 1000)
        if e:
            r["err"]["信号"] = e
        elif v:
            r["sig"] = [x[0] for x in v]
            d, e2, _ = run(lambda: signals.describe_all(v, None))
            if e2:
                r["err"]["信号说明"] = e2
            else:
                r["sig_text"] = [x.split("｜精炼后")[0] for x in d[:3]]
        v, e, dt = run(lambda: displayinfo.parse(displayinfo.lines_of(img)))
        r["ms"]["右上角"] = round(dt * 1000)
        if e:
            r["err"]["右上角"] = e
        elif v and v.get("global"):
            r["di"] = {"location": v.get("location"), "zone": v.get("zone")}
    v, e, dt = run(lambda: _H._read_tooltip(img, (W // 2, H // 2)))
    r["ms"]["物品"] = round(dt * 1000)
    if e:
        r["err"]["物品"] = e
    elif v and v[1]:
        r["item"] = list(v[1]) + [v[2]]
        r["where"] = v[2]  # 停在哪一档（如 "30-50%@title"），汇总结论里统计
    return r


def main():
    stamp = time.strftime("%Y%m%d_%H%M")
    out = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else ROOT / "测试数据" / f"稳定性测试_{stamp}.md"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    rows, t0 = [], time.time()
    todo = list(files())
    print(f"共 {len(todo)} 张图", flush=True)
    for i, (label, p) in enumerate(todo, 1):
        try:
            r = one(label, p)
        except Exception as e:  # 打不开的图也记下来，不中断
            r = {
                "src": label,
                "file": p.name,
                "err": {"打开": f"{type(e).__name__}: {e}"},
                "ms": {},
            }
        rows.append(r)
        print(f"{i}/{len(todo)} {label} {p.name} 错误 {len(r['err'])}", flush=True)
        out.with_suffix(".json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    errs = [r for r in rows if r["err"]]
    # 物品说明框停在哪一档：只算认出名字的图（没认出时 where 是最后试过的一档，不是停下的地方）
    tried = [r for r in rows if "物品" in r["ms"] and "物品" not in r["err"]]
    got = [r for r in tried if r.get("item")]
    stage_hits = {k: 0 for k in ("title", "body", "full", "整屏")}
    for r in got:
        s = stage_of(r.get("where"))
        if s:
            stage_hits[s] += 1
    other = len(got) - sum(stage_hits.values())  # 旧标签（没有 @阶段）归不了档
    lines = [
        f"# AT 稳定性测试（截图样本全量）{time.strftime('%Y-%m-%d %H:%M')}",
        "",
        f"- 图片 {len(rows)} 张，用时 {(time.time() - t0) / 60:.1f} 分钟",
        f"- 出错 {len(errs)} 张（程序报错，不是没认出）",
        f"- 认出扫描面板 {sum(1 for r in rows if 'scan' in r)} 张（其中读全 {sum(1 for r in rows if r.get('scan', {}).get('valid'))} 张）",
        f"- 认出信号 {sum(1 for r in rows if r.get('sig'))} 张",
        f"- 认出物品说明框 {sum(1 for r in rows if r.get('item'))} 张",
        (
            f"- 说明框停在哪一档（跑过物品识别 {len(tried)} 张，不含报错：F8 小图、整屏大图都跑；"
            f"只算认出名的那 {len(got)} 张）：标题带 {stage_hits['title']} 张、"
            f"说明框带 {stage_hits['body']} 张、全高条带 {stage_hits['full']} 张、"
            f"整屏 {stage_hits['整屏']} 张；没认出 {len(tried) - len(got)} 张"
            + (f"；旧标签无法归类 {other} 张" if other else "")
        ),
        f"- 读到右上角坐标 {sum(1 for r in rows if r.get('di'))} 张",
        "",
    ]
    for k in ("扫描", "信号", "物品", "右上角"):
        ts = sorted(r["ms"][k] for r in rows if k in r["ms"])
        if ts:
            lines.append(f"- {k}耗时：中位 {ts[len(ts) // 2]} ms，最慢 {ts[-1]} ms")
    if errs:
        lines += ["", "## 出错的", ""] + [
            f"- {r['src']} {r['file']}：{r['err']}" for r in errs
        ]
    lines += [
        "",
        "## 每张图",
        "",
        "| 来源 | 文件 | 扫描 | 信号 | 物品 | 右上角 |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        sc = r.get("scan")
        sct = (
            (
                f"{sc['rock']} {sc['mass']} kg 抗{sc['res']} 不稳{sc['inst']} {len(sc['comp'])}种"
                + ("" if sc["valid"] else "（不全）")
            )
            if sc
            else ""
        )
        lines.append(
            f"| {r['src']} | {r['file']} | {sct} | {' / '.join(r.get('sig_text', []))[:80]} | "
            f"{' / '.join(map(str, r.get('item', [])))[:60]} | {(r.get('di') or {}).get('location') or ''} |"
        )
    out.write_text("\n".join(lines), encoding="utf-8")
    print("报告：", out)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
