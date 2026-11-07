"""功能工作线程（目录迁移章程 §5）：定位（position）、导航（navigation、game_events）、采矿（mining）、
热键（hotkeys）、盘点（count）都搬进来了。

每个工作线程只管周期、暂停、停止、会话有效性和结果提交；读屏、分析、发布由 bootstrap 用窄函数接进来。
本文件不导入任何东西（import 不起线程、不碰读屏和资料）。
"""
