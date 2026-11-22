"""新界面的一级分类（catalog/topclass）和接口 item_tags"""

from astral_toolkit.catalog import topclass as T
from astral_toolkit.tasks import catalog as C
from astral_toolkit.tasks.catalog_queries import search as S


def test_top_class_shop_category_first():
    assert T.top_class("Personal Weapons", "WeaponPersonal", "P4-AR Rifle") == "weapon"
    assert T.top_class("Helmets", "Char_Armor_Helmet") == "armor"
    assert T.top_class("Power Plants", "PowerPlant") == "ship"
    assert T.top_class("Foods", "") == "consumable"


def test_top_class_falls_back_to_wiki_type():
    assert T.top_class("", "Char_Clothing_Torso_1") == "armor"
    assert T.top_class("", "Flair_Wall") == "collectible"
    assert T.top_class("", "ShieldController") == "ship"
    assert T.top_class("", "RemovableChip") == "access"
    assert T.top_class("", "Cargo") == "material"


def test_magazines_are_ammo_not_attachments():
    assert (
        T.top_class("Attachments", "WeaponAttachment", "P4-AR Magazine (40 Cap)")
        == "ammo"
    )
    assert T.top_class("Attachments", "WeaponAttachment", "Gamma (1x)") == "attachment"
    assert T.top_class("Helmets", "", "Magazine Helmet") == "armor"


def test_unsure_stays_unclassified():
    assert T.top_class() == "unclassified"
    assert T.top_class("Miscellaneous", "Gadget") == "unclassified"
    assert T.top_class(None, None, None) == "unclassified"
    assert T.top_class(3, ["x"], 5) == "unclassified"  # pyright: ignore[reportArgumentType]
    assert T.top_class("", "Char_Head_Piercings") == "armor"


def test_every_rule_points_at_a_listed_class():
    keys = {k for k, _ in T.CLASSES}
    assert len(keys) == len(T.CLASSES) == 10
    assert set(T._CAT.values()) | set(T._WTYPE.values()) <= keys


def test_item_tags_route_shape(monkeypatch):
    rows = {
        "P4-AR Rifle": {
            "cat": "Personal Weapons",
            "wtype": "WeaponPersonal",
            "wsize": 2,
        },
        "JS-300": {"cat": "", "wtype": "PowerPlant", "wsize": 1},
    }
    monkeypatch.setattr(S, "lookup", lambda en: rows.get(en))
    d = C.item_tags(names=["P4-AR Rifle", "JS-300", "不存在", "P4-AR Rifle", "", 7])
    assert [c["key"] for c in d["classes"]][0] == "weapon" and len(d["classes"]) == 10
    assert d["items"] == {
        "P4-AR Rifle": {"top": "weapon", "size": 2, "known": True},
        "JS-300": {"top": "ship", "size": 1, "known": True},
        "不存在": {"top": "unclassified", "size": None, "known": False},
    }


def test_item_tags_accepts_one_name_and_caps_the_batch(monkeypatch):
    monkeypatch.setattr(S, "lookup", lambda en: None)
    assert list(C.item_tags(names="X")["items"]) == ["X"]
    many = [f"n{i}" for i in range(C.TAGS_MAX + 50)]
    assert len(C.item_tags(names=many)["items"]) == C.TAGS_MAX
    assert C.item_tags()["items"] == {}
    for odd in (5, {"A": 1}, b"X", None):
        assert C.item_tags(names=odd)["items"] == {}


def test_item_tags_through_the_route_table(monkeypatch):
    from astral_toolkit.app.api import router

    monkeypatch.setattr(S, "lookup", lambda en: {"cat": "Foods", "wsize": 1})
    r = router.call("item_tags", {"names": ["Burrito"]})
    assert r["ok"] and r["data"] == C.item_tags(names=["Burrito"])
    assert r["data"]["items"]["Burrito"]["top"] == "consumable"
