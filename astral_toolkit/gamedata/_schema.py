"""库的表结构：建表和索引语句按顺序执行。表改了就升 SCHEMA_VERSION；导入规则改了（表没变）就升 IMPORTER_VERSION

各列对应的源字段见 docs/superpowers/specs/ 下各批矩阵：2026-11-02-gamedata-callsites.md（批 1）、-b2（导航）、-b3（制造 / 维科洛 / 物品属性）、gd-b4（掉落）、gd-b6（名字对照）。"""

SCHEMA_VERSION = 6  # 2：导航表；3：shop_items；4：制造 / 维科洛 / 物品属性等；5：可空文本列存 NULL、q 保留类型；6：采矿石头表 / 舰船截面 / 精炼站加成（批 5 公共层，2026-11-02）
IMPORTER_VERSION = 7  # 7：item_stats 空 dict 条目不入库（收口 2，2026-11-02）

DDL: list[str] = [
    # 清单和版本：schema_version / importer_version / data_version / generation_id / build_time / src:<文件名>=sha256
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    # 物品目录：item_id 是规范化英文名（contracts.textkeys.en_key），不是任何外部编号
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
    # shops.json 的 items 原样：uex 编号 → 英文名、类别，按字典顺序。shops.find / variants / cheapest_buy 在它上面扫，
    # 不能用合并后的 items 表代替（同一折叠名两种写法只会留一个，如 Synergy / Synergy+）
    """CREATE TABLE shop_items (
        uex_item_id INTEGER PRIMARY KEY,
        en TEXT NOT NULL,
        cat TEXT NOT NULL DEFAULT '',
        source_order INTEGER NOT NULL
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
    # schema 4 加三列（批 4 公共层）：norm_en / norm_zh = contracts.textkeys.fold_mixed_loose（find 的比较键，源里原样 en/zh 折叠，不做中英对调）；
    # cls_lower = cls 小写（mine_info 按前缀筛；真实数据 uuid 无重复、各列无 None，2026-11-02 核过）
    """CREATE TABLE loot_rows (
        uuid TEXT PRIMARY KEY,
        en TEXT NOT NULL,
        cls TEXT NOT NULL,
        rarity TEXT NOT NULL,
        n INTEGER NOT NULL,
        zh TEXT NOT NULL DEFAULT '',
        norm_en TEXT NOT NULL,
        norm_zh TEXT NOT NULL DEFAULT '',
        cls_lower TEXT NOT NULL DEFAULT '',
        source_order INTEGER NOT NULL
    )""",
    "CREATE INDEX idx_loot_rows_cls ON loot_rows(cls)",
    "CREATE INDEX idx_loot_rows_norm_en ON loot_rows(norm_en)",
    "CREATE INDEX idx_loot_rows_norm_zh ON loot_rows(norm_zh)",
    "CREATE INDEX idx_loot_rows_cls_lower ON loot_rows(cls_lower)",
    # wiki_items.json 的游戏类名（cls + alt[] 同一列多行），norm_n = contracts.textkeys.fold_mixed_loose(n)：loot._wiki_classes 用（批 4 公共层）。
    # 不能用 item_source_ids('class') 代替：那张表没有 alt、同名只留首个、折叠规则是 en_key
    """CREATE TABLE wiki_classes (
        norm_n TEXT NOT NULL,
        cls_lower TEXT NOT NULL,
        source_order INTEGER NOT NULL
    )""",
    "CREATE INDEX idx_wiki_classes_norm_n ON wiki_classes(norm_n)",
    # ---- 批 6 公共层（names / gamekey）：三张「原样、有序」表，不过物品目录的合并 / 过滤（item_names 是过滤后的，gamekey / names.table 用不了）
    # trade/names.table() 的结果原样：_import._names_table 的规则；src = zh_names / zh_only
    """CREATE TABLE zh_name_pairs (
        source_order INTEGER PRIMARY KEY,
        zh TEXT NOT NULL,
        en TEXT NOT NULL,
        src TEXT NOT NULL
    )""",
    # wiki_items.json 的 items 原样（全部行，含噪声物品）；cls 保留原大小写（localization.wiki_class_names 按原样当键）
    """CREATE TABLE wiki_items (
        id INTEGER PRIMARY KEY,
        n TEXT NOT NULL,
        cls TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE wiki_alt_classes (
        wiki_id INTEGER NOT NULL REFERENCES wiki_items(id),
        idx INTEGER NOT NULL,
        cls TEXT NOT NULL,
        PRIMARY KEY (wiki_id, idx)
    )""",
    # name_aliases.json 原样：全部 str→str 对，按 dict 顺序
    """CREATE TABLE name_alias_pairs (
        source_order INTEGER PRIMARY KEY,
        old TEXT NOT NULL,
        new TEXT NOT NULL
    )""",
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
    # ---------------------------------------------------------------- schema 4：制造 / 维科洛 / 物品属性（批 3 公共层，2026-11-02）
    # crafting.json blueprints：标量列原样（源里是 null 的存 NULL，不存 ''——消费方 GEAR_ZH[(g, None)] 这类键靠它）；slots（含每槽的改装列表）、src 整段存 JSON——消费方吃嵌套树，拆表无查询收益；
    # u（实体 uuid）真实数据里有重复和空值，不作主键，用自增 id。bp_key = contracts.blueprints.assign_keys 的「名字#序号」规则；
    # norm_n / norm_z = contracts.textkeys.blueprint_norm（for_item 规则），search_n / search_z = contracts.textkeys.blueprint_search_norm（search 规则）；
    # item_id = contracts.textkeys.en_key(n) 且在 items 表里才填（批 1 物品身份）
    """CREATE TABLE blueprints (
        id INTEGER PRIMARY KEY,
        u TEXT,
        n TEXT NOT NULL,
        z TEXT,
        g TEXT,
        t TEXT,
        s TEXT,
        m TEXT,
        sec INTEGER,
        d INTEGER NOT NULL DEFAULT 0,
        nsrc INTEGER,
        bp_key TEXT NOT NULL UNIQUE,
        norm_n TEXT NOT NULL,
        norm_z TEXT NOT NULL DEFAULT '',
        search_n TEXT NOT NULL,
        search_z TEXT NOT NULL DEFAULT '',
        item_id TEXT,
        slots_json TEXT NOT NULL,
        src_json TEXT NOT NULL,
        source_order INTEGER NOT NULL
    )""",
    "CREATE INDEX idx_blueprints_norm_n ON blueprints(norm_n)",
    "CREATE INDEX idx_blueprints_norm_z ON blueprints(norm_z)",
    "CREATE INDEX idx_blueprints_u ON blueprints(u)",
    "CREATE INDEX idx_blueprints_item ON blueprints(item_id)",
    # slots 平铺一份供「哪些蓝图用到某种材料」筛选：kind = r（原料）/ i（物品）；qty / min_q 原样（源里 qty 多为小数、min_q 整数）
    """CREATE TABLE blueprint_materials (
        blueprint_id INTEGER NOT NULL REFERENCES blueprints(id),
        slot_idx INTEGER NOT NULL,
        slot_name TEXT NOT NULL,
        opt_idx INTEGER NOT NULL,
        kind TEXT NOT NULL,
        material TEXT NOT NULL,
        qty REAL NOT NULL,
        min_q INTEGER NOT NULL,
        PRIMARY KEY (blueprint_id, slot_idx, opt_idx)
    )""",
    "CREATE INDEX idx_bp_materials_material ON blueprint_materials(material)",
    # wikelo.json contracts：标量原样（可空文本存 NULL；q 不声明类型，源里 int 就是 int、float 就是 float——goals 要原样乘数量）；
    # rewards / req / systems 各一张子表，idx 保序；req.norm_n = contracts.textkeys.fold_mixed_loose（uses 的比较规则）
    """CREATE TABLE wikelo_contracts (
        id TEXT PRIMARY KEY,
        type TEXT,
        t TEXT,
        te TEXT,
        rz TEXT,
        source_order INTEGER NOT NULL
    )""",
    """CREATE TABLE wikelo_rewards (
        contract_id TEXT NOT NULL REFERENCES wikelo_contracts(id),
        idx INTEGER NOT NULL,
        item TEXT NOT NULL,
        PRIMARY KEY (contract_id, idx)
    )""",
    """CREATE TABLE wikelo_requirements (
        contract_id TEXT NOT NULL REFERENCES wikelo_contracts(id),
        idx INTEGER NOT NULL,
        n TEXT,
        z TEXT,
        q,
        u TEXT,
        norm_n TEXT NOT NULL,
        norm_z TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (contract_id, idx)
    )""",
    "CREATE INDEX idx_wikelo_req_norm_n ON wikelo_requirements(norm_n)",
    """CREATE TABLE wikelo_contract_systems (
        contract_id TEXT NOT NULL REFERENCES wikelo_contracts(id),
        idx INTEGER NOT NULL,
        system TEXT NOT NULL,
        PRIMARY KEY (contract_id, idx)
    )""",
    # item_stats.json items：标量原样；s（属性字典，形状不一：{min,max} / {value} / 各种嵌套键）整段存 JSON，itemstats._get 按路径取
    """CREATE TABLE item_stats (
        uuid TEXT PRIMARY KEY,
        n TEXT,
        size INTEGER,
        grade TEXT,
        cls TEXT,
        type TEXT,
        sub TEXT,
        mass REAL,
        ver TEXT,
        mfr TEXT,
        cn TEXT,
        stats_json TEXT NOT NULL,
        source_order INTEGER NOT NULL
    )""",
    "CREATE INDEX idx_item_stats_n ON item_stats(n)",
    # print_spots.json items：打印机打印的物品在哪打
    """CREATE TABLE print_spots (
        item_name TEXT PRIMARY KEY,
        zh TEXT,
        cls TEXT,
        source_order INTEGER NOT NULL
    )""",
    """CREATE TABLE print_spot_places (
        item_name TEXT NOT NULL REFERENCES print_spots(item_name),
        idx INTEGER NOT NULL,
        place TEXT NOT NULL,
        PRIMARY KEY (item_name, idx)
    )""",
    # ship_items.json items：部件名 → 自带它出厂的船（中文名），保序
    """CREATE TABLE ship_stock_items (
        item_name TEXT NOT NULL,
        idx INTEGER NOT NULL,
        ship TEXT NOT NULL,
        PRIMARY KEY (item_name, idx)
    )""",
    # ---------------------------------------------------------------- schema 6：采矿（批 5 公共层，2026-11-02）
    # mining_rocks.json：顶层每个 dict 段（tiers / ores / areas / contains）按「段 + 键」一行，值整条 JSON 原样
    # （area_for_spot 要分得清 {} 和缺；百分比是 float、sig 是 int，JSON 原样不改类型；未知字段不丢）。
    # 哪些段在、非 dict 顶层键 → meta 'mining_rocks_meta' = {"sections": [...], "extra": {...}}（源缺失 / 坏时没有这个键）
    """CREATE TABLE mining_rock_entries (
        section TEXT NOT NULL,
        key TEXT NOT NULL,
        value_json TEXT NOT NULL,
        source_order INTEGER NOT NULL,
        PRIMARY KEY (section, key)
    )""",
    # ship_signatures.json 的 ships[]：整条 JSON 原样（shipsig.match 把源 dict 的所有键带给调用方）；source_order = 源下标
    """CREATE TABLE ship_signatures (
        source_order INTEGER PRIMARY KEY,
        ship_json TEXT NOT NULL
    )""",
    # prices.json 的 yields：精炼站 → {矿: 加成}，整站 JSON 原样（int / float 原样；{} 站也存——旧逻辑整站替换会清空该站）
    """CREATE TABLE refinery_yields (
        station TEXT PRIMARY KEY,
        bonus_json TEXT NOT NULL,
        source_order INTEGER NOT NULL
    )""",
]
