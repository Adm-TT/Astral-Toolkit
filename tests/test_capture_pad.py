"""无边框 + 游戏分辨率比显示器小：游戏窗口占满屏幕、画面只画在一角、其余是黑边（老大 2026-11-13 实测：2K 屏开 1080p
无边框，AT 按整屏找面板，采矿扫描一次都读不出）。截图范围要只算有画面的那一块"""

from PIL import Image

from astral_toolkit.infrastructure.platform import capture as C


def _screen(size=(2560, 1440), frame=(0, 0, 1920, 1080), color=(90, 120, 60)):
    """一张屏幕：黑底，frame（左, 上, 宽, 高）那块是画面；frame=None 整屏都是画面"""
    img = Image.new("RGB", size, color if frame is None else (0, 0, 0))
    if frame:
        left, top, w, h = frame
        img.paste(color, (left, top, left + w, top + h))
    return img


def _box(img):
    """一张图里有画面的那一块（_padded 里就是这两步）"""
    lit = C._lit_box(img)
    return C._frame_of(lit, img.size) if lit else None


def test_content_box_finds_frame_in_black_padding():
    assert _box(_screen()) == (0, 0, 1920, 1080)  # 画面在左上角
    assert _box(_screen(frame=(320, 180, 1920, 1080))) == (
        320,
        180,
        1920,
        1080,
    )  # 画面居中也认
    assert _box(_screen(size=(3840, 2160), frame=(0, 0, 2560, 1440))) == (
        0,
        0,
        2560,
        1440,
    )


def test_content_box_none_when_no_padding_or_odd_size():
    assert _box(_screen(frame=None)) is None  # 整屏都是画面
    assert _box(_screen(frame=(0, 0, 0, 0))) is None  # 全黑（加载中）
    # 暗场景里碰巧只有中间一块亮：不是常见的游戏画面大小，不当成黑边
    assert _box(_screen(frame=(300, 200, 1500, 700))) is None
    assert _box(_screen(frame=(0, 0, 1900, 1068))) is None


def test_content_box_more_shapes():
    # 上下黑边（带鱼屏画面放在普通屏上）、RGBA 图也认
    wide = _screen(frame=(0, 180, 2560, 1080))
    assert _box(wide) == (0, 180, 2560, 1080)
    assert _box(wide.convert("RGBA")) == (0, 180, 2560, 1080)
    assert not C._lit(Image.new("RGBA", (4, 4), (0, 0, 0, 255)))  # 透明度不算亮


def _use(monkeypatch, state):
    """_padded 用的截图换成从 state["img"] 这张假屏幕上裁，不看真屏幕；每次都重新看黑边"""
    grabs = []

    def shot(area):
        grabs.append((area["width"], area["height"]))
        left, top = area["left"], area["top"]
        return state["img"].crop(
            (left, top, left + area["width"], top + area["height"])
        )

    monkeypatch.setattr(C, "_shot_masked", shot)
    monkeypatch.setattr(C, "_frame_hint", lambda: state.get("hint"))
    monkeypatch.setattr(C, "_pad", {"t": -1e9, "win": None, "box": None, "seen": None})
    monkeypatch.setattr(C, "_PAD_EVERY", 0.0)
    return grabs


AREA = {"left": 0, "top": 0, "width": 2560, "height": 1440}
BOX = (0, 0, 1920, 1080)


def test_padded_full_frame_only_grabs_two_thin_lines(monkeypatch):
    """平常（窗口里全是画面）：只截右边、下边两条细线，不截整块"""
    grabs = _use(monkeypatch, {"img": _screen(frame=None)})
    assert C._padded(AREA) is None and C._padded(AREA) is None
    assert grabs == [(2, 1440), (2560, 2)] * 2


def test_padded_needs_two_looks_then_keeps_box_through_dark_frames(monkeypatch):
    state = {"img": _screen()}
    _use(monkeypatch, state)
    assert C._padded(AREA) is None  # 第一次看到：先不信
    assert C._padded(AREA) == BOX  # 连着两次一样：采用
    # 画面一时很暗（右边一截全黑），框不准：沿用，不退回整屏
    state["img"] = _screen(frame=(0, 0, 1500, 1080))
    assert C._padded(AREA) == BOX
    state["img"] = _screen(frame=(0, 0, 0, 0))  # 全黑（加载中）也一样
    assert C._padded(AREA) == BOX
    # 玩家把游戏改回满屏：边上亮了，马上作废
    state["img"] = _screen(frame=None)
    assert C._padded(AREA) is None
    # 窗口大小变了：旧的框不带过去
    state["img"] = _screen()
    assert C._padded(AREA) is None and C._padded(AREA) == BOX
    state["img"] = _screen(size=(3840, 2160), frame=(0, 0, 0, 0))
    assert C._padded({"left": 0, "top": 0, "width": 3840, "height": 2160}) is None


def test_padded_drops_box_when_frame_outgrows_it(monkeypatch):
    """玩家把游戏从 1080p 改成更大的画面，边上又正好是黑的：旧框外面亮了就作废，不能一直裁着旧的那块"""
    state = {"img": _screen()}
    _use(monkeypatch, state)
    C._padded(AREA)
    assert C._padded(AREA) == BOX
    dark = _screen(frame=(0, 0, 2200, 1300))  # 新画面边上是黑的、亮的那块不是常见大小
    state["img"] = dark
    assert C._padded(AREA) is None
    state["img"] = _screen()  # 换回 1080p：重新连看两次
    assert C._padded(AREA) is None and C._padded(AREA) == BOX
    state["img"] = _screen(
        frame=(0, 0, 1600, 900)
    )  # 改小：新框连看两次才换，中间沿用旧框
    assert C._padded(AREA) == BOX and C._padded(AREA) == (0, 0, 1600, 900)


