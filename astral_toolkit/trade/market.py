"""物品目录 + 玩家市场那半边的窄门（F 段 B2）：市场接口、物品查询、F8 只经这里拿目录、显示名、查价，碰不到库存。

现在包着 tasks/trade.trade() 那一个 Trade：目录、行情和库存在同一个库文件里，Trade 构造时还要做库存迁移，库存冻着不动。
新库存把 Trade 换掉时，只改 tasks/trade.market() 这一处（改成自己造目录和行情服务），用的地方不用动。
"""


class Market:
    def __init__(self, trade):
        self._t = trade

    @property
    def catalog(self):
        """物品目录（查名字、记中文别名）"""
        return self._t.catalog

    def label(self, item_id):
        """「中文名（英文名）」：Trade.label 原样"""
        return self._t.label(item_id)

    def lookup(self, query):
        """按名字搜物品 (物品列表, 出错说明)：Trade.lookup 原样"""
        return self._t.lookup(query)

    def prices(self, *args, **kwargs):
        """查价 (item, quality_group="q0", operation="sell", now=None)：参数原样转给 Trade.prices"""
        return self._t.prices(*args, **kwargs)
