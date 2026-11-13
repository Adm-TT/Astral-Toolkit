"""Windows 启动器：.bat 只调用这里，中文提示都放在 Python 里输出
（.bat 里写中文会因为编码问题被 cmd 读乱）

python -m astral_toolkit.run            打开 AT（窗口）
python -m astral_toolkit.run install | update | restart
（命令行版：老菜单、交易 / 导航 / 找矿点 / 制造 / 实时读屏命令 2026-11-06 删了，F 段 B3）
"""

import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# 下载组件的地方：官方源在中国大陆很慢（识别组件一共两百多 MB），所以装之前先比一下哪个快
INDEXES = [
    ("官方源", "https://pypi.org/simple"),
    ("清华镜像", "https://pypi.tuna.tsinghua.edu.cn/simple"),
    ("阿里云镜像", "https://mirrors.aliyun.com/pypi/simple"),
]
_index = None


SAMPLE = 400_000  # 测速时真的下载多少字节


def _speed(url, timeout=8.0):
    """真实下载速度（字节/秒）：从这个源的文件列表里找一个真实的安装包，下载前 400 KB 计时。
    以前只看「文件列表页」打开快不快——官方源的列表页在国内也很快，可真正的安装包在另一台服务器上，只有几十 KB/s。
    连不上返回 None"""
    import re as _re
    import time
    import urllib.parse
    import urllib.request

    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                url + "/onnxruntime/", headers={"User-Agent": "pip"}
            ),
            timeout=timeout,
        ) as r:
            page = r.read(2_000_000).decode("utf-8", "replace")
        links = _re.findall(r'href="([^"]+?\.whl)[^"]*"', page)
        if not links:
            return None
        link = urllib.parse.urljoin(url + "/onnxruntime/", links[-1])
        t = time.time()
        got = 0
        with urllib.request.urlopen(
            urllib.request.Request(link, headers={"User-Agent": "pip"}), timeout=timeout
        ) as r:
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
    from .core.paths import FROZEN

    if FROZEN:  # 独立打包版自带全部组件，不用也不能 pip 安装
        print("独立版自带全部组件，无需安装")
        return True
    global _index
    if _index is None:
        _index = pick_index()
        print(f"下载源：{_index[0]}")
    return (
        subprocess.call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-i",
                _index[1],
                "--timeout",
                "60",
                "--retries",
                "5",
                *pkgs,
            ]
        )
        == 0
    )


