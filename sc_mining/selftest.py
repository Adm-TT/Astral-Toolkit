"""自检（2026-10-26，独立打包版验收用）：AT.exe selftest，Python 版也能跑：python -m sc_mining.selftest

逐项检查并计时：运行环境、全部模块能导入、数据文件、物品搜索、破碎计算、文字识别（含显卡）、扫描面板识别、
悬浮窗绘制、本机网页服务、Edge 浏览器。结果写进 userdata\\logs\\selftest.txt；全部通过返回 0，否则返回 1
"""
import json
import sys
import time
import traceback

MODULES = (
    "run", "mining.screen", "mining.parse", "mining.signals", "mining.laser", "mining.data", "mining.refinery",
    "crafting.crafting", "crafting.wikelo", "crafting.goals", "navigation.navigate",
    "system.showloc", "app.overlay", "system.helpers", "core.perf", "core.perfmon",
    "crafting.itemsearch", "crafting.shops", "crafting.loot", "update.localization", "update.data_pack",
    "update.update_check", "update.upgrade", "update.legacy", "navigation.displayinfo",
    "navigation.position", "system.cockpit", "app.tray", "core.i18n",
    "app.server", "app.services", "app.bus", "trade.console", "trade.ocr", "trade.inventory",
    "tasks.mining", "tasks.hover", "tasks.count", "tasks.stock", "tasks.system", "tasks.navigation", "tasks.trade", "tasks.goals",
)


def main():
    from .core import paths
    rows, ok_all = [], True
    t_all = time.perf_counter()

    def check(name, fn):
        nonlocal ok_all
        t = time.perf_counter()
        try:
            detail = fn() or ""
            ok = True
        except Exception as e:
            detail, ok = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}", False
        ms = (time.perf_counter() - t) * 1000
        ok_all &= ok
        rows.append(f"{'✅' if ok else '❌'} {name}（{ms:,.0f} ms）{('：' + str(detail)) if detail else ''}")

    def env():
        import platform
        probe = paths.USER / ".selftest_write"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return (f"{'独立打包版' if paths.FROZEN else 'Python 版'}，Python {sys.version.split()[0]}，Windows {platform.version()}，"
                f"程序位置 {paths.ROOT}，可写入 userdata")

    def imports():
        import importlib
        for m in MODULES:
            importlib.import_module(f"sc_mining.{m}")
        return f"{len(MODULES)} 个模块"

    def data_files():
        out = []
        for name in ("shops.json", "crafting.json", "starmap.json", "loot_index.json", "zh_names.json", "wikelo.json", "prices.json"):
            p = paths.DATA / name
            if not p.exists():
                raise FileNotFoundError(f"缺少 data\\{name}")
            json.loads(p.read_text(encoding="utf-8"))
            out.append(name)
        return f"{len(out)} 个数据文件可读"

    def search():
        from .crafting import itemsearch
        r = itemsearch.find("霍夫斯泰德")
        if not r:
            raise AssertionError("搜不到「霍夫斯泰德」")
        return f"「霍夫斯泰德」{len(r)} 条，第一条 {r[0]['zh']} {r[0]['en']}"

    def breaking():
        from .mining import laser
        p = laser.recommend(9800, 45, 3.2)
        if not p:
            raise AssertionError("没有破碎方案")
        return p[0].short()

    ocr = {}

    def ocr_engine():
        from .core import perf
        t = time.perf_counter()
        perf.rapidocr()
        ocr["load"] = (time.perf_counter() - t) * 1000
        return f"识别在 {perf.ocr_device()} 上算（可用显卡：{'是' if perf.gpu_available() else '否'}）"

    def scan_panel():
        from PIL import Image
        from .mining import screen
        img = None
        for p in (paths.ROOT / "selftest" / "scan1.png", paths.SAMPLES / "scan1.png"):
            if p.exists():
                img = Image.open(p).convert("RGB")
                break
        if img is None:
            raise FileNotFoundError("缺少自检截图 selftest\\scan1.png")
        times = []
        for _ in range(2):
            screen.PANEL_CACHE.update(win=None)
            t = time.perf_counter()
            scan, _bag = screen.analyse(img)
            times.append((time.perf_counter() - t) * 1000)
        if not scan.valid:
            raise AssertionError(f"扫描面板没读全：{scan}")
        return f"{scan.main_mineral} {scan.mass:,.0f} kg 抗性 {scan.resistance}%；第一次 {times[0]:,.0f} ms，第二次 {times[1]:,.0f} ms"

    def overlay_paint():
        from .app import overlay
        overlay.paint({"扫描": "金｜8,000 kg\n螺旋 Helix II｜功率 60%"}, scale=1.0)
        import tkinter  # noqa: F401  悬浮窗用
        return "悬浮窗能画、tkinter 可用"

    def server():
        import threading
        import urllib.request
        from .app import server as S
        srv = S.Server(("127.0.0.1", 0), S.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            port = srv.server_address[1]
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/status", data=b"{}",
                                         headers={"Content-Type": "application/json", "X-Token": S.TOKEN})
            d = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
            if not d.get("ok"):
                raise AssertionError(d)
            html = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10).read().decode("utf-8")
            if "AT 星际公民助手" not in html:
                raise AssertionError("网页没加载出来")
            return f"端口 {port}，版本 {d['data'].get('version')}"
        finally:
            srv.shutdown()

    def edge():
        from .app.server import _browser
        b = _browser()
        if not b:
            raise FileNotFoundError("没找到 Edge 或 Chrome（窗口会改用默认浏览器打开）")
        return b

    check("运行环境", env)
    check("导入全部模块", imports)
    check("数据文件", data_files)
    check("物品搜索", search)
    check("破碎方案计算", breaking)
    check("加载文字识别引擎", ocr_engine)
    check("扫描面板识别（自检截图）", scan_panel)
    check("悬浮窗绘制", overlay_paint)
    check("本机网页服务", server)
    check("Edge 浏览器", edge)
    total = (time.perf_counter() - t_all) * 1000
    head = [f"AT 自检 {time.strftime('%F %T')}：{'全部通过' if ok_all else '有项目失败'}（共 {total:,.0f} ms）"]
    if "load" in ocr:
        head.append(f"识别引擎加载 {ocr['load']:,.0f} ms")
    text = "\n".join(head + rows) + "\n"
    try:
        (paths.LOGS / "selftest.txt").write_text(text, encoding="utf-8")
    except OSError:
        pass
    if sys.stdout is not None:
        try:
            print(text)
        except Exception:
            pass
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
