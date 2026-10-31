"""游戏辅助后台进程：1.1.2 起删除。
双击 W 自动跑、防挂机都删了，AT 不再替玩家按任何键。这里只留几个名字，旧代码、旧设置调用时什么也不做；
老版本留下的「自动跑中」标记和还在跑的辅助进程会被清掉。远程重启请求（userdata/restart_request）照旧处理。
"""

from ..core.paths import LOGS, USER, ROOT, self_cmd

LOG = LOGS / "helpers_log.txt"
FLAG = USER / ".autorun_on"  # 老版本的「自动跑中」标记：启动时删掉
RESTART_REQUEST = USER / "restart_request"
_proc = None


def autorun_on():
    return False


def _restart_requested():
    """userdata 里有 restart_request：替主程序「重新启动」一次（远程帮你重启时用）"""
    if not RESTART_REQUEST.exists():
        return False
    try:
        RESTART_REQUEST.unlink()
    except OSError:
        return False
    import subprocess
    import sys

    subprocess.Popen(
        self_cmd("restart"),
        cwd=str(ROOT),
        creationflags=0x08000000 if sys.platform == "win32" else 0,
    )
    return True


def start():
    """以前用来启动辅助进程；现在不再有辅助进程，只处理重启请求、清掉老标记。总是返回 False"""
    stop_helpers()
    _restart_requested()
    return False


def clear_startup():
    """AT 刚启动时调：清掉老标记；留下的重启请求直接删掉，不用再重启（刚启动本来就是新进程）。
    S5 第 4 批审查 2026-10-31：启动时走 start() 会拉起一个 restart 进程，它拿上次留下的 window_url.txt 叫不动这个 AT，
    空等 60 秒后弹「上一个 AT 还没退出」"""
    stop_helpers()
    try:
        RESTART_REQUEST.unlink(missing_ok=True)
    except OSError:
        pass


def stop_helpers():
    global _proc
    if _proc and _proc.poll() is None:
        _proc.terminate()
    _proc = None
    try:
        if FLAG.exists():
            FLAG.unlink()
    except OSError:
        pass


def status_line():
    return "辅助：无（1.1.2 起 AT 不再模拟按键）"


def menu():
    print(status_line())


def main(parent_pid=0):
    """老版本主程序会用 `helpers <pid>` 拉起辅助进程：现在直接退出"""
    _restart_requested()