def _pip_uninstall(*pkgs):
    return (
        subprocess.call(
            [sys.executable, "-m", "pip", "uninstall", "-y", *pkgs],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        == 0
    )


def use_directml():
    """识别组件换成显卡版（onnxruntime-directml）：先装显卡版，装上了再卸 CPU 版 onnxruntime，
    再强制重装一遍显卡版（两个包装在同一个 onnxruntime 目录里，卸 CPU 版会把显卡版的文件一起删掉）。
    显卡版装不上就留着 CPU 版、不卸（以前先卸再装，装失败就两个都没有，识别用不了）"""
    from .core.paths import FROZEN

    if FROZEN:  # 独立打包版自带全部组件
        return True
    if not _pip("onnxruntime-directml"):
        print("显卡加速组件没装上，继续用 CPU 识别")
        return False
    _pip_uninstall("onnxruntime")
    if _pip("--force-reinstall", "--no-deps", "onnxruntime-directml"):
        return True
    print(
        "显卡加速组件没装好，装回 CPU 版识别组件…"
    )  # CPU 版已经卸了：不装回来就一个都没有
    _pip("onnxruntime")
    return False


def _onnx_ok():
    """识别组件真的能用：另开一个 Python 试 import onnxruntime（包装上了、文件却缺了也算不能用）"""
    return (
        subprocess.call(
            [sys.executable, "-c", "import onnxruntime"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        == 0
    )


def install():
    print(f"Python {sys.version.split()[0]}")
    _pip("--upgrade", "pip", "-q")
    ok = _pip("mss", "pillow", "numpy")
    print("\n安装中文识别组件…")
    ocr = _pip("rapidocr")
    if sys.platform == "win32":
        print("配置 DirectML 显卡加速…")
        use_directml()
    else:
        ocr = bool(ocr and _pip("onnxruntime"))
    if ocr:
        try:
            from .ocr.runtime import ensure_models

            print("下载 PP-OCRv6 识别模型（离线打包用；已存在则跳过）…")
            ensure_models()
        except Exception as e:
            print(f"❌ 识别模型没下好：{e}")
            ocr = False
    print()
    exe = None
    try:
        from .app.build_exe import build

        exe = build()
    except Exception as e:
        print(
            f"（生成 Dubhe.exe 没成功：{e}，可以用 .venv\\Scripts\\python.exe -m astral_toolkit.run 打开）"
        )
    if ocr and not _onnx_ok():
        ocr = False
        print("❌ 文字识别组件（onnxruntime）装了但加载不了")
    if ok and ocr:
        print("✅ 安装完成，以后双击「Dubhe.exe」就能用" if exe else "✅ 安装完成")
    else:
        print("❌ 有组件没装上，把这个窗口截图发给作者（游戏 ID：Adm_TT）")


def run_entry(name):
    """管理员窗口用：直接进某个功能，结束后等回车再关窗口"""
    import os

    os.environ.setdefault("PYTHONUTF8", "1")
    silent = _no_console()  # 从 exe 启动、用 pythonw 重开的管理员窗口：没有命令行
    try:
        ENTRIES[name]()
        if name == "menu" or silent:
            return  # 助手窗口关了就直接退出
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
        if silent:
            _error_box(
                "助手出错了。错误已记进日志（设置页可导出），发给作者（游戏 ID：Adm_TT）看看。"
            )
            return
        print("出错了，把这个窗口截图发给作者（游戏 ID：Adm_TT）")
    input("\n按回车关闭这个窗口")


def update(direct=False):
    """更新数据：汉化包从 SC汉化盒子（国内服务器）下载；其余数据从 AT 服务器（不通再国内镜像、GitHub）下 AT 发布的数据包。
    数据包连不上时只更新行情（矿价、商店，UEX）：星图、制造蓝图、掉落只跟数据包走，不再去别的网站下（2026-11-13 老大定）。
    direct=True：作者发布数据包前用（tools/make_data_pack.py）：跳过数据包，更新行情、按本机构建输入重编制造数据、
    更新掉落索引（掉落改成自己算之前，发数据还要从 scl.miao.network 取；玩家这边的更新走不到这两项）"""
    from .crafting import build_crafting
    from .update import data_pack, localization, loot, shops, uex

    market = (
        ("矿价和精炼站加成（UEX）", uex.refresh),
        ("商店售卖地点（UEX）", shops.update),
    )
    author = (
        ("制造蓝图 + 维科洛兑换（本机构建输入）", build_crafting.update),
        ("掉落数据（scl.miao.network）", loot.update),
    )
    pack = {"ok": None}

    def from_pack():
        try:
            r = data_pack.update()
        except Exception as e:
            pack["ok"] = (
                False  # 下载到了但装的时候出错：是真失败，不要再去更新行情盖掉半新半旧的文件
            )
            raise ValueError(f"数据包安装出错：{e}")
        pack["ok"] = r
        if r is None:
            raise ValueError("数据包无法下载")

    from_pack_fn = from_pack
    jobs = (("最新汉化包（SC汉化盒子）", localization.update),) + (
        market + author if direct else (("数据包", from_pack),)
    )

    try:  # 在 AT 窗口里点「更新」时：几个下载线程的输出都要进窗口的更新记录
        from .app import task_runner

        task = task_runner.current_task()
    except Exception:
        task_runner, task = None, None

    def run(job):
        if task_runner and task:
            task_runner.adopt_task(task)
        title, fn = job
        print(f"—— 开始更新{title} ——")
        try:
            fn()
            print(f"✅ {title} 更新完成")
            return {"title": title, "ok": True}
        except Exception as e:
            if (
                fn is from_pack_fn and pack["ok"] is None
            ):  # 数据包下不到：不算失败、不报错（2026-11-13 老大定），下面只更新行情
                return {"title": title, "ok": False, "error": str(e)}
            print(f"❌ {title} 更新失败：{e}（不影响使用，继续用旧数据）")
            return {"title": title, "ok": False, "error": str(e)}

    # 几个数据源互不相关，同时下载：总时间≈最慢的那一个，而不是全部加起来（访问国外慢的网络下差别很大）
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(len(jobs)) as ex:
        results = list(ex.map(run, jobs))
    if (
        not direct and pack["ok"] is None
    ):  # 数据包连不上：行情（玩家上报的价格，游戏文件里没有）还是从 UEX 更新；别的数据等数据包
        print("—— 先只更新矿价和商店行情 ——")
        results = [r for r in results if r["title"] != "数据包"]
        with ThreadPoolExecutor(len(market)) as ex:
            results += list(ex.map(run, market))
    print("全部更新完成")
    try:
        data_pack.clear_caches()  # 不管走哪条路，换了文件就清缓存，不用重启
    except Exception:
        pass
    # 每一项成没成功（巡检和窗口都能直接看，不用从文字里找 ❌）
    return {
        "results": results,
        "ok": sum(r["ok"] for r in results),
        "total": len(results),
    }


def menu(restart=False):
    from .core import paths

    try:
        paths.migrate()  # 旧版本散落的文件搬到 data/ 和 userdata/
    except Exception:
        traceback.print_exc()
    from .core import settings
    from .system import showloc
    from .app.server import _single_instance, release_instance

    # 只允许开一个 AT：已经开着就把它的窗口叫出来，这次直接退出（不再弹管理员确认框、不再重复挂热键）
    if not _single_instance(restart):
        return
    if showloc.WIN and not showloc.is_admin() and settings.load()["admin"] is not False:
        # 你的游戏是管理员权限运行：热键（F8）要求助手也是管理员身份，
        # 否则 Windows 不让读游戏里的按键。默认直接用管理员身份重开。
        print("正在用管理员身份重新打开助手（Windows 会弹确认框，点「是」）…")
        print("（不想这样的话：在窗口「设置与更新」里关掉「以管理员身份运行」）")
        release_instance()  # 让管理员身份的新 AT 拿到「只开一个」的锁
        if showloc.relaunch_as_admin("menu"):
            settings.update(admin=True)
            return
        print("没能用管理员身份打开（可能点了「否」）。热键在游戏里会失效。")
        if not _single_instance():  # 没换成功：把锁拿回来，继续用普通身份
            return
    from .app.server import main as window

    window(restart=restart)


ENTRIES = {
    "menu": menu,
    "restart": lambda: menu(restart=True),
    "install": install,
    "update": update,
    "prices": update,
}


def _crash_log():
    from .core import paths

    paths.crash_log()


def _no_console():
    """用 pythonw 启动（exe 启动器）时没有命令行窗口：输出写进日志，出错弹框"""
    _crash_log()
    if sys.stdout is not None:
        return False
    from .core import paths

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
            ENTRIES[cmd]()
        except Exception:
            traceback.print_exc()
            _error_box(
                "助手出错了。错误已记进日志（设置页可导出），发给作者（游戏 ID：Adm_TT）看看。"
            )
        sys.exit(0)
    ENTRIES[cmd]()
