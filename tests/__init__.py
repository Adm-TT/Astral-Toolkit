"""自检。跑测试时交易库存（%LOCALAPPDATA%\\SCTradeCompanion\\inventory.db，玩家真实的库存）一律指到临时目录：
任何测试不小心用到默认的交易库（services.trade()），也只会碰临时的那份，绝不碰真实库存（用户 2026-10-23 定的规矩）"""
import os
import tempfile

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="dubhe_test_localappdata_")


def patch_services(monkeypatch, name, value):
    """换 services 上的一个名字，sc_mining/tasks/ 和 sc_mining/app/hud_state 里同名的一起换。
    NGU 重构后 services 只是转发层，真正干活的在 tasks/*；只换 services 打不中（2026-10-30 合并时 6 个测试因此失败，反馈导出写到了真桌面）"""
    import importlib, pkgutil
    from sc_mining import tasks
    from sc_mining.app import services
    monkeypatch.setattr(services, name, value)
    mods = [f"sc_mining.tasks.{m.name}" for m in pkgutil.iter_modules(tasks.__path__)]
    mods.append("sc_mining.app.hud_state")      # 2026-10-30 阶段 0：基础 HUD 搬到 hud_state，_note_hud 等在那里调自己的 _hud
    for modname in mods:
        mod = importlib.import_module(modname)
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, value)
