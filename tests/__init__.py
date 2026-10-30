"""自检。跑测试时交易库存（%LOCALAPPDATA%\\SCTradeCompanion\\inventory.db，玩家真实的库存）一律指到临时目录：
任何测试不小心用到默认的交易库（tasks.trade.trade()），也只会碰临时的那份，绝不碰真实库存（用户 2026-10-23 定的规矩）"""
import os
import tempfile

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="dubhe_test_localappdata_")

# 2026-10-30 重构阶段 4：services.py 删了，patch_services 也删了。测试直接换名字所在的模块
# （tasks/*、app/hud_state.py，引擎换 EngineManager.get_instance() 上的）；一个名字被几个模块 import 了的，几个一起换。
