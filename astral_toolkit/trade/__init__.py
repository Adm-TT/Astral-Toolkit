"""交易：UEX + SCM 玩家市场查价、库存管理、截图入库（由 SC Trade Companion 重构进助手，去掉独立窗口）

核心逻辑（价格口径、缓存限流、库存流水、撤销）沿用原工具；界面改为助手菜单 + 游戏内热键 + 悬浮窗。
1.6.58 起库存在 %LOCALAPPDATA%\\SCTradeCompanion\\dubhe_inventory.db（表结构重新设计）；旧的 inventory.db 不动，第一次启动时导一份过来。
"""
