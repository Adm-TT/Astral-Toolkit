"""库的表结构：建表和索引语句按顺序执行。表改了就升 SCHEMA_VERSION；导入规则改了（表没变）就升 IMPORTER_VERSION

试点（批 1）用到的表。各列对应的源字段见 docs/superpowers/specs/2026-11-02-gamedata-callsites.md。"""

SCHEMA_VERSION = 1
IMPORTER_VERSION = 1

DDL: list[str] = [
    # 清单和版本：schema_version / importer_version / data_version / generation_id / build_time / src:<文件名>=sha256
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    # 物品目录：item_id 是规范化英文名（itemsearch.en_key），不是任何外部编号
    """CREATE TABLE items (
        item_id TEXT PRIMARY KEY,
        en TEXT NOT NULL,
        zh TEXT NOT NULL DEFAULT '',
        cat TEXT NOT NULL DEFAULT '',
        has_shop INTEGER NOT NULL,
        has_loot INTEGER NOT NULL,
        loc INTEGER NOT NULL,
        wiki INTEGER NOT NULL,
        wtype TEXT NOT NULL DEFAULT '',
        wsize INTEGER,
        desc TEXT NOT NULL DEFAULT '',
        variant INTEGER NOT NULL,
        zlen INTEGER NOT NULL,
        source_order INTEGER NOT NULL
    )""",
    # 物品的各种名字：kind = en / zh_loc（汉化包）/ zh_loot（掉落数据）/ aka（旧写法）；norm 是比较键（zh_key / en_key）
    """CREATE TABLE item_names (
        item_id TEXT NOT NULL REFERENCES items(item_id),
        lang TEXT NOT NULL,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        norm TEXT NOT NULL,
        source_order INTEGER NOT NULL
    )""",
    "CREATE INDEX idx_item_names_norm ON item_names(norm)",
    "CREATE INDEX idx_item_names_item ON item_names(item_id)",
    # 外部编号 → 物品：source = uex（商店物品 id）/ loot_uuid / class（游戏类名）
    """CREATE TABLE item_source_ids (
        source TEXT NOT NULL,
        external_id TEXT NOT NULL,
        item_id TEXT NOT NULL REFERENCES items(item_id),
        PRIMARY KEY (source, external_id)
    )""",
    # shops.json 的 rows 原样 7 列
    """CREATE TABLE shop_rows (
        uex_item_id INTEGER NOT NULL,
        shop_name TEXT NOT NULL,
        place_text TEXT NOT NULL,
        price_buy REAL NOT NULL,
        price_sell REAL NOT NULL,
        version TEXT NOT NULL,
        f0 TEXT NOT NULL, f1 TEXT NOT NULL, f2 TEXT NOT NULL,
        f3 TEXT NOT NULL, f4 TEXT NOT NULL, f5 TEXT NOT NULL,
        source_order INTEGER NOT NULL
    )""",
    "CREATE INDEX idx_shop_rows_item ON shop_rows(uex_item_id)",
    "CREATE INDEX idx_shop_rows_shop ON shop_rows(shop_name)",
    # loot_index.json 的 rows 原样 6 列
    """CREATE TABLE loot_rows (
        uuid TEXT PRIMARY KEY,
        en TEXT NOT NULL,
        cls TEXT NOT NULL,
        rarity TEXT NOT NULL,
        n INTEGER NOT NULL,
        zh TEXT NOT NULL DEFAULT '',
        source_order INTEGER NOT NULL
    )""",
    "CREATE INDEX idx_loot_rows_cls ON loot_rows(cls)",
    # prices.json：矿物 × 城市 收购价
    """CREATE TABLE mineral_prices (
        mineral TEXT NOT NULL,
        city TEXT NOT NULL,
        price REAL NOT NULL,
        PRIMARY KEY (mineral, city)
    )""",
]
