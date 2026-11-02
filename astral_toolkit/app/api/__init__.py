"""接口层（2026-10-30 重构阶段 0，NGU 设计第 4 节）

- router.py：收集本包里每个 Controller 模块的 ROUTES，统一调用、统一返回格式（阶段 4 起 services.py 已删，没有别的接口来源）
- <领域>.py（阶段 1–3 加）：接口函数，文件末尾 ROUTES = {"接口名": 函数, …}，router 自动收集
"""
