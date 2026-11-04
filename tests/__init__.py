"""自检。跑测试时交易库存（%LOCALAPPDATA%\\SCTradeCompanion\\inventory.db，玩家真实的库存）一律指到临时目录：
任何测试不小心用到默认的交易库（tasks.trade.trade()），也只会碰临时的那份，绝不碰真实库存（用户 2026-10-23 定的规矩）"""

import os
import tempfile

from tests.minipytest import ROOT as _TMP_ROOT

# 放在本轮临时目录里：不往 C 盘写，全部通过时跟着一起删
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(
    prefix="at_test_localappdata_", dir=_TMP_ROOT
)
os.environ["AT_FEEDBACK_OFF"] = (
    "1"  # 测试一律不往服务器发反馈：以前只在 run_all 里设，单跑一个模块会漏（2026-11-01 收件箱出现过测试数据）
)

# 2026-10-30 重构阶段 4：services.py 删了，patch_services 也删了。测试直接换名字所在的模块
# （tasks/*、app/hud_state.py；引擎用 bootstrap.build("test") 造出来的 app 上的；一个名字被几个模块 import 了的，几个一起换）。
