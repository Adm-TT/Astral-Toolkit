"""发版前的接口巡检：把安装包解压到临时目录（全新的用户数据，不碰你自己的），启动天枢后台，
按真实使用顺序把每一个接口都调一遍，检查有没有报错、返回的东西对不对、耗时多少。

用法（在 sc_mining 文件夹里）：
  .venv\\Scripts\\python.exe -X utf8 tools\\release_check.py              巡检 dist 里最新的安装包
  .venv\\Scripts\\python.exe -X utf8 tools\\release_check.py 包.zip       巡检指定的安装包
  加 --update 会顺便测「更新数据」（要联网，两三分钟）

结果打印出来，也写进 tools\\release_check_结果.txt。全部通过才算这个版本可以发、可以存为稳定版。
这是「接口巡检」：读屏准不准、热键、悬浮窗、真实升级重启这些要在游戏里手动演练（见 AGENTS.md）。
巡检用的是全新的临时用户数据、临时交易库存（LOCALAPPDATA）和临时「桌面」，不碰你的真实数据。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
if not PY.exists():
    PY = Path(sys.executable)

LAUNCH = r"""
import sys, threading, subprocess
from pathlib import Path
from sc_mining.app import server, bus
desk = Path(sys.argv[1])
import sc_mining.tasks.system as _ts
_ts._desktop = lambda: desk                         # 导出日志放临时「桌面」，不碰真实桌面（导出在 tasks/system 里做）
_popen = subprocess.Popen
subprocess.Popen = lambda a, *k, **kw: None if a and str(a[0]).lower() == "explorer" else _popen(a, *k, **kw)
bus.install_router()                                # 和正式启动一样：后台任务的输出进窗口日志
srv = server.Server(("127.0.0.1", 0), server.Handler)
sys.__stdout__.write(f"READY {srv.server_address[1]} {server.TOKEN}\n"); sys.__stdout__.flush()
srv.serve_forever()
"""


class Client:
    def __init__(self, port, token):
        self.base, self.token = f"http://127.0.0.1:{port}", token

    def call(self, _api, timeout=120, **args):
        req = urllib.request.Request(
            f"{self.base}/api/{_api}",
            data=json.dumps(args).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Token": self.token},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
        if not body.get("ok"):
            raise RuntimeError(body.get("error") or "接口报错")
        return body["data"]

    def get(self, path):
        with urllib.request.urlopen(f"{self.base}{path}", timeout=20) as r:
            return r.status, r.read()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_update = "--update" in sys.argv
    pkg = (
        Path(args[0])
        if args
        else max((ROOT / "dist").glob("Dubhe_*.zip"), key=lambda p: p.stat().st_mtime)
    )
    tmp = Path(tempfile.mkdtemp(prefix="dubhe_check_"))
    with zipfile.ZipFile(pkg) as z:
        z.extractall(tmp)
    app = next(tmp.iterdir())
    for big in (
        "scmdb",
        "loc",
    ):  # 安装包里不带的原始大文件：从现在的安装复制过去（更新数据才需要）
        if (ROOT / "data" / big).exists():
            shutil.copytree(ROOT / "data" / big, app / "data" / big)
    # 交易库存的数据库在 %LOCALAPPDATA%\SCTradeCompanion（和你真实的库存同一个）：巡检时指到临时目录，绝不碰真实库存
    fake_local = tmp / "_localappdata"
    fake_local.mkdir()
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "PYTHONPATH": str(app),
        "LOCALAPPDATA": str(fake_local),
        "AT_FEEDBACK_OFF": "1",
    }  # 巡检的假反馈别真传服务器
    desk = tmp / "_desktop"
    desk.mkdir()
    proc = subprocess.Popen(
        [str(PY), "-X", "utf8", "-c", LAUNCH, str(desk)],
        cwd=app,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    line = proc.stdout.readline()
    while line and not line.startswith("READY"):
        line = proc.stdout.readline()
    if not line:
        print("❌ 天枢后台没启动起来")
        return 1
    _, port, token = line.split()
    import threading

    server_out = []
    threading.Thread(
        target=lambda: [server_out.append(x) for x in proc.stdout], daemon=True
    ).start()  # 一直读，管道不会塞满卡住
    c = Client(int(port), token)
    rows, ctx = [], {}

    def step(title, fn, check=None, allow_error=False):
        """check 必须明确返回 True 才算通过；返回别的（False、一句话、None、数字）都算不通过，那就是原因。
        接口返回 {"error": ...} 一律算不通过，除非 allow_error（专门测「错的要拒绝」的那几项）"""
        t = time.time()
        try:
            r = fn()
            if isinstance(r, dict) and r.get("error") and not allow_error:
                msg = r["error"]
            elif check:
                msg = check(r)
                if msg is None:
                    msg = "检查没给出结果"
            else:
                msg = True
            ok = msg is True
            rows.append((ok, title, time.time() - t, "" if ok else str(msg)))
            return r
        except Exception as e:
            rows.append((False, title, time.time() - t, f"{type(e).__name__}: {e}"))
            return None

    def expect(cond, why):
        return True if cond else False if not why else why

    # ---- 网页文件
    step(
        "网页：首页 / 脚本 / 样式",
        lambda: [c.get(p)[0] for p in ("/", "/app.js", "/style.css")],
        lambda r: r == [200, 200, 200] or f"状态 {r}",
    )

    def no_token():
        try:
            urllib.request.urlopen(
                urllib.request.Request(
                    f"{c.base}/api/status",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                ),
                timeout=10,
            )
            return "放行了"
        except urllib.error.HTTPError as e:
            return e.code

    step("拒绝没口令的请求", no_token, lambda r: r == 403 or f"没口令也放行了（{r}）")
    # ---- 第一次打开
    step(
        "免责声明：错的话不放行",
        lambda: c.call("agree", text="随便写"),
        lambda r: bool(r.get("error")) or "错的也放行了",
        allow_error=True,
    )
    step("免责声明：同意", lambda: c.call("agree", text="本软件是免费软件"))
    st = step(
        "状态 status",
        lambda: c.call("status"),
        lambda r: bool(r.get("version")) or "没有版本号",
    )
    step(
        "设置 set_settings",
        lambda: c.call("set_settings", hud_scale=0.75),
        lambda r: r.get("hud_scale") == 0.75 or r,
    )
    step("刚升级提示 upgraded", lambda: c.call("upgraded"))
    # ---- 全局搜索
    step(
        "全局搜索：量子",
        lambda: c.call("search", q="量子"),
        lambda r: any(r.get(k) for k in r) or "所有分类都没结果",
    )
    step(
        "全局搜索：空",
        lambda: c.call("search", q=""),
        lambda r: not any(r.values()) or "空搜索不该有结果",
    )
    # ---- 找矿点
    m = step(
        "找矿点：搜 铜",
        lambda: c.call("mineral_search", q="铜"),
        lambda r: bool(r) or "没有结果",
    )
    step(
        "找矿点：详情",
        lambda: c.call(
            "mineral_info",
            name=(m or [{}])[0].get("name") or (m or [{}])[0].get("en") or "Copper",
        ),
        lambda r: bool(r) or "空",
    )
    # ---- 原矿扫描（手动输入 + 配装）
    step(
        "手动输入扫描 manual_scan",
        lambda: c.call("manual_scan", mass=44336, resistance=4, instability=17.32),
        lambda r: (
            (isinstance(r, list) and len(r) > 0 and "short" in r[0]) or "没有破碎方案"
        ),
    )
    g = step(  # noqa: F841
        "配装 mining_gear",
        lambda: c.call("mining_gear"),
        lambda r: bool(r.get("ships")) or "没有船",
    )  # noqa: F841
    step("配装：选勘探者", lambda: c.call("set_mining_gear", ship="prospector"))
    # 1.6.41：自造矿头（发射器、汇流排的品质决定激光功率）
    step(
        "配装：自造矿头 S 档",
        lambda: c.call(
            "set_mining_gear",
            ship="prospector",
            loadout={
                "heads": [["helix_i", []]],
                "crew": 1,
                "craft": [{"Emitter": 971, "Bus Bars": 958}],
            },
        ),
        lambda r: (
            next(s for s in r["ships"] if s["key"] == "prospector")["power"][0]["pct"]
            == 37.2
            or r
        ),
    )
    step(
        "配装：方案标出自造",
        lambda: c.call("manual_scan", mass=9000, resistance=30, instability=10),
        lambda r: (
            (isinstance(r, list) and bool(r) and "自造 +37%" in r[0]["heads"]) or r
        ),
    )
    step("配装：恢复默认", lambda: c.call("set_mining_gear", ship="mole", reset=True))
    step(
        "实时扫描：开始",
        lambda: c.call("live_start"),
        lambda r: r.get("running") is True or r,
    )
    time.sleep(3)
    step(
        "实时扫描：停止",
        lambda: c.call("live_stop"),
        lambda r: r.get("running") is False or r,
    )
    # ---- 制造
    b = step(
        "制造：蓝图字典 全部",
        lambda: c.call("craft_browse"),
        lambda r: r.get("total", 0) > 1000 or f"只有 {r.get('total')} 份",
    )
    step(
        "制造：护甲→头盔 筛选",
        lambda: c.call("craft_browse", cat="fpsgear/armour", part="头盔"),
        lambda r: r.get("total", 0) > 50 or f"只有 {r.get('total')} 份",
    )
    step(
        "制造：加载更多",
        lambda: c.call("craft_browse", offset=60),
        lambda r: bool(r.get("rows")) or "空",
    )
    cs = step(
        "制造：搜索 P4-AR",
        lambda: c.call("craft_search", q="P4-AR"),
        lambda r: bool(r) or "没有结果",
    )
    key = (cs or [{}])[0].get("key") or ((b or {}).get("rows") or [{}])[0].get("key")
    ctx["craft"] = key
    step(
        "制造：详情",
        lambda: c.call("craft_detail", key=key),
        lambda r: bool(r.get("text")) or r,
    )
    # 1.6.47：制造页改版——结构化详情（标签带尺寸）、属性统计（相加）、成品基础值（item_stats.json）
    step(
        "制造：详情带尺寸标签和槽位",
        lambda: c.call("craft_detail", key="Helix II Mining Laser"),
        lambda r: (
            (
                "S2" in r["head"]["tags"]
                and [s["slot"] for s in r["slots"]] == ["框架", "发射器", "汇流排"]
            )
            or r
        ),
    )
    step(
        "制造：属性统计相加 +36.20%",
        lambda: c.call(
            "craft_stats", key="Helix II Mining Laser", qualities={"1": 947, "2": 958}
        ),
        lambda r: (
            next(p["text"] for p in r["stats"]["props"] if p["name"] == "激光功率")
            == "+36.20%"
            or r
        ),
    )
    step(
        "制造：成品基础值（完整性 8000 → 8003.2）",
        lambda: c.call(
            "craft_stats", key="Helix II Mining Laser", qualities={"0": 501}
        ),
        lambda r: (
            (lambda p: p["base"] == 8000 and abs(p["now"] - 8003.2) < 0.01)(
                next(p for p in r["stats"]["props"] if p["name"] == "结构强度")
            )
            or r
        ),
    )
    step(
        "制造：采矿激光写激光功率",
        lambda: c.call("craft_detail", key="Helix II Mining Laser"),
        lambda r: (
            ("激光功率合计" in r.get("text", "") and "冲击力" not in r.get("text", ""))
            or r.get("text", r)
        ),
    )
    step(
        "制造：同名两份配方分开",
        lambda: [
            c.call("craft_detail", key=k)["text"]
            for k in ("Main Powerplant#1", "Main Powerplant#2")
        ],
        lambda r: r[0] != r[1] or "两份一样",
    )
    step(
        "混料计算器",
        lambda: c.call("craft_mix", need=0.14, target=902, boxes=[[860, 1], [967, 1]]),
        lambda r: r.get("ok") or r,
    )
    # ---- 维科洛
    w = step(
        "维科洛：搜索",
        lambda: c.call("wikelo_search", q=""),
        lambda r: len(r) > 50 or len(r),
    )
    wk = (w or [{}])[0].get("key")
    d = step(
        "维科洛：详情",
        lambda: c.call("wikelo_detail", key=wk),
        lambda r: bool(r.get("req")) or r,
    )
    step(
        "维科洛：每样材料都有来源",
        lambda: [c.call("wikelo_detail", key=x["key"]) for x in (w or [])],
        lambda r: (lambda miss: not miss or f"没来源：{miss[:5]}")(
            sorted({q["name"] for x in r for q in x["req"] if not q["tip"]})
        ),
    )
    # ---- 目标
    step(
        "目标：加维科洛兑换",
        lambda: c.call("goal_add", kind="wikelo", ref=(d or {}).get("id")),
    )
    step(
        "目标：加制造",
        lambda: c.call("goal_add", kind="craft", ref="Main Powerplant#2", times=2),
    )
    gl = step(
        "目标：列表",
        lambda: c.call("goals"),
        lambda r: len(r.get("goals", [])) == 2 or r,
    )
    gid = ((gl or {}).get("goals") or [{}])[0].get("id")
    step("目标：改次数", lambda: c.call("goal_update", id=gid, times=3))
    step("目标：调顺序", lambda: c.call("goal_update", id=gid, move=1))
    step(
        "目标：直接入库",
        lambda: c.call(
            "goal_stock_add",
            en="Riccite",
            zh="愈金",
            qty=3,
            unit="SCU",
            quality="600",
            location="测试",
        ),
    )
    step("目标：市场价", lambda: c.call("goal_prices", timeout=60))
    step("目标：删掉", lambda: c.call("goal_update", id=gid, remove=True))
    # ---- 物品 / 交易 / 库存
    step(
        "原矿记录：列表（1.6.70）",
        lambda: c.call("ore_list"),
        lambda r: isinstance(r.get("rows"), list) or r,
    )
    step(
        "热键：改原矿记录键再清掉",
        lambda: (
            c.call("set_settings", ore_key="F11"),
            c.call("set_settings", ore_key=""),
        )[1],
        lambda r: r.get("ore_key") == "" or r,
    )
    it = step(
        "物品：搜索 牵引光束",
        lambda: c.call("item_search", q="牵引光束"),
        lambda r: bool(r) or "没有结果",
    )
    first = (it or [{}])[0]
    step(
        "物品：详情",
        lambda: c.call(
            "item_info",
            name=first.get("name", ""),
            zh=first.get("zh", ""),
            id=first.get("id"),
        ),
        lambda r: bool(r) or "空",
    )
    # 1.6.41：物品查询搜索（商店、掉落、汉化包一起搜）
    step(
        "物品：搜 视差步枪",
        lambda: c.call("item_search", q="视差步枪"),
        lambda r: (
            (bool(r) and r[0]["name"] == "Parallax Energy Assault Rifle")
            or [x["name"] for x in (r or [])[:3]]
        ),
    )
    step(
        "物品：商店掉落都没有的也搜得到（1.6.48）",
        lambda: c.call(
            "item_search", q="Hartmoore Inverter"
        ),  # 2026-10-28 解包后它有了汉化包名，来源从 wiki 变成 loc
        lambda r: (
            bool(
                r
                and r[0]["src"] in ("wiki", "loc")
                and r[0]["name"] == "Hartmoore Inverter Code"
                and r[0].get("zh")
                and r[0].get("category")
            )
            or r
        ),
    )
    step(
        "物品：汉化包 _Name 键（矿石吊舱、采矿模组）",
        lambda: c.call("item_search", q="净采 模组"),
        lambda r: (bool(r) and r[0]["name"] == "Clearcut Module") or r,
    )
    step(
        "物品：描述（1.6.49）",
        lambda: c.call("item_info", name="Helix II Mining Laser", exact=True),
        lambda r: ("采矿激光" in r.get("desc", "")) or r,
    )
    step(
        "物品：汉化包旧写法对到正名",
        lambda: c.call("item_search", q="CF-227 Bulldog"),
        lambda r: (bool(r) and r[0]["name"] == "CF-227 Badger Repeater") or r,
    )
    lo = step(
        "物品：商店和掉落里都没有的也搜得到",
        lambda: c.call("item_search", q="守卫 基底服"),
        lambda r: any(x["src"] == "loc" for x in r) or r,
    )
    lx = next((x for x in (lo or []) if x.get("src") == "loc"), {})
    step(
        "物品：都没有的详情注明",
        lambda: c.call(
            "item_info",
            name=lx.get("name", ""),
            zh=lx.get("zh", ""),
            exact=True,
            loot=False,
        ),
        lambda r: r.get("nowhere") is True or r,
    )
    ml = step(
        "交易：查物品",
        lambda: c.call("market_lookup", q="Quantainium"),
        lambda r: bool(r) or "没有结果",
    )
    mid = (
        (ml or [{}])[0]
        if isinstance(ml, list)
        else (ml or {}).get("items", [{}])[0]
        if isinstance(ml, dict)
        else {}
    ).get("id", "")
    step("交易：市场价（联网）", lambda: c.call("market_prices", id=mid, timeout=60))
    sa = step(
        "库存：入库",
        lambda: c.call("stock_add", id=mid, qty=2, quality="500", location="测试"),
        lambda r: bool(r.get("rows")) or r,
    )
    sn = step(
        "库存：手动入库（带品质）",
        lambda: c.call(
            "stock_add_named",
            name="钛",
            qty="1.5",
            unit="SCU",
            quality="",
            location="测试",
        ),
        lambda r: bool(r.get("added")) or r,
    )
    un = next(
        (x for x in (sn or {}).get("rows", []) if x.get("qkey") == "unknown"), None
    )
    if un:
        step(
            "库存：改品质",
            lambda: c.call(
                "stock_set_quality",
                id=un["id"],
                qkey="unknown",
                location=un["location"],
                ukey=un["ukey"],
                quality="720",
            ),
            lambda r: any(x.get("qkey") == "exact:720" for x in r.get("rows", [])) or r,
        )
    step(
        "目标：品质影响",
        lambda: c.call("craft_effect", key="Main Powerplant#2", qualities={"0": 500}),
        lambda r: "slots" in r or r,
    )
    # 1.6.39：地点列表、出库 / 移库 / 改数量（都在临时库存里做）
    step(
        "库存：地点列表",
        lambda: c.call("stock_places"),
        lambda r: len(r.get("places", [])) >= 20 or r,
    )
    cur = step(
        "库存：读当前",
        lambda: c.call("stock"),
        lambda r: bool(r.get("rows")) and "tree" in r or r,
    )
    ti = next(
        (
            x
            for x in (cur or {}).get("rows", [])
            if x.get("location") == "测试" and "Titanium" in x.get("en", "")
        ),
        None,
    )
    if ti:
        k = {key: ti[key] for key in ("id", "qkey", "location", "ukey")}
        step(
            "库存：出库",
            lambda: c.call("stock_out", **k, qty="0.5", reason="卖出", note="巡检"),
            lambda r: (r.get("history") or [{}])[0].get("type") == "出库" or r,
        )
        step(
            "库存：移库",
            lambda: c.call("stock_move", **k, qty="0.5", to="New Babbage", note="巡检"),
            lambda r: r.get("moved_to") == "新巴贝奇" or r,
        )
        step(
            "库存：改数量",
            lambda: c.call("stock_set_qty", **k, qty="0.2"),
            lambda r: (r.get("history") or [{}])[0].get("type") == "改数量" or r,
        )
        step(
            "库存：不给目标用",
            lambda: c.call("stock_reserve", **k, on=True),
            lambda r: any(x.get("reserved") for x in r.get("rows", [])) or r,
        )
    # 1.6.40：仓位、仓储流水
    step(
        "库存：新建仓位",
        lambda: c.call(
            "stock_bin_save", place="测试", name="巡检仓位", desc="巡检", default=False
        ),
        lambda r: r.get("bin") == "测试｜巡检仓位" or r,
    )
    step(
        "库存：仓储流水",
        lambda: c.call("stock_ledger", size=5),
        lambda r: r.get("total", 0) >= 3 and len(r.get("rows", [])) <= 5 or r,
    )
    step(
        "库存：删仓位",
        lambda: c.call("stock_bin_delete", place="测试", name="巡检仓位"),
        lambda r: "rows" in r or r,
    )
    step(
        "库存：列表",
        lambda: c.call("stock"),
        lambda r: bool(r.get("history")) or "没有记录",
    )
    step(
        "库存：撤销刚才那次",
        lambda: c.call(
            "stock_undo", batch=((sa or {}).get("history") or [{}])[0].get("batch", "")
        ),
        lambda r: (
            not any(
                x.get("location") == "测试" and "Quantainium" in x.get("item", "")
                for x in r.get("rows", [])
            )
            or f"撤销后还剩 {r.get('rows')}"
        ),
    )
    # ---- 导航 / 路标
    ns = step(
        "导航：搜索 洞穴",
        lambda: c.call("nav_search", q="洞穴"),
        lambda r: bool(r.get("rows")) or "没有结果",
    )
    nk = (
        (ns or [{}])[0] if isinstance(ns, list) else ((ns or {}).get("rows") or [{}])[0]
    ).get("key", "")
    step(
        "导航：路线",
        lambda: c.call("nav_plan", key=nk),
        lambda r: bool(r.get("routes")) or "没有路线",
    )
    step(
        "路标：手动新建",
        lambda: c.call(
            "waypoint_add", name="巡检路标", body="Daymar", lat=10, lon=20, alt=0
        ),
    )
    step(
        "路标：用当前位置（等 /showlocation）",
        lambda: c.call("waypoint_add", name="巡检当前位置", here=True),
        lambda r: r.get("pending") is True or r,
    )
    step(
        "路标：粘贴 /showlocation 预览",
        lambda: c.call(
            "waypoint_preview",
            text="Coordinates: x:-18930539540.1 y:-2610158765.2 z:295000.3",
        ),
        lambda r: r.get("ok") is True or r,
    )
    step(
        "路标：粘贴新建",
        lambda: c.call(
            "waypoint_from_text",
            name="巡检粘贴",
            text="Coordinates: x:-18930539540.1 y:-2610158765.2 z:295000.3",
        ),
        lambda r: "desc" in r or r,
    )
    step(
        "路标：粘贴的不是坐标要拒绝",
        lambda: c.call("waypoint_from_text", name="x", text="hello"),
        lambda r: "error" in r or r,
        allow_error=True,
    )
    step("路标：删除粘贴的", lambda: c.call("waypoint_delete", name="巡检粘贴"))
    wp = step(
        "路标：列表",
        lambda: c.call("waypoints"),
        lambda r: any(x.get("name") == "巡检路标" for x in r) or "没找到",
    )
    step(
        "导航：开始（去路标）",
        lambda: c.call(
            "nav_start",
            key=next(
                (x.get("key") for x in (wp or []) if x.get("name") == "巡检路标"), ""
            ),
        ),
    )
    step(
        "导航：切到太空导航（一键定位）",
        lambda: c.call("nav_mode", mode="space"),
        lambda r: r.get("space") is True or r,
    )
    step(
        "导航：切回地面导航",
        lambda: c.call("nav_mode", mode="ground"),
        lambda r: r.get("space") is False or r,
    )
    step("导航：刷新", lambda: c.call("nav_refresh"))
    step("导航：停止", lambda: c.call("nav_stop"))
    step(
        "小行星带：选项",
        lambda: c.call("halo_options"),
        lambda r: len(r.get("bands", [])) == 10 or r,
    )
    step(
        "小行星带：ARC-L1 第5带路线",
        lambda: c.call("halo_routes", frm="ARC-L1", band=5),
        lambda r: (
            any(
                x["to"] == "CRU-L4" and abs(x["dropout"] - 14.3) < 0.06
                for x in r.get("rows", [])
            )
            or r
        ),
    )
    step(
        "小行星带：带号不对要拒绝",
        lambda: c.call("halo_routes", frm="ARC-L1", band=11),
        lambda r: "error" in r or r,
        allow_error=True,
    )
    step(
        "小行星带：挂到悬浮窗",
        lambda: c.call("halo_pin", frm="ARC-L1", to="CRU-L4", band=5),
        lambda r: "14.3 Gm" in r.get("text", "") or r,
    )
    step(
        "矿物：搜「金」",
        lambda: c.call("mineral_search", q="金"),
        lambda r: any(x["en"] == "Gold" for x in r) or r,
    )
    step(
        "矿物：去哪挖带导航",
        lambda: c.call("mineral_info", name="Taranite"),
        lambda r: any(x["nav"]["kind"] == "search" for x in r.get("rows", [])) or r,
    )
    step(
        "制造：按矿筛（艾格瑞金属）",
        lambda: c.call("craft_browse", mat="Agricium", mq=588),
        lambda r: (
            (r.get("total", 0) > 0 and r.get("mat", {}).get("en") == "Agricium") or r
        ),
    )
    step(
        "问题反馈：一键记录",
        lambda: c.call("feedback_report", kind="signal", note="巡检"),
        lambda r: r.get("kb", 0) > 0 or r,
    )
    step(
        "问题反馈：列表",
        lambda: c.call("feedback_list"),
        lambda r: any(x["note"] == "巡检" for x in r) or r,
    )
    step(
        "问题反馈：导出到（临时）桌面",
        lambda: c.call("feedback_export"),
        lambda r: r.get("files", 0) >= 1 or r,
    )
    step(
        "问题反馈：清空",
        lambda: c.call("feedback_clear"),
        lambda r: r.get("removed", 0) >= 2 or r,
    )
    step(
        "小行星带：取下",
        lambda: c.call("halo_unpin"),
        lambda r: r.get("ok") is True or r,
    )
    step(
        "路标：删除",
        lambda: c.call("waypoint_delete", name="巡检路标"),
        lambda r: not any(x.get("name") == "巡检路标" for x in r) or "没删掉",
    )
    # ---- 设置页
    step("悬浮窗：可移动 开", lambda: c.call("overlay_move", on=True))
    step("悬浮窗：可移动 关", lambda: c.call("overlay_move", on=False))
    step(
        "升级：查找新版本/可回滚",
        lambda: c.call("upgrade_check"),
        lambda r: "older" in r or r,
    )
    step(
        "升级：坏安装包要拒绝",
        lambda: c.call("upgrade_apply", path=str(tmp / "不存在.zip")),
        lambda r: bool(r.get("error")) or "没拒绝",
        allow_error=True,
    )
    step(
        "升级：上传名字不对要拒绝",
        lambda: c.call("upgrade_upload", name="abc.zip", data=""),
        lambda r: bool(r.get("error")) or "没拒绝",
        allow_error=True,
    )
    step(
        "回滚：坏路径要拒绝",
        lambda: c.call("upgrade_rollback", path=str(tmp / "不存在.zip")),
        lambda r: bool(r.get("error")) or "没拒绝",
        allow_error=True,
    )
    step(
        "存为稳定版",
        lambda: c.call("upgrade_mark_stable"),
        lambda r: bool(r.get("path")) or r,
    )
    step(
        "导出日志（放临时桌面，压缩包能打开）",
        lambda: c.call("export_logs"),
        lambda r: (
            (
                Path(r["path"]).parent == desk
                and zipfile.ZipFile(r["path"]).testzip() is None
            )
            or f"放到了 {r.get('path')}"
        ),
    )
    if do_update:

        def update():
            import threading

            msgs, done = [], threading.Event()

            def listen():  # 后台任务的进度和结果从事件流里来
                with urllib.request.urlopen(
                    f"{c.base}/api/events?t={c.token}", timeout=600
                ) as r:
                    for raw in r:
                        line = raw.decode("utf-8", "replace").strip()
                        if not line.startswith("data:"):
                            continue
                        try:
                            m = json.loads(line[5:])
                        except ValueError:
                            continue
                        msgs.append(m)
                        d = m.get("data") or {}
                        if (
                            m.get("kind") == "task"
                            and d.get("id") == "update"
                            and d.get("state") in ("done", "error")
                        ):
                            done.set()
                            return

            threading.Thread(target=listen, daemon=True).start()
            time.sleep(1)
            c.call("update_data")
            done.wait(600)
            last = next(
                (
                    (m.get("data") or {})
                    for m in reversed(msgs)
                    if m.get("kind") == "task"
                    and (m.get("data") or {}).get("id") == "update"
                ),
                {},
            )
            return {"state": last.get("state"), "result": last.get("result") or {}}

        # 2026-10-26 起数据走 Gitee 数据包：汉化包 + 数据包 2 项；数据包连不上时退回各网站直接下（项数更多）。都要成功
        step(
            "更新数据（联网，每项都要成功）",
            update,
            lambda r: (
                (
                    r["state"] == "done"
                    and r["result"].get("total", 0) >= 2
                    and r["result"].get("ok") == r["result"].get("total")
                )
                or f"状态 {r['state']}，结果 {r['result']}"
            ),
        )
    # 不测：show（弹窗口）、quit（退出）、open_referral（开浏览器）、真正的升级/回滚（会重启）——这些在单元测试和手动测试里覆盖
    proc.terminate()
    try:
        proc.wait(5)
    except Exception:
        proc.kill()
    shutil.rmtree(tmp, ignore_errors=True)
    ok = sum(1 for r in rows if r[0])
    out = [
        f"天枢 {(st or {}).get('version', '?')} 接口巡检：{ok}/{len(rows)} 通过（{pkg.name}）",
        "",
    ]
    out += [
        f"{'✅' if r[0] else '❌'} {r[1]}（{r[2]:.1f}s）"
        + (f"｜{r[3]}" if r[3] else "")
        for r in rows
    ]
    text = "\n".join(out)
    print(text)
    (ROOT / "tools" / "release_check_结果.txt").write_text(text, encoding="utf-8")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
