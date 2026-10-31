"""Windows 启动器：.bat 只调用这里，中文提示都放在 Python 里输出
（.bat 里写中文会因为编码问题被 cmd 读乱）

python -m sc_mining.run            打开主菜单（AT）
python -m sc_mining.run install | live | demo | update | where | craft | nav
"""
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# 下载组件的地方：官方源在中国大陆很慢（识别组件一共两百多 MB），所以装之前先比一下哪个快
INDEXES = [("官方源", "https://pypi.org/simple"),
           ("清华镜像", "https://pypi.tuna.tsinghua.edu.cn/simple"),
           ("阿里云镜像", "https://mirrors.aliyun.com/pypi/simple")]
_index = None


SAMPLE = 400_000          # 测速时真的下载多少字节


def _speed(url, timeout=8.0):
    """真实下载速度（字节/秒）：从这个源的文件列表里找一个真实的安装包，下载前 400 KB 计时。
    以前只看「文件列表页」打开快不快——官方源的列表页在国内也很快，可真正的安装包在另一台服务器上，只有几十 KB/s。
    连不上返回 None"""
    import re as _re
    import time
    import urllib.parse
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(url + "/onnxruntime/", headers={"User-Agent": "pip"}),
                                    timeout=timeout) as r:
            page = r.read(2_000_000).decode("utf-8", "replace")
        links = _re.findall(r'href="([^"]+?\.whl)[^"]*"', page)
        if not links:
            return None
        link = urllib.parse.urljoin(url + "/onnxruntime/", links[-1])
        t = time.time()
        got = 0
        with urllib.request.urlopen(urllib.request.Request(link, headers={"User-Agent": "pip"}), timeout=timeout) as r:
            while got < SAMPLE and time.time() - t < timeout:
                chunk = r.read(65536)
                if not chunk:
                    break
                got += len(chunk)
        return got / max(time.time() - t, 0.05)
    except Exception:
        return None


def pick_index():
    """(名字, 地址)：几个下载源里实际下载最快的那个（同时测，最多十来秒）"""
    from concurrent.futures import ThreadPoolExecutor
    print("测各个下载源的速度…")
    with ThreadPoolExecutor(len(INDEXES)) as ex:
        speeds = list(ex.map(lambda x: _speed(x[1]), INDEXES))
    for (name, _), sp in zip(INDEXES, speeds):
        print(f"  {name}：" + (f"{sp / 1024:,.0f} KB/s" if sp else "连不上"))
    ok = [(sp, i) for i, sp in enumerate(speeds) if sp]
    if not ok:
        return INDEXES[0]
    return INDEXES[max(ok)[1]]


def _pip(*pkgs):
    from .paths import FROZEN
    if FROZEN:                              # 独立打包版自带全部组件，不用也不能 pip 安装
        print("独立版自带全部组件，无需安装")
        return True
    global _index
    if _index is None:
        _index = pick_index()
        print(f"下载源：{_index[0]}")
    return subprocess.call([sys.executable, "-m", "pip", "install", "-i", _index[1], "--timeout", "60",
                            "--retries", "5", *pkgs]) == 0


def install():
    print(f"Python {sys.version.split()[0]}")
    _pip("--upgrade", "pip", "-q")
    ok = _pip("mss", "pillow", "numpy")
    print("\n安装中文识别组件…")
    ocr = _pip("rapidocr_onnxruntime") or _pip("rapidocr", "onnxruntime")
    print()
    exe = None
    try:
        from .app.build_exe import build
        exe = build()
    except Exception as e:
        print(f"（生成 Dubhe.exe 没成功：{e}，可以用 .venv\\Scripts\\python.exe -m sc_mining.run console）")
    if ok and ocr:
        print("✅ 安装完成，以后双击「Dubhe.exe」就能用" if exe else "✅ 安装完成")
    else:
        print("❌ 有组件没装上，把这个窗口截图发给作者（游戏 ID：Adm_TT）")


def live():
    print("进游戏后在采矿模式下扫描石头，结果会显示在这里。按 Ctrl+C 退出\n")
    from . import screen
    sys.argv = ["screen"]
    screen.main()


def demo():
    from . import demo as d
    d.main()


def where():
    from .locations import ask
    ask()


def craft():
    from .crafting import ask
    ask()


class Relaunched(Exception):
    """已经用管理员身份另开了窗口，这个窗口退出"""


def nav():
    from .navigate import ask
    ask()


def trade():
    from .trade.console import ask
    ask()


def assist():
    from .helpers import menu as m
    m()


