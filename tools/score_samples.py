"""识别答题卡打分：用标好正确答案的截图（测试数据\\识别样本\\answers.json）给扫描面板和雷达信号识别打分，
再和上一次的结果比，列出退步的图（改识别前后各跑一次，保证不退步）。

用法（项目根目录）：
  .venv\\Scripts\\python.exe -X utf8 tools\\score_samples.py                 跑一遍，结果存 测试数据\\识别打分_<时间>.json/.md
  .venv\\Scripts\\python.exe -X utf8 tools\\score_samples.py --base 上次.json 再和上次比
  加 --height 1080：把样本缩到这个高度再识别（模拟低分辨率、小窗口）
  .venv\\Scripts\\python.exe -X utf8 tools\\score_samples.py --only 雪地       只跑文件名带「雪地」的

answers.json：{文件名: {"ship": mole/prospector/golem, "seat": 驾驶/左/右/中, "env": 太空/雪地/雾天/沙漠/地表,
               "scan": {"rock", "mass", "res", "inst", "scu", "comp": [[英文名, 百分比, 品质或 null], …]} 或 null（没有面板）,
               "signals": [画面上能看清的信号值…]}}
只在本机跑，不上传图片
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SRC = ROOT / "测试数据" / "识别样本"
FIELDS = ("rock", "mass", "res", "inst", "scu", "comp")


def _same(a, b, tol=0.0):
    if a is None or b is None:
        return a is None and b is None
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return str(a) == str(b)


def check_scan(exp, scan):
    """→ {字段: 对/错}；exp 里没写的字段不算（面板被挡住时只标得出一部分）"""
    norm = lambda n, p, q: [  # noqa: E731
        n or "",
        round(float(p), 2) if p is not None else None,
        None if n == "Inert Materials" else q,
    ]  # 惰性物质的品质（0）不算  # noqa: E731
    got = {
        "rock": scan.rock,
        "mass": scan.mass,
        "res": scan.resistance,
        "inst": scan.instability,
        "scu": scan.total_scu,
        "comp": sorted((norm(n, p, q) for n, p, q in scan.composition), key=str),
    }
    out = {}
    for k in FIELDS:
        if k not in exp:
            continue
        if k == "comp":
            want = sorted((norm(n, p, q) for n, p, q in exp["comp"]), key=str)
            out[k] = want == got["comp"]
        elif k == "rock":
            out[k] = (got["rock"] or "") == exp["rock"] or (
                scan.main_mineral or ""
            ) == exp["rock"]
        else:
            out[k] = _same(exp[k], got[k], 0.005)
    return out, got


HEIGHT = 0
UP = 0


def one(path, ans):
    from PIL import Image
    from sc_mining.mining import screen, signals

    img = Image.open(path).convert("RGB")
    if (
        HEIGHT and img.height != HEIGHT
    ):  # --height 1080：缩到这个高度，模拟低分辨率 / 小窗口玩
        img = img.resize(
            (round(img.width * HEIGHT / img.height), HEIGHT), Image.LANCZOS
        )
    if (
        UP and img.height < UP
    ):  # --up 1440：识别前再放大回这个高度（试「小画面先放大再认」管不管用）
        img = img.resize((round(img.width * UP / img.height), UP), Image.LANCZOS)
    r = {"file": ans["_name"], "ms": {}}
    cache = getattr(screen, "PANEL_CACHE", None)
    if cache is not None:
        cache["win"] = (
            None  # 每张图都从头找（冷启动）；下面再量一次「记住面板位置后」的速度
        )
    t = time.perf_counter()
    scan, _bag = screen.analyse(img)
    r["ms"]["scan"] = round((time.perf_counter() - t) * 1000)
    if cache is not None and cache.get("win"):
        t = time.perf_counter()
        warm, _ = screen.analyse(img)
        r["ms"]["warm"] = round((time.perf_counter() - t) * 1000)
        r["warm_same"] = (
            warm.mass,
            warm.total_scu,
            sorted(map(str, warm.composition)),
        ) == (scan.mass, scan.total_scu, sorted(map(str, scan.composition)))
    raw = screen.LAST_RAW.get("scan") or []
    seen = screen.panel_seen(scan, raw)
    exp = ans.get("scan")
    if exp:
        fields, got = check_scan(exp, scan)
        r["scan"] = {
            "fields": fields,
            "all": all(fields.values()),
            "valid": scan.valid,
            "got": got,
        }
    else:
        r["scan"] = {"false_panel": bool(scan.valid)}
    r["panel_seen"] = seen
    t = time.perf_counter()
    found = signals.find_signatures(img)
    r["ms"]["sig"] = round((time.perf_counter() - t) * 1000)
    got = sorted({v for v, *_ in found})
    want = sorted(set(ans.get("signals") or []))
    r["sig"] = {
        "want": want,
        "got": got,
        "hit": [v for v in want if v in got],
        "extra": [v for v in got if v not in want],
    }
    return r


def summary(rows, answers):
    lines = []
    errs = [r for r in rows if r.get("err")]  # 识别抛异常的：单独计，不算进「做对了」
    rows = [r for r in rows if not r.get("err")]
    if errs:
        lines.append(
            f"- 识别出错（程序报错）{len(errs)} 张：{'、'.join(r['file'] for r in errs)}"
        )
    scan_rows = [r for r in rows if "all" in r["scan"]]
    nopanel = [r for r in rows if "false_panel" in r["scan"]]
    want = sum(len(r["sig"]["want"]) for r in rows)
    hit = sum(len(r["sig"]["hit"]) for r in rows)
    extra = sum(len(r["sig"]["extra"]) for r in rows)
    lines.append(
        f"- 扫描面板全对 {sum(r['scan']['all'] for r in scan_rows)}/{len(scan_rows)} 张"
    )
    for k in FIELDS:
        n = [r["scan"]["fields"][k] for r in scan_rows if k in r["scan"]["fields"]]
        if n:
            lines.append(f"  - {k}：{sum(n)}/{len(n)}")
    wrong = [r for r in scan_rows if r["scan"].get("valid") and not r["scan"]["all"]]
    lines.append(
        f"- 读错了却当成读全了（会显示出来的错）{len(wrong)} 张；没读全（这一帧不出结果）"
        f"{sum(1 for r in scan_rows if not r['scan'].get('valid'))} 张"
    )
    lines.append(
        f"- 没有面板却认出面板 {sum(r['scan']['false_panel'] for r in nopanel)}/{len(nopanel)} 张"
    )
    lines.append(f"- 信号：认出 {hit}/{want} 个，多认 {extra} 个")
    for k, lab in (
        ("scan", "扫描"),
        ("warm", "扫描（记住面板位置后）"),
        ("sig", "信号"),
    ):
        ts = sorted(r["ms"][k] for r in rows if k in r["ms"])
        if ts:
            lines.append(
                f"- {lab}耗时：中位 {ts[len(ts) // 2]} ms，平均 {sum(ts) // len(ts)} ms，最慢 {ts[-1]} ms"
            )
    # 按环境、船位分组
    groups = {}
    for r in rows:
        a = answers[r["file"]]
        for g in (
            f"环境·{a.get('env', '?')}",
            f"船位·{a.get('ship', '?')}-{a.get('seat', '?')}",
        ):
            d = groups.setdefault(g, [0, 0, 0, 0])
            if "all" in r["scan"]:
                d[0] += r["scan"]["all"]
                d[1] += 1  # noqa: E702
            d[2] += len(r["sig"]["hit"])
            d[3] += len(r["sig"]["want"])  # noqa: E702
    lines += ["", "| 分组 | 扫描全对 | 信号认出 |", "|---|---|---|"]
    for g in sorted(groups):
        d = groups[g]
        lines.append(f"| {g} | {d[0]}/{d[1]} | {d[2]}/{d[3]} |")
    return lines


def ok_keys(r):
    """这张图做对了哪些项（用来和上次比退步）；识别出错的图什么都不算做对"""
    if r.get("err"):
        return set()
    keys = set()
    s = r["scan"]
    if "fields" in s:
        keys |= {f"扫描.{k}" for k, v in s["fields"].items() if v}
    elif not s.get("false_panel"):
        keys.add("没面板不误认")
    keys |= {f"信号.{v}" for v in r["sig"]["hit"]}
    if not r["sig"]["extra"]:
        keys.add("信号不多认")
    return keys


def main():
    global HEIGHT, UP
    args = sys.argv[1:]
    base = Path(args[args.index("--base") + 1]) if "--base" in args else None
    HEIGHT = int(args[args.index("--height") + 1]) if "--height" in args else 0
    UP = int(args[args.index("--up") + 1]) if "--up" in args else 0
    only = args[args.index("--only") + 1] if "--only" in args else ""
    src = Path(args[args.index("--src") + 1]) if "--src" in args else SRC
    answers = json.loads((src / "answers.json").read_text(encoding="utf-8"))
    todo = [(k, v) for k, v in answers.items() if only in k and not k.startswith("_")]
    rows, t0 = [], time.time()
    for i, (name, ans) in enumerate(todo, 1):
        ans["_name"] = name
        try:
            r = one(src / name, ans)
        except Exception as e:
            r = {
                "file": name,
                "err": f"{type(e).__name__}: {e}",
                "ms": {"scan": 0, "sig": 0},
                "scan": {"fields": {}, "all": False, "valid": False, "got": None}
                if ans.get("scan")
                else {"false_panel": None},
                "sig": {
                    "want": ans.get("signals") or [],
                    "got": [],
                    "hit": [],
                    "extra": [],
                },
            }
        rows.append(r)
        print(
            f"{i}/{len(todo)} {name} 扫描{'✓' if not r.get('err') and r['scan'].get('all', not r['scan'].get('false_panel')) else '✗'} "
            f"信号 {len(r['sig']['hit'])}/{len(r['sig']['want'])}+{len(r['sig']['extra'])} {r['ms']['scan']}+{r['ms']['sig']}ms",
            flush=True,
        )
    stamp = time.strftime("%Y%m%d_%H%M")
    out = (
        ROOT
        / "测试数据"
        / f"识别打分_{stamp}{'_' + only if only else ''}{f'_{HEIGHT}p' if HEIGHT else ''}{f'_up{UP}' if UP else ''}"
    )
    out.with_suffix(".json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    lines = [
        f"# 识别打分 {time.strftime('%Y-%m-%d %H:%M')}（{len(rows)} 张，用时 {(time.time() - t0) / 60:.1f} 分钟）",
        "",
    ]
    lines += summary(rows, answers)
    if base and base.exists():
        old = {r["file"]: r for r in json.loads(base.read_text(encoding="utf-8"))}
        worse, better = [], []
        for r in rows:
            o = old.get(r["file"])
            if not o:
                continue
            a, b = ok_keys(o), ok_keys(r)
            if r.get("err") and not o.get("err"):
                worse.append(
                    f"- {r['file']}：识别出错 {r['err']}"
                    + (f"（原来做对的 {'、'.join(sorted(a))}）" if a else "")
                )
            elif a - b:
                worse.append(f"- {r['file']}：{'、'.join(sorted(a - b))}")
            if b - a:
                better.append(f"- {r['file']}：{'、'.join(sorted(b - a))}")
        ts_old = sorted(o["ms"]["scan"] + o["ms"]["sig"] for o in old.values())
        ts_new = sorted(r["ms"]["scan"] + r["ms"]["sig"] for r in rows)
        lines += [
            "",
            f"## 和上次比（{base.name}）",
            "",
            f"- 每张图扫描+信号耗时中位：{ts_old[len(ts_old) // 2] if ts_old else '?'} → {ts_new[len(ts_new) // 2]} ms",
            f"- 退步 {len(worse)} 张，进步 {len(better)} 张",
            "",
        ]
        lines += (["### 退步"] + worse + [""] if worse else []) + (
            ["### 进步"] + better if better else []
        )
    lines += ["", "## 没做对的", ""]
    for r in rows:
        s, g = r["scan"], r["sig"]
        bad = []
        if r.get("err"):
            bad.append(f"出错 {r['err']}")
        if "fields" in s and not s["all"]:
            bad.append(
                "扫描错 "
                + "、".join(k for k, v in s["fields"].items() if not v)
                + f"（读到 {s['got']}）"
            )
        if s.get("false_panel"):
            bad.append("没面板却认出面板")
        if len(g["hit"]) < len(g["want"]):
            bad.append(f"信号漏了 {[v for v in g['want'] if v not in g['hit']]}")
        if g["extra"]:
            bad.append(f"信号多认 {g['extra']}")
        if bad:
            lines.append(f"- {r['file']}：" + "；".join(bad))
    out.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    print("报告：", out.with_suffix(".md"))


if __name__ == "__main__":
    main()
