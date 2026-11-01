"""库的表结构：建表和索引语句按顺序执行。表改了就升 SCHEMA_VERSION；导入规则改了（表没变）就升 IMPORTER_VERSION

试点（批 1）用到的表。各列对应的源字段见 docs/superpowers/specs/2026-11-02-gamedata-callsites.md。"""

SCHEMA_VERSION = 2  # 2：加星图 / 城市地点 / 设施 / 空间站电梯 / 地名对照 / 挖矿点（批 2 公共层，2026-11-02）
IMPORTER_VERSION = 2

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
    # ---- 以下 schema 2：导航（对应 docs/superpowers/specs/2026-11-02-gamedata-callsites-b2.md）
    # starmap.json bodies：天体
    """CREATE TABLE bodies (
        name TEXT PRIMARY KEY,
        sys TEXT NOT NULL,
        x REAL NOT NULL, y REAL NOT NULL, z REAL NOT NULL,
        rot REAL, adj REAL, r REAL, om REAL, grid REAL,
        source_order INTEGER NOT NULL
    )""",
    # starmap.json pois：地表 / 轨道兴趣点；norm_n = 小写去非字母数字（names._norm）
    """CREATE TABLE pois (
        id INTEGER PRIMARY KEY,
        b TEXT NOT NULL,
        n TEXT NOT NULL,
        t TEXT NOT NULL DEFAULT '',
        x REAL NOT NULL, y REAL NOT NULL, z REAL NOT NULL,
        qt INTEGER,
        norm_n TEXT NOT NULL,
        source_order INTEGER NOT NULL
    )""",
    "CREATE INDEX idx_pois_b ON pois(b)",
    "CREATE INDEX idx_pois_norm ON pois(norm_n)",
    # starmap.json points（已套 starmap_fixes）：星、行星、拉格朗日点、星门；i = 内部名
    """CREATE TABLE points (
        id INTEGER PRIMARY KEY,
        n TEXT NOT NULL,
        i TEXT NOT NULL,
        sys TEXT NOT NULL,
        t TEXT NOT NULL DEFAULT '',
        x REAL NOT NULL, y REAL NOT NULL, z REAL NOT NULL,
        norm_n TEXT NOT NULL,
        i_lower TEXT NOT NULL,
        source_order INTEGER NOT NULL
    )""",
    "CREATE INDEX idx_points_norm ON points(norm_n)",
    "CREATE INDEX idx_points_i ON points(i_lower)",
    # city_places.json 经 transit._city_rows 变换后的行（t='City'、qt=0 读时补）
    """CREATE TABLE city_places (
        id TEXT PRIMARY KEY,
        b TEXT NOT NULL,
        n TEXT NOT NULL,
        zh TEXT NOT NULL DEFAULT '',
        x REAL NOT NULL, y REAL NOT NULL, z REAL NOT NULL,
        cat TEXT NOT NULL DEFAULT '',
        area TEXT NOT NULL DEFAULT '',
        city TEXT NOT NULL DEFAULT '',
        city_zh TEXT NOT NULL DEFAULT '',
        site_en TEXT NOT NULL DEFAULT '',
        line TEXT NOT NULL DEFAULT '',
        stop TEXT NOT NULL DEFAULT '',
        space INTEGER NOT NULL DEFAULT 0,
        sys TEXT NOT NULL DEFAULT '',
        up_x REAL, up_y REAL, up_z REAL,
        source_order INTEGER NOT NULL
    )""",
    "CREATE INDEX idx_city_places_city ON city_places(city)",
    "CREATE INDEX idx_city_places_line ON city_places(city, line)",
    """CREATE TABLE city_place_kinds (
        place_id TEXT NOT NULL REFERENCES city_places(id),
        kind TEXT NOT NULL,
        PRIMARY KEY (place_id, kind)
    )""",
    "CREATE INDEX idx_city_place_kinds_kind ON city_place_kinds(kind)",
    # place_amenities.json：城外设施；ref 的六种键（transit.amenity_targets 实际读的）原样拆列，读时回查星图
    """CREATE TABLE amenities (
        id INTEGER PRIMARY KEY,
        en TEXT NOT NULL,
        zh TEXT NOT NULL DEFAULT '',
        rec_lower TEXT NOT NULL DEFAULT '',
        ref_poi TEXT NOT NULL DEFAULT '',
        ref_body TEXT NOT NULL DEFAULT '',
        ref_local_x REAL, ref_local_y REAL, ref_local_z REAL,
        ref_point TEXT NOT NULL DEFAULT '',
        ref_point_id TEXT NOT NULL DEFAULT '',
        ref_city TEXT NOT NULL DEFAULT '',
        source_order INTEGER NOT NULL
    )""",
    """CREATE TABLE amenity_kinds (
        amenity_id INTEGER NOT NULL REFERENCES amenities(id),
        kind TEXT NOT NULL,
        PRIMARY KEY (amenity_id, kind)
    )""",
    "CREATE INDEX idx_amenity_kinds_kind ON amenity_kinds(kind)",
    # station_lifts.json：每站一行，payload_json 是 transit._lift_rows 校验通过的整站原样（路由算法消费嵌套树，拆表无收益）
    """CREATE TABLE station_lifts (
        station_key TEXT PRIMARY KEY,
        station TEXT NOT NULL,
        sys TEXT NOT NULL DEFAULT '',
        space INTEGER NOT NULL DEFAULT 0,
        worst_m INTEGER,
        payload_json TEXT NOT NULL,
        source_order INTEGER NOT NULL
    )""",
    # places_zh.json + places_extra_zh.json：两份都存，src = zh / extra；names.poi_zh 读时 extra 优先，position 那一路只看 zh
    """CREATE TABLE place_names (
        norm_key TEXT NOT NULL,
        zh TEXT NOT NULL,
        src TEXT NOT NULL,
        source_order INTEGER NOT NULL,
        PRIMARY KEY (norm_key, src)
    )""",
    # place_codes_zh.json：小写地点代码 → 中文
    """CREATE TABLE place_codes (
        code TEXT PRIMARY KEY,
        zh TEXT NOT NULL,
        source_order INTEGER NOT NULL
    )""",
    # mining_spots.json：挖矿点，坐标存原始米（navigate 自己 /1000）；每行都留（无 id、重复 id 也留），spot_id 是源里的 id
    """CREATE TABLE mining_spots (
        id INTEGER PRIMARY KEY,
        spot_id TEXT,
        sys TEXT NOT NULL DEFAULT '',
        zh TEXT NOT NULL DEFAULT '',
        en TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT '',
        area TEXT NOT NULL DEFAULT '',
        x REAL NOT NULL, y REAL NOT NULL, z REAL NOT NULL,
        source_order INTEGER NOT NULL
    )""",
]
