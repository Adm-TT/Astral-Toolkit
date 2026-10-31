"""跑全部自检：python -m tests.run_all"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["AT_FEEDBACK_OFF"] = "1"  # 测试里不往服务器发问题反馈（2026-10-27）

from tests.minipytest import run_all, tmpdir  # noqa: E402

_tmp = tmpdir()
from sc_mining.navigation import navigate as _nav  # noqa: E402

_nav.CALIB = (
    _tmp / "rotation_calib.json"
)  # 自转相位校准写临时文件，不碰用户的 userdata（2026-10-28）
_nav.LAST = (
    _tmp / "last_position.json"
)  # locate(record=True) 记的最近位置也一样（2026-10-28 审查：以前写进真实 userdata）
_nav.WAYPOINTS = _tmp / "waypoints.json"  # 读路标的测试别读到老大的真实路标
from sc_mining.core import paths as _paths  # noqa: E402

_OLD_USER = _paths.USER
_paths.USER = _tmp  # 运行时才取 paths.USER 的（地点编号、锁文件、升级目录）也写临时目录；import 时绑定的各测试自己 patch
_paths.SHOTS = _tmp / "shots"
_paths.LOGS = (
    _tmp / "logs"
)  # 日志也写临时目录（以前测试会往真实 userdata\logs 写 perf 日志）


def _off_userdata():
    """已经 import 的 sc_mining 模块里，import 时就绑定好、还指着真实 userdata 的路径，全搬到临时目录。
    以前漏了 navigate.USER：测试会读真实 userdata 里的星系编号表（2026-10-31 审查）"""
    for m in list(sys.modules.values()):
        if not getattr(m, "__name__", "").startswith("sc_mining"):
            continue
        for k, v in list(vars(m).items()):
            if isinstance(v, Path) and v.is_relative_to(_OLD_USER):
                setattr(m, k, _tmp / v.relative_to(_OLD_USER))


_off_userdata()

MODULES = [
    "tests.test_mining",
    "tests.test_trade",
    "tests.test_tools",
    "tests.test_goals",
    "tests.test_loadout_sweep",
    "tests.test_upgrade",
    "tests.test_update",
    "tests.test_data_pack",
    "tests.test_gridtext",
    "tests.test_station_lifts",
    "tests.test_stage0",
    "tests.test_stage3",
    "tests.test_stage4",
    "tests.test_gpu_ocr",
    "tests.test_hover",
    "tests.test_inspector",
    "tests.test_ocr_module",
]

if __name__ == "__main__":
    sys.exit(1 if run_all(MODULES) else 0)
