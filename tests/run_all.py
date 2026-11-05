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
from astral_toolkit.navigation import navigate as _nav  # noqa: E402
from astral_toolkit.navigation import waypoints as _wp  # noqa: E402
from astral_toolkit.navigation import celestial as _cel  # noqa: E402

_nav.CALIB = _cel.CALIB = (
    _tmp / "rotation_calib.json"
)  # 自转相位校准写临时文件，不碰用户的 userdata（2026-10-28）
_nav.LAST = _cel.LAST = (
    _tmp / "last_position.json"
)  # locate(record=True) 记的最近位置也一样（2026-10-28 审查：以前写进真实 userdata）
_nav.WAYPOINTS = _wp.WAYPOINTS = (
    _tmp / "waypoints.json"
)  # 读路标的测试别读到本机的真实路标
from astral_toolkit.core import paths as _paths  # noqa: E402

# import 时把 DATA 下的路径绑成模块常量的模块，趁 paths.DATA 还是真实目录先导入一遍：
# 以前 crafting/loot 第一次 import 发生在 test_mining 里某条把 DATA 换成临时目录的测试中（经 position → places.code_zh → ensure →
# 建库 → import_loot），INDEX / DETAILS 从此绑在临时目录，test_wikelo_materials_all_have_source 在库已建好时总被跳过（收口 2，待做 ㉑）
import astral_toolkit.crafting.loot  # noqa: E402, F401
import astral_toolkit.crafting.shops  # noqa: E402, F401
import astral_toolkit.crafting.wikelo  # noqa: E402, F401
import astral_toolkit.update.localization  # noqa: E402, F401
import astral_toolkit.update.uex  # noqa: E402, F401

_OLD_USER = _paths.USER
_paths.USER = _tmp  # 运行时才取 paths.USER 的（地点编号、锁文件、升级目录）也写临时目录；import 时绑定的各测试自己 patch
_paths.SHOTS = _tmp / "shots"
_paths.LOGS = (
    _tmp / "logs"
)  # 日志也写临时目录（以前测试会往真实 userdata\logs 写 perf 日志）


def _off_userdata():
    """已经 import 的 astral_toolkit 模块里，import 时就绑定好、还指着真实 userdata 的路径，全搬到临时目录。
    以前漏了 navigate.USER：测试会读真实 userdata 里的星系编号表（2026-10-31 审查）"""
    for m in list(sys.modules.values()):
        if not getattr(m, "__name__", "").startswith("astral_toolkit"):
            continue
        for k, v in list(vars(m).items()):
            if isinstance(v, Path) and v.is_relative_to(_OLD_USER):
                setattr(m, k, _tmp / v.relative_to(_OLD_USER))


_off_userdata()

MODULES = [
    "tests.test_mining",
    "tests.test_trade",
    "tests.test_tools",
    "tests.test_tooltip_two_line",
    "tests.test_f8_retry",
    "tests.test_goals",
    "tests.test_loadout_sweep",
    "tests.test_run_directml",
    "tests.test_update",
    "tests.test_ret1_cleanup",
    "tests.test_data_pack",
    "tests.test_gridtext",
    "tests.test_camdir_sign",
    "tests.test_di_live",
    "tests.test_lifecycle",
    "tests.test_lifecycle_gates",
    "tests.test_gadget_pick",
    "tests.test_station_lifts",
    "tests.test_stage0",
    "tests.test_stage3",
    "tests.test_stage4",
    "tests.test_gpu_ocr",
    "tests.test_hover",
    "tests.test_inspector",
    "tests.test_debug_shots",
    "tests.test_f8_unsure_data_hint",
    "tests.test_ocr_module",
    "tests.test_nav_modules",
    "tests.test_system_modules",
    "tests.test_run_records",
    "tests.test_gamedata",
    "tests.test_gamedata_nav",
    "tests.test_feedback_guard",
    "tests.test_gamedata_b1",
    "tests.test_gamedata_b2",
    "tests.test_gd_k1",
    "tests.test_gamedata_craft",
    "tests.test_gamedata_b3",
    "tests.test_gamedata_mining",
    "tests.test_gamedata_arch",
    "tests.test_runtime_arch",
    "tests.test_junk_check",
    "tests.test_bootstrap",
    "tests.test_settings_view",
    "tests.test_runtime_results",
    "tests.test_runtime_output",
    "tests.test_runtime_session",
    "tests.test_runtime_session_clock",
    "tests.test_runtime_session_race",
    "tests.test_runtime_session_k1",
    "tests.test_live_commit",
    "tests.test_mining_inputs",
    "tests.test_mining_analysis",
    "tests.test_mining_presenter",
    "tests.test_gamedata_b4",
    "tests.test_gamedata_b6",
    "tests.test_gamedata_b5",
    "tests.test_ui_stream",
    "tests.test_ui_k0b",
    "tests.test_ui_k0c",
    "tests.test_ui_client",
    "tests.test_nav_session",
    "tests.test_nav_golden",
    "tests.test_catalog_golden",
    "tests.test_f8_golden",
    "tests.test_textkeys",
    "tests.test_catalog_search",
    "tests.test_catalog_shops",
    "tests.test_catalog_loot",
    "tests.test_catalog_presenter",
    "tests.test_catalog_usecases",
    "tests.test_catalog_market",
    "tests.test_pos_service",
    "tests.test_nav_fps",
    "tests.test_count_session",
]

if __name__ == "__main__":
    sys.exit(1 if run_all(MODULES) else 0)
