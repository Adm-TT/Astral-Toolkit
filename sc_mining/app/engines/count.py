"""库存盘点读屏（_Count）

2026-10-28 从 app/services.py 原样剪出来（逻辑没改）。2026-10-30 重构阶段 4 删了 services.py，
用到的函数 / 变量直接到它们所在的模块取，运行时才取，避免互相 import：
_T("mining").xxx = tasks/mining.py，_H().xxx = app/hud_state.py，_E().live / .nav / .pos / .cam_filter = 引擎实例。
用到：WIN, _count_review, _game_front, _hud, _note_hud, _place_of, _read_item, qty_text, settings_key, trade
"""
import importlib
import sys
import threading
import time

from .. import bus

WIN = sys.platform == "win32"


def _T(name):
    """sc_mining.tasks 里的模块（运行时才取，避免互相 import）"""
    return importlib.import_module(f"sc_mining.tasks.{name}")


def _H():
    from .. import hud_state
    return hud_state


class _Count:
    IDLE_CLOSE = 60         # 这么多秒没认到物品：自动结束（切出游戏的那段不算）
    STILL = 0.35            # 鼠标停这么久才认（说明框要一点时间才出来）

    def __init__(self):
        self.ev = None
        self.thread = None
        self.place = ""
        self.items = {}         # (en, 品质, 单位) → {zh, en, quality, unit, qty, cells}
        self.cells = set()
        self.review = None      # 结束后的对账结果，等窗口里确认

    def running(self):
        return bool(self.thread and self.thread.is_alive())

    def start(self):
        if not WIN or self.running():
            return {"running": self.running()}
        from ...crafting import stockplaces as SP
        here = SP.current_place()
        place = here["label"] if here else _T("stock")._place_of(_T("trade").trade().db.get("last_location", "") or "")[0]
        if not place:
            _H()._note_hud("盘点", "盘点：当前位置未知｜先在游戏中打开一次库存")
            return {"error": "当前位置未知：先在游戏中打开一次库存"}
        self.place, self.items, self.cells, self.review = place, {}, set(), None
        self.ev = ev = threading.Event()
        self.thread = threading.Thread(target=self._run, args=(ev,), daemon=True, name="count")
        self.thread.start()
        self._show()
        bus.publish("count", {"running": True, "place": place})
        return {"running": True, "place": place}

    def stop(self):
        """手动结束（F6 / 窗口里的按钮）：识别线程自己收尾"""
        if self.ev:
            self.ev.set()
        return {"running": False}

    def _key(self, r):               # 制造出来的同名东西，各槽品质不一样就分开记
        return ((r["en"] or r["zh"]), r["quality"], r["unit"], tuple(x["q"] for x in r.get("craft") or []))

    def _show(self):
        lines = [f"盘点｜{self.place}"]
        for v in list(self.items.values())[-8:]:
            q = "" if v["quality"] is None else f" Q{v['quality']}"
            lines.append(f"{v['zh'] or v['en']}{q} ×{v['cells']}  {_T("hover").qty_text(v['qty'], v['unit'])}")
        _H()._hud().set("盘点", "\n".join(lines))

    def _run(self, ev):
        import ctypes
        from ctypes import wintypes
        from ...mining.screen import grab
        from ...trade import console as C
        last_hit = time.time()
        prev_pos, still_since, done_pos, tries = None, time.time(), None, 0
        logged = None
        pt = wintypes.POINT()
        try:
            while not ev.is_set():
                if _T("mining")._game_front() is False:              # 切出游戏：不认，也不算闲着
                    last_hit += 0.25
                    ev.wait(0.25)
                    continue
                now = time.time()
                if now - last_hit > self.IDLE_CLOSE:
                    break
                ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                pos = (pt.x, pt.y)
                if pos != prev_pos:
                    prev_pos, still_since = pos, now
                    if done_pos and abs(pos[0] - done_pos[0]) + abs(pos[1] - done_pos[1]) > 8:
                        done_pos, tries = None, 0
                    ev.wait(0.1)
                    continue
                if now - still_since < self.STILL or done_pos == pos:
                    ev.wait(0.1)
                    continue
                img = grab()
                cursor = C._cursor_on_image(img)
                try:
                    r = _T("count")._read_item(img, cursor)
                except Exception as e:
                    r = None
                    if repr(e) != logged:               # 同一种错只记一次（以前吞掉，认不出时日志里看不到原因）
                        logged = repr(e)
                        bus.runtime_log(f"盘点识别出错：{e!r}", tag="COUNT", level="ERROR")
                tries += 1
                if r is None or (r["unit"] == "SCU" and not r["qty"]) or not r["sure"]:
                    if tries >= 3:                      # 停在这里认了 3 次都没认出：不再认，等鼠标挪开
                        done_pos = pos
                    ev.wait(0.3)
                    continue
                done_pos, tries = pos, 0
                last_hit = time.time()
                W, H = img.size
                cell = (self._key(r), r["qty"], round(cursor[0] / (W * 0.065)), round(cursor[1] / (H * 0.11)))
                if cell in self.cells:                  # 同一格按过了
                    continue
                self.cells.add(cell)
                v = self.items.setdefault(self._key(r), {"zh": r["zh"], "en": r["en"], "quality": r["quality"],
                                                         "unit": r["unit"], "qty": 0, "cells": 0, "craft": r.get("craft")})
                v["qty"] = round(v["qty"] + r["qty"], 6)
                v["cells"] += 1
                if not ev.is_set():
                    self._show()
        finally:
            self._finish()

    def _finish(self):
        _H()._hud().clear("盘点")
        try:
            self.review = _T("count")._count_review(self.place, self.items) if self.items else None
        except Exception as e:
            self.review = None
            bus.publish("log", {"task": "count", "line": f"盘点对账失败：{e}"})
        k = _T("navigation").settings_key("count_key", "F6")
        if self.review:
            n = len([r for r in self.review["rows"] if r["delta"]]) + len(self.review["missing"])
            _H()._note_hud("盘点", f"盘点结束｜{n} 处不一致，需在 AT 中确认" if n else "盘点结束｜数量一致", 8)
        else:
            _H()._note_hud("盘点", f"盘点结束｜未识别到物品｜按 {k} 重新开始", 8)
        bus.publish("count", {"running": False, "review": self.review})