def run_entry(name):
    """管理员窗口用：直接进某个功能，结束后等回车再关窗口"""
    import os
    os.environ.setdefault("PYTHONUTF8", "1")
    silent = _no_console()              # 从 exe 启动、用 pythonw 重开的管理员窗口：没有命令行
    try:
        ENTRIES[name]()
        if name == "menu" or silent:
            return                      # 助手窗口关了就直接退出
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
        if silent:
            _error_box("助手出错了。错误已记进日志（设置页可导出），发给作者（游戏 ID：Adm_TT）看看。")
            return
        print("出错了，把这个窗口截图发给作者（游戏 ID：Adm_TT）")
    input("\n按回车关闭这个窗口")


def _is_unpack(fn):
    """这项更新对应的本地文件是不是我们自己解包的版本（source == "unpack"）：是就不用网站版覆盖"""
    import json as _j
    from . import paths
    mod = getattr(fn, "__module__", "") or ""
    if mod == "sc_mining.build_crafting":
        from . import build_crafting
        if build_crafting.unpacked() is not None:          # 本机有解包原文件：交给它自己按解包版重编（不会去 scmdb），游戏更新后新蓝图才进得来（二十一审）
            return False
    for f in {"sc_mining.navigate": ["starmap.json"], "sc_mining.build_crafting": ["crafting.json"]}.get(mod, []):
        try:
            if _j.loads(paths.data(f).read_text(encoding="utf-8")).get("source") == "unpack":
                return True
        except Exception:
            pass
    return False


def update(direct=False, web_ok=()):
    """更新数据（2026-10-26 起）：汉化包照旧从 SC汉化盒子（国内服务器）下载；其余数据先从 AT 服务器（不通再 Gitee、GitHub）下 AT 发布的数据包，
    Gitee、GitHub 都连不上才改从各数据网站直接下载（矿价、商店 UEX，蓝图 scmdb，星图 starmap.space，掉落 scl.miao.network）。
    direct=True：跳过数据包、直接从各网站下载（作者发布数据包前用，tools/make_data_pack.py）。
    web_ok：本机是解包版也照样从网站下的模块名（make_data_pack 下了 starmap.space 后会用 unpack_starmap 重新合并，只取自转相位和玩家补充的点）"""
    from . import uex, build_crafting, navigate, shops, localization, loot, data_pack
    sources = (("矿价和精炼站加成（UEX）", uex.refresh), ("制造蓝图 + 维科洛兑换（scmdb）", build_crafting.update),
               ("星图导航数据（starmap.space）", navigate.update), ("商店售卖地点（UEX）", shops.update),
               ("掉落数据（scl.miao.network）", loot.update))
    pack = {"ok": None}

    def from_pack():
        try:
            r = data_pack.update()
        except Exception as e:
            pack["ok"] = False                    # 下载到了但装的时候出错：是真失败，不要再去各网站直连盖掉半新半旧的文件
            raise ValueError(f"数据包安装出错：{e}")
        pack["ok"] = r
        if r is None:
            raise ValueError("数据包无法下载")

    from_pack_fn = from_pack
    own = [s for s in sources if getattr(s[1], "__module__", "") not in web_ok and _is_unpack(s[1])]   # 本机已是自己解包的（星图、制造 + 维科洛）：网站版不再盖掉（2026-10-28 老大定：自己解包的优先）
    sources = tuple(s for s in sources if s not in own)

    def say_own():
        for s in own:
            print(f"跳过{s[0]}：用自己解包的数据")
    if direct:
        say_own()
    jobs = (("最新汉化包（SC汉化盒子）", localization.update),) + (sources if direct else (("数据包", from_pack),))

    try:                                    # 在天枢窗口里点「更新」时：几个下载线程的输出都要进窗口的更新记录
        from .app import bus
        task = bus.current_task()
    except Exception:
        bus, task = None, None

    def run(job):
        if bus and task:
            bus.adopt_task(task)
        title, fn = job
        print(f"—— 开始更新{title} ——")
        try:
            fn()
            print(f"✅ {title} 更新完成")
            return {"title": title, "ok": True}
        except Exception as e:
            if fn is from_pack_fn and pack["ok"] is None:      # 数据包下不到：不算失败，下面改从各数据网站更新
                return {"title": title, "ok": False, "error": str(e)}
            print(f"❌ {title} 更新失败：{e}（不影响使用，继续用旧数据）")
            return {"title": title, "ok": False, "error": str(e)}

    # 几个数据源互不相关，同时下载：总时间≈最慢的那一个，而不是全部加起来（访问国外慢的网络下差别很大）
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(len(jobs)) as ex:
        results = list(ex.map(run, jobs))
    if not direct and pack["ok"] is None:          # 数据包连不上：改从各数据网站直接下载（和 2026-10-26 以前一样）
        print("—— 改从各数据网站直接更新 ——")
        results = [r for r in results if r["title"] != "数据包"]
        say_own()
        with ThreadPoolExecutor(len(sources)) as ex:          # 解包版的上面已经去掉了
            results += list(ex.map(run, sources))
    print("全部更新完成")
    try:
        data_pack.clear_caches()                   # 不管走哪条路，换了文件就清缓存，不用重启
    except Exception:
        pass
    # 每一项成没成功（巡检和窗口都能直接看，不用从文字里找 ❌）
    return {"results": results, "ok": sum(r["ok"] for r in results), "total": len(results)}


