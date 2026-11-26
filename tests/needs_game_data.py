"""要真实游戏数据（data/ 下的星图、制造、汉化、价格等）才能跑的测试。

云端 CI 没有 data/，设了 AT_NO_GAME_DATA=1 时 tests.run_all 把这里列的跳过，其余照跑。
本机不设这个变量，全部照常跑，和以前一样。

规矩：
- 只登记「缺数据就过不了」的测试，按模块分组写清缺什么；写错名字、测试改名或删掉了，CI 会报错，不会悄悄不跑。
- 新写的测试最好自己在缺数据时 skip（像「没有星图数据」那样），不用往这里加。
"""

NEEDS_GAME_DATA: dict[str, set[str]] = {
    # 星图、制造蓝图、汉化包、矿价
    "tests.test_mining": {
        "test_crafting_dataset_and_links",
        "test_nav_matches_starmap",
        "test_overlay_paint_rules",
        "test_crafted_head_quality",
        "test_laser_power_naming_on_craft_page",
        "test_craft_stats_and_detail_structure",
        "test_mining_area_from_position",
        "test_review_102_area_never_guesses",
        "test_game_mining_spots_and_pyro_areas",
        "test_fill_name_exact_tier_before_one_edit",
    },
    # 汉化包（中文名 → 英文名）
    "tests.test_trade": {
        "test_chinese_to_english",
        "test_catalog_finds_english_item_by_chinese_name",
        "test_ocr_row_with_chinese_name_matches",
        "test_market_lookup_translates_for_english_only_source",
        "test_glued_quantity_and_quality",
        "test_tooltip_zh_only_medal_not_description",
    },
    "tests.test_tools_trade": {"test_trade_lookup_chinese"},
    # 星图、物品库
    "tests.test_tools_catalog": {
        "test_mineral_in_item_search_with_nav",
        "test_ground_gems_searchable_with_locations",
        "test_item_names_and_categories_unified",
    },
    "tests.test_tools_nav": {"test_display_label_lagrange_station"},
    "tests.test_tools_crafting": {"test_goal_shortage_marked_everywhere"},
    # 维科洛兑换、制造蓝图、星图地点
    "tests.test_goals": {
        "test_wikelo_goal_shortfall",
        "test_quality_gate_and_priority",
        "test_shared_stock_goes_by_priority",
        "test_add_stock_from_goal_page",
        "test_goal_quality_effect_and_stock_quality",
        "test_stock_places_list_and_match",
        "test_stock_out_set_move_and_places",
        "test_stock_bins_reserve_ledger_and_values",
        "test_goal_finish_deducts_stock",
        "test_crafted_item_qualities_from_bonus",
        "test_nav_goals_router_roundtrip",
    },
    "tests.test_stage4": {"test_showloc_hotkey_and_new_here_do_not_double_save"},
    "tests.test_crafting_api": {"test_b5_mining_and_mineral_page_go_through_usecases"},
    "tests.test_place_patches": {"test_patch_points_show_up_in_search"},
    # 星图地点（新巴贝奇等）
    "tests.test_stock_count_fixes": {
        "test_unknown_manual_place_validation_and_start",
        "test_bin_aliases_read_and_edit_atomically",
        "test_legacy_bin_default_and_unrelated_place_remain",
        "test_legacy_bin_default_and_desc_fill_official_blanks",
    },
}
