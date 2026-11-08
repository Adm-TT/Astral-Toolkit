"""F8 第一遍没认准就等一下再截一次（RD-B1，老大 11-06 验收：说明框还没出来 / 没出完就按了）。

不截真屏幕、不碰真鼠标：截图、识别、悬浮窗、发布都换成替身。
"""

from types import SimpleNamespace

from astral_toolkit.mining import screen
from astral_toolkit.ocr import OcrToken
from astral_toolkit.tasks import hover as Hv
from astral_toolkit.trade import inspector as I


class _NoThread:
    def __init__(self, *a, **k):
        pass

    def start(self):
        pass


def _res(zh, en, sure):
    return {
        "zh": zh,
        "en": en,
        "quality": 0,
        "qty": 1,
        "unit": "个",
        "sure": sure,
        "raw": (zh, en),
        "canon": (zh, en) if sure else None,
        "craft": None,
        "tokens": [],
        "where": "50-70%@title",
    }


def _setup(monkeypatch, results):
    """grab 每次给一张新假图；inspect_item 按次序给结果，记下第几张图、whole_screen 传了什么，运行日志也记下。"""
    imgs, calls, logs = [], [], []

    def grab():
        im = SimpleNamespace(width=2560, height=1440, n=len(imgs))
        imgs.append(im)
        return im

    def inspect(img, cur, **kw):
        calls.append((getattr(img, "n", "给的"), kw.get("whole_screen", True)))
        return results[len(calls) - 1]

    from astral_toolkit.core import run_records
    from astral_toolkit.tasks.system import about

    monkeypatch.setattr(screen, "grab", grab)
    monkeypatch.setattr(Hv, "inspect_item", inspect)
    monkeypatch.setattr(Hv, "WIN", False)
    monkeypatch.setattr(Hv, "RETRY_WAIT", 0)
    monkeypatch.setattr(Hv, "_item_hud", lambda *a, **k: None)
    monkeypatch.setattr(Hv, "threading", SimpleNamespace(Thread=_NoThread))
    monkeypatch.setattr(Hv.bus, "publish", lambda *a, **k: None)
    monkeypatch.setattr(Hv.bus, "runtime_log", lambda msg, *a, **k: logs.append(msg))
    monkeypatch.setattr(run_records, "record", lambda *a, **k: None)
    monkeypatch.setattr(about, "data_names_ready", lambda: True)
    links = Hv.HoverLinks(
        item_card=lambda *a, **k: {},
        loot=lambda *a, **k: None,
        market=lambda: None,
        market_rows=lambda *a, **k: ([], None),
        hud_market=lambda results: "",
        wikelo_rewards=lambda name, zh: [],
        has_blueprint=lambda *names: False,
    )
    return imgs, calls, logs, links


def test_miss_twice_grabs_again_and_second_pass_may_go_full(monkeypatch):
    """第一遍认不出 → 再截一张再认；两遍都没有就是未识别（级联已无整屏 OCR）。"""
    imgs, calls, logs, links = _setup(monkeypatch, [None, None])
    assert Hv.hover_once(links) == {"miss": True}
    assert calls == [(0, False), (1, True)] and len(imgs) == 2
    assert any("第一遍没找到说明框" in m and "再截一次" in m for m in logs)


def test_sure_first_pass_does_not_grab_again(monkeypatch):
    """第一遍就在汉化包里对上了：不等、不再截。"""
    imgs, calls, logs, links = _setup(monkeypatch, [_res("极地", "Polar", True)])
    assert Hv.hover_once(links)["ok"]
    assert calls == [(0, False)] and len(imgs) == 1
    assert not any("再截一次" in m for m in logs)
    assert Hv._last_hover["lines"][0].startswith("极地")


def test_unsure_first_pass_uses_second_pass(monkeypatch):
    """第一遍没把握 → 再截一次，用第二遍的。"""
    imgs, calls, logs, links = _setup(
        monkeypatch, [_res("罗伯茨太空工业", "", False), _res("黎明女神", "Eos", True)]
    )
    assert Hv.hover_once(links)["ok"]
    assert calls == [(0, False), (1, True)]
    assert any("认成「罗伯茨太空工业」" in m and "再截一次" in m for m in logs)
    assert Hv._last_hover["lines"][0].startswith("黎明女神")


def test_second_pass_empty_keeps_first(monkeypatch):
    """第二遍什么都没认出来：还用第一遍没把握的那个，不报未识别。"""
    imgs, calls, logs, links = _setup(
        monkeypatch, [_res("某样东西", "Something Odd", False), None]
    )
    assert Hv.hover_once(links)["ok"]
    assert Hv._last_hover["lines"][0].startswith("某样东西")


def test_given_image_reads_once_as_before(monkeypatch):
    """窗口、测试传进来的图：只认一遍、照旧可以整屏，不截屏。"""
    imgs, calls, logs, links = _setup(monkeypatch, [None])
    given = SimpleNamespace(width=1920, height=1080)
    assert Hv.hover_once(links, given) == {"miss": True}
    assert calls == [("给的", True)] and imgs == []
    assert not any("再截一次" in m for m in logs)


def test_read_tooltip_first_pass_skips_full_screen(monkeypatch):
    """_read_tooltip：只认 title/body 裁切，从不认整张图（whole_screen 参数不再触发整屏 OCR）。"""
    from astral_toolkit import ocr

    seen = []

    class _Img:
        size = (2560, 1440)

        def crop(self, box):
            return SimpleNamespace(box=box)

    def recognize(img, **kw):
        seen.append(getattr(img, "box", "整张"))
        return [OcrToken("关闭物品栏", 95, (2000, 1300, 100, 20))]

    monkeypatch.setattr(ocr, "recognize", recognize)
    monkeypatch.setattr(I, "_debug_on", lambda: False)
    tokens, name, where = I._read_tooltip(_Img(), (2434, 961), whole_screen=False)
    assert name is None and "整张" not in seen and seen
    seen.clear()
    I._read_tooltip(_Img(), (2434, 961), whole_screen=True)
    assert "整张" not in seen and seen


def test_inspect_item_passes_first_pass_down(monkeypatch):
    """inspect_item(whole_screen=False) 把「不整屏」传给 _read_tooltip；默认照旧只传两个参数（老测试的替身只收两个）。"""
    got = []

    def read(img, cursor, **kw):
        got.append(kw)
        return [], None, "30-50%@title"

    class _Img:
        size = (2560, 1440)

    monkeypatch.setattr(I, "_read_tooltip", read)
    assert I.inspect_item(_Img(), (100, 100), whole_screen=False) is None
    assert I.inspect_item(_Img(), (100, 100)) is None
    assert got == [{"whole_screen": False}, {}]
