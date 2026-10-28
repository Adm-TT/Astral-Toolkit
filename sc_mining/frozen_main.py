"""独立打包版（PyInstaller，2026-10-26）的入口：AT.exe [入口] [参数…]

  AT.exe                 打开 AT（和以前 Dubhe.exe 一样）
  AT.exe restart         重新启动（托盘「重新启动」、升级后用）
  AT.exe helpers <pid>   后台辅助进程（防挂机、双击 W 自动跑）
  AT.exe admin <入口>    管理员身份重开时用
  AT.exe selftest        自检：模块、数据、文字识别、计算、本机服务，结果写进 userdata\\logs\\selftest.txt
Python 版不用这个文件（照旧 python -m sc_mining.run）
"""
import sys
import traceback


def _velopack():
    """Velopack 安装版（2026-10-27）：必须最先调用——安装、升级、卸载时 Velopack 会带着特殊参数运行 AT.exe，
    在这里处理完就直接退出；平时什么也不做。没装 velopack 组件（开发时、老的 Inno 版）就跳过"""
    try:
        import velopack
        velopack.App().run()
    except Exception:                          # 组件坏了：写进日志，照常打开 AT（钩子调用由 main 拦下，不会走到这里以外）
        try:
            from sc_mining import paths
            with open(paths.LOGS / "velopack_error.txt", "a", encoding="utf-8") as f:
                f.write(traceback.format_exc())
        except Exception:
            pass


HOOKS = ("--veloapp-install", "--veloapp-updated", "--veloapp-obsolete", "--veloapp-uninstall")   # Velopack 的 4 个钩子


def main():
    hook = any(a in HOOKS for a in sys.argv[1:])
    _velopack()
    if hook:                                    # 安装 / 升级 / 卸载时 Velopack 的调用：不能把整个 AT（托盘、热键、窗口）跑起来（二审 2026-10-27）
        sys.exit(0)
    args = sys.argv[1:]
    cmd = args[0] if args else "menu"
    if cmd == "ocrworker":                      # 显卡 OCR 小进程（采矿助手开着时，2026-10-27）：只认字，别的都不跑
        from sc_mining import gpu_ocr
        gpu_ocr.worker_main()
        sys.exit(0)
    from sc_mining import paths
    try:
        paths.seed_data()                       # Velopack 版：新版本第一次运行，把自带的数据放到外面的 data\
        paths.import_inno()                     # 直接装 Velopack 版的老用户：把老 Inno 版的设置和记录搬过来
    except Exception:
        traceback.print_exc()
    from sc_mining import run
    if cmd == "selftest":
        from sc_mining import selftest
        sys.exit(selftest.main())
    silent = run._no_console()
    try:
        if cmd == "helpers":
            from sc_mining import helpers
            helpers.main(int(args[1]) if len(args) > 1 else 0)
        elif cmd == "admin":
            run.run_entry(args[1] if len(args) > 1 else "menu")
        else:
            (run.nav if cmd == "nav" else run.ENTRIES.get(cmd, run.ENTRIES["menu"]))()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        if silent:
            run._error_box("AT 出错了。错误已记进日志（设置页可导出），发给作者（游戏 ID：Adm_TT）。")
    sys.exit(0)


if __name__ == "__main__":
    main()
