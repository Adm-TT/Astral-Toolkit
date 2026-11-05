"""物品与交易查询的领域规则（架构稿 §5.1 的 catalog）：匹配、排序、筛选、汇总的纯函数。

只 import 标准库和 astral_toolkit.contracts；读文件、联网、缓存、gamedata 查询留在调用方（crafting/*、tasks）。
"""