def test_padded_one_dark_scene_look_is_not_enough(monkeypatch):
    """满屏的暗场景里，亮的那块碰巧是个常见大小：只看到一次不采用"""
    state = {"img": _screen(frame=(320, 180, 1920, 1080))}
    _use(monkeypatch, state)
    assert C._padded(AREA) is None
    state["img"] = _screen(frame=(300, 200, 1500, 700))
    assert C._padded(AREA) is None
    state["img"] = _screen(frame=(320, 180, 1920, 1080))
    assert C._padded(AREA) is None  # 中间断过，不算连着两次


def test_padded_bottom_only_padding(monkeypatch):
    """只有下面是黑边（2560×1080 的画面放在 2560×1440 的屏上）：右边那条是亮的，也要认出来"""
    state = {"img": _screen(frame=(0, 0, 2560, 1080))}
    _use(monkeypatch, state)
    C._padded(AREA)
    assert C._padded(AREA) == (0, 0, 2560, 1080)


def test_padded_trusts_game_setting_in_dark_scene(monkeypatch):
    """游戏设置里写着 1920×1080、窗口是 2560×1440：夜里画面边上全黑、只有中间一点亮，也马上认出是左上角那一块
    （老大就是在暗的星球表面挖矿）；设置和实际对不上（亮到外面去了）就不信它"""
    state = {"img": _screen(frame=(600, 400, 300, 200)), "hint": (1920, 1080)}
    _use(monkeypatch, state)
    assert C._padded(AREA) == BOX  # 第一次看就采用
    state["img"] = _screen(frame=(0, 0, 0, 0))
    assert C._padded(AREA) == BOX  # 全黑：沿用
    state["img"] = _screen(frame=(0, 0, 2300, 1300))  # 实际画面比设置的大：设置是旧的
    assert C._padded(AREA) is None
    state.update(img=_screen(frame=(600, 400, 300, 200)), hint=(2560, 1440))
    assert C._padded(AREA) is None  # 设置和窗口一样大：没有黑边这回事
    state["hint"] = (3840, 2160)  # 设置比窗口还大：不信
    assert C._padded(AREA) is None


def test_frame_hint_reads_game_attributes(monkeypatch, tmp_path):
    from astral_toolkit.core import settings

    live = tmp_path / "LIVE"
    prof = live / "user" / "client" / "0" / "Profiles" / "default"
    prof.mkdir(parents=True)
    monkeypatch.setattr(settings, "load", lambda: {"game_log": str(live / "Game.log")})
    assert C._frame_hint() is None  # 没有设置文件
    (prof / "attributes.xml").write_text(
        '<Attributes Version="1">\n <Attr name="FOV" value="76.5"/>\n <Attr name="Height" value="1080"/>\n'
        ' <Attr name="Width" value="1920"/>\n <Attr name="WindowMode" value="2"/>\n</Attributes>',
        encoding="utf-8",
    )
    assert C._frame_hint() == (1920, 1080)
    (prof / "attributes.xml").write_text(
        '<Attr name="Width" value="1920"/>', encoding="utf-8"
    )
    assert C._frame_hint() is None  # 缺一项
    monkeypatch.setattr(settings, "load", lambda: {})
    assert C._frame_hint() is None  # 没设游戏目录


def test_padded_rechecks_only_every_few_seconds(monkeypatch):
    state = {"img": _screen()}
    grabs = _use(monkeypatch, state)
    C._padded(AREA)
    assert C._padded(AREA) == BOX
    monkeypatch.setattr(C, "_PAD_EVERY", 3.0)
    n = len(grabs)
    state["img"] = _screen(frame=None)
    assert C._padded(AREA) == BOX and len(grabs) == n  # 3 秒内不重看


def _fake_window(monkeypatch, found):
    import sys

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        C, "_sct", lambda: type("S", (), {"monitors": [None, dict(AREA)]})()
    )
    monkeypatch.setattr(C, "_window_area", lambda m: (dict(m), found))
    monkeypatch.setattr(C, "_game_area_cache", {"t": 0.0, "area": None, "found": False})


def test_game_area_uses_content_box(monkeypatch):
    """game_area 给出去的是有画面的那一块：读屏的比例区域、鼠标换算、悬浮窗定位都跟着对"""
    _fake_window(monkeypatch, True)
    _use(monkeypatch, {"img": _screen(frame=(320, 180, 1920, 1080))})
    assert C.game_area() == AREA  # 第一次看到黑边：还按整个窗口
    monkeypatch.setattr(C, "_game_area_cache", {"t": 0.0, "area": None, "found": False})
    assert C.game_area() == {"left": 320, "top": 180, "width": 1920, "height": 1080}


def test_game_area_without_game_window_never_crops(monkeypatch):
    """找不到游戏窗口时截的是整个桌面：不在桌面上找黑边"""
    _fake_window(monkeypatch, False)
    grabs = _use(monkeypatch, {"img": _screen()})
    for _ in range(3):
        monkeypatch.setattr(
            C, "_game_area_cache", {"t": 0.0, "area": None, "found": False}
        )
        assert C.game_area() == AREA
    assert grabs == []
