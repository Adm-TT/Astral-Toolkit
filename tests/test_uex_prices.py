"""UEX 城市收购价：只收精炼矿，同一终端原矿和精炼都报价时原矿那条不能盖掉精炼价

全部是假的 UEX 返回（monkeypatch uex._get），不联网、不读真实 data/、不写文件。"""

from contextlib import contextmanager


def _run_refresh(monkeypatch, rows, terminals=None):
    """用假返回跑一次 refresh，返回它要写进 prices.json 的内容"""
    import astral_toolkit.gamedata as G
    from astral_toolkit.core import paths
    from astral_toolkit.mining import data
    from astral_toolkit.update import uex

    written = []

    @contextmanager
    def fake_updating():
        yield

    monkeypatch.setattr(G, "updating", fake_updating)
    monkeypatch.setattr(paths, "write_json", lambda p, obj, **kw: written.append(obj))
    monkeypatch.setattr(
        data, "SELL_TERMINALS", terminals or {12: "Area18"}, raising=True
    )

    def fake_get(endpoint):
        if endpoint.startswith("commodities_prices"):
            tid = int(endpoint.rsplit("=", 1)[-1])
            return rows.get(tid, []) if isinstance(rows, dict) else rows
        return []

    monkeypatch.setattr(uex, "_get", fake_get)
    uex.refresh()
    assert len(written) == 1
    return written[0]


def _row(name, price):
    return {"commodity_name": name, "price_sell": price, "price_sell_avg": price}


def test_raw_after_refined_does_not_override(monkeypatch):
    out = _run_refresh(
        monkeypatch,
        [_row("Quantainium", 150000), _row("Quantainium (Raw)", 40000)],
    )
    assert out["prices"]["Quantainium"] == {"Area18": 150000}


def test_raw_before_refined_does_not_override(monkeypatch):
    out = _run_refresh(
        monkeypatch,
        [_row("Gold (Ore)", 9000), _row("Gold", 31000)],
    )
    assert out["prices"]["Gold"] == {"Area18": 31000}


def test_raw_only_is_not_used_as_refined_price(monkeypatch):
    """只报了原矿：不能把原矿价当精炼价记进去（没有就留空，apply_live 用内置快照）"""
    out = _run_refresh(monkeypatch, [_row("Taranite (Raw)", 8000)])
    assert "Taranite" not in out["prices"]


def test_pressurized_ice_still_maps_to_ice(monkeypatch):
    out = _run_refresh(
        monkeypatch,
        {
            12: [_row("Raw Ice", 1000), _row("Pressurized Ice", 5100)],
            18: [_row("Pressurized Ice", 4600)],
        },
        terminals={12: "Area18", 18: "Lorville"},
    )
    assert out["prices"]["Ice"] == {"Area18": 5100, "Lorville": 4600}
