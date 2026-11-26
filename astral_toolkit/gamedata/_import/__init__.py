"""把读好的源 JSON 变成库里的行

import_items 逐段复现 crafting/itemsearch.py:_build_locked() 的合并规则（行号指 main 4facdc5），折叠函数直接 import 复用、不抄。
改了这里的规则要升 _schema.IMPORTER_VERSION。对应关系见 docs/superpowers/specs/2026-11-02-gamedata-callsites.md。

2026-11-26 按建库的段拆成几个文件（只搬家，规则没变）：
- _common：取源、列值清洗、坐标和逐条变换
- names / items：schema 1（名字、物品、商店、掉落、价格）
- places：schema 2 导航和地点注册表
- crafting：schema 4 制造 / 维科洛 / 物品属性
- mining：schema 6 采矿
外面照旧写 _import.import_xxx，名字都从这里转出去（外面在用的 _s、_names_table 也是）。"""

from ._common import _s
from .crafting import (
    import_crafting,
    import_item_stats,
    import_print_spots,
    import_ship_items,
    import_wikelo,
)
from .items import import_items, import_loot, import_prices, import_shops
from .mining import import_mining_rocks, import_refinery_yields, import_ship_signatures
from .names import (
    _names_table,
    import_name_pairs,
    import_wiki_classes,
    import_wiki_rows,
)
from .places import (
    import_amenities,
    import_city_places,
    import_mining_spots,
    import_place_names,
    import_places,
    import_starmap,
    import_station_lifts,
)

__all__ = [
    "_names_table",
    "_s",
    "import_amenities",
    "import_city_places",
    "import_crafting",
    "import_item_stats",
    "import_items",
    "import_loot",
    "import_mining_rocks",
    "import_mining_spots",
    "import_name_pairs",
    "import_place_names",
    "import_places",
    "import_prices",
    "import_print_spots",
    "import_refinery_yields",
    "import_ship_items",
    "import_ship_signatures",
    "import_shops",
    "import_starmap",
    "import_station_lifts",
    "import_wiki_classes",
    "import_wiki_rows",
    "import_wikelo",
]