MENU = [
    ("1", "实时读屏（信号 + 扫描 + 破碎方案 + 精炼 + 制造提示）", live),
    ("2", "找矿点：想挖什么矿，去哪挖", where),
    ("3", "制造：查蓝图要什么矿 / 某种矿能做什么", craft),
    ("4", "手动输入扫描数据", demo),
    ("5", "更新数据（汉化 + 矿价 + 制造 + 星图 + 商店 + 掉落）", update),
    ("6", "导航：去没有量子信标的地点（洞穴、残骸、自定义路标）", nav),
    ("7", "游戏辅助（1.1.2 起已删除）", assist),
    ("8", "交易：查价 / 哪里买 / 维科洛兑换 / 库存（游戏里 F8 识别物品）", trade),
    ("0", "退出", None),
]


def menu(console=False, restart=False):
    from . import paths
    try:
        paths.migrate()                 # 旧版本散落的文件搬到 data/ 和 userdata/
    except Exception:
        traceback.print_exc()
    from . import showloc, settings, helpers
    from .app.server import _single_instance, release_instance
    # 只允许开一个天枢：已经开着就把它的窗口叫出来，这次直接退出（不再弹管理员确认框、不再重复挂热键）
    if not _single_instance(restart):
        return
    if showloc.WIN and not showloc.is_admin() and settings.load()["admin"] is not False:
        # 你的游戏是管理员权限运行：热键（F8）、双击 W 都要求助手也是管理员身份，
        # 否则 Windows 既不让读游戏里的按键，也不让往游戏里发键。默认直接用管理员身份重开。
        print("正在用管理员身份重新打开助手（Windows 会弹确认框，点「是」）…")
        print("（不想这样的话：菜单 7 → 3 把「管理员身份」改成「不用」）")
        release_instance()                          # 让管理员身份的新天枢拿到「只开一个」的锁
        if showloc.relaunch_as_admin("menu"):
            settings.update(admin=True)
            return
        print("没能用管理员身份打开（可能点了「否」）。热键和自动按键在游戏里会失效。")
        if not _single_instance():                  # 没换成功：把锁拿回来，继续用普通身份
            return
    helpers.start()
    try:
        if console:
            _menu_loop()
        else:
            from .app.server import main as window
            window(restart=restart)
    except Relaunched:
        pass
    finally:
        helpers.stop_helpers()


def console_menu():
    """老的命令行菜单（窗口打不开时备用）：python -m sc_mining.run console"""
    menu(console=True)


def _menu_loop():
    from .data import GAME_VERSION
    from .helpers import status_line
    while True:
        print("\n" + "=" * 50)
        print(f"  AT · 游戏数据 {GAME_VERSION}")
        print("  " + status_line())
        print("=" * 50)
        for key, title, _ in MENU:
            print(f"  {key}. {title}")
        choice = input("\n选择功能序号 > ").strip()
        action = next((fn for key, _, fn in MENU if key == choice), "missing")
        if action is None:
            return
        if action == "missing":
            print("没有这个选项")
            continue
        print()
        try:
            action()
        except Relaunched:
            raise
        except KeyboardInterrupt:
            print("\n（已返回菜单）")
        except Exception:
            traceback.print_exc()
            print("出错了，把这个窗口截图发给作者（游戏 ID：Adm_TT）")


ENTRIES = {"menu": menu, "restart": lambda: menu(restart=True), "console": console_menu, "install": install, "live": live, "demo": demo, "update": update,
           "prices": update, "where": where, "craft": craft, "trade": trade, "nav": lambda: __import__(
               "sc_mining.navigate", fromlist=["ask"]).ask()}

def _crash_log():
    from . import paths
    paths.crash_log()


def _no_console():
    """用 pythonw 启动（exe 启动器）时没有命令行窗口：输出写进日志，出错弹框"""
    _crash_log()
    if sys.stdout is not None:
        return False
    from . import paths
    f = open(paths.log("app_log.txt"), "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = f
    print(f"\n==== {__import__('time').strftime('%F %T')} 启动 ====")
    return True


def _error_box(msg):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, "AT", 0x10)
    except Exception:
        pass


if __name__ == "__main__":
    silent = _no_console()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "menu"
    if silent:
        try:
            (nav if cmd == "nav" else ENTRIES[cmd])()
        except Exception:
            traceback.print_exc()
            _error_box("助手出错了。错误已记进日志（设置页可导出），发给作者（游戏 ID：Adm_TT）看看。")
        sys.exit(0)
    (nav if cmd == "nav" else ENTRIES[cmd])()
