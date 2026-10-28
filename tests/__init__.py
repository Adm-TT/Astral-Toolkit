"""自检。跑测试时交易库存（%LOCALAPPDATA%\\SCTradeCompanion\\inventory.db，玩家真实的库存）一律指到临时目录：
任何测试不小心用到默认的交易库（services.trade()），也只会碰临时的那份，绝不碰真实库存（用户 2026-10-23 定的规矩）"""
import os
import tempfile

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="dubhe_test_localappdata_")
