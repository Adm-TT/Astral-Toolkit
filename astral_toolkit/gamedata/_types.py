"""游戏数据层对外的公共类型和异常：接口只返回这里的冻结 dataclass，不返回 dict、不返回 sqlite 行

坐标 Vec3 的坐标系和单位在批 2（星图）开工时写进这里的文档字符串；地基阶段只定形状。"""

from dataclasses import dataclass


class GamedataError(Exception):
    """游戏数据层的错误基类"""


class GamedataUnavailable(GamedataError):
    """库不可用：还没建、清单坏了、库文件丢了、清单和库对不上。调用方不能把它当成“查不到”"""


class BuildError(GamedataError):
    """建库或发布失败：源文件缺失 / 坏掉、校验不过、写不进去。旧库和旧清单保持原样"""


@dataclass(frozen=True)
class Vec3:
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class Item:
    """物品目录里的一件：item_id 是本库主键（规范化英文名），不是任何外部编号"""

    item_id: str
    en: str
    zh: str
    cat: str
    has_shop: bool
    has_loot: bool
    loc: bool
    wiki: bool
    wtype: str
    wsize: int | None
    desc: str
    variant: bool


@dataclass(frozen=True)
class ItemCandidate:
    """模糊搜索 / OCR 纠错的轻量候选：只带名字和别名，不带整行"""

    item_id: str
    name: str
    aliases: tuple[str, ...]
    source_order: int


@dataclass(frozen=True)
class ShopRow:
    """shops.json 的一行原样映射（7 列）；价格是源里的 float，原样不转"""

    uex_item_id: int
    shop_name: str
    place_text: str
    price_buy: float
    price_sell: float
    version: str
    fields: tuple[str, str, str, str, str, str]
    source_order: int


@dataclass(frozen=True)
class ShopDistance:
    shop: ShopRow
    distance_m: float


@dataclass(frozen=True)
class Place:
    """地点（本期只定义类型，不建表；批 2 填）"""

    place_id: str
    name: str
    system: str
    body: str
    pos: Vec3 | None
