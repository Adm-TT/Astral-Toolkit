"""交易：主菜单第 9 项（不再开独立窗口）

- 输入物品名（中文/英文）查 UEX + SCM 玩家市场价
- 库存：查看、手动入库、截图识别入库、撤销
- 截图入库：在这个界面时，游戏里按 F8（可在 settings.json 的 trade_capture_key 改），
  屏幕变暗后拖出物品名和数量那一块，松开就识别；结果在这里逐行核对后才入库
- 查到的价格会显示在悬浮窗「交易」分区
"""
import hashlib
import io
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import re as _re

from .catalog import Catalog
from .history import History
from .inspector import (
    _ANCHOR,
    _VOLUME,
    _is_anchor,
    _SENTENCE,
    _LETTERS,
    _STAT,
    _NOT_ITEM,
    _ink,
    _bright_only,
    tooltip_name,
    plausible_name,
    tooltip_pick,
    _anchor_name,
    _cursor_on_image,
    _hover_log,
    inspect_item,
)
from .inventory import Inventory
from .market_service import MarketService
from .models import ImportRow, Item, StockKey, StockLine
from .names import has_chinese, to_english, _fold_en
from .parser import parse_inventory
from .providers.scm import ScmProvider
from .providers.uex import UexProvider
from .storage import Database


def _fold(text):
    """比较名字用：忽略大小写、空格、符号；OCR 常把 II 认成 ll，统一成 i。
    names._fold_en 不动（那边查表要分清 l 和 i），只在这里比较 OCR 认出的名字时放宽"""
    return _fold_en(text).replace("l", "i")

VK = {f"F{i}": 0x6F + i for i in range(1, 13)}
SOURCE_ZH = {"uex": "UEX", "scm": "SCM"}
STATE_ZH = {"ok": "", "empty": "暂无报价", "partial": "部分数据", "stale": "旧缓存", "offline": "离线",
            "forbidden": "拒绝访问", "rate_limited": "限流", "schema_error": "格式变化", "cancelled": "已取消"}


def data_directory():
    """和原 SC Trade Companion 同一个数据库位置，原来录入的库存直接能用"""
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share")))
    return base / "SCTradeCompanion"


DB_NAME = "dubhe_inventory.db"


class Trade:
    def __init__(self, directory=None, providers=None):
        d = Path(directory or data_directory())
        d.mkdir(parents=True, exist_ok=True)
        # 1.6.58：天枢自己的库存文件（表结构重新设计）。旧的 inventory.db 不动，第一次启动时只读地导一份过来
        self.db = Database(d / DB_NAME)
        if not self.db.get("v1_imported"):
            try:
                from .storage import import_v1
                n = import_v1(d / "inventory.db", self.db)
                self.db.set("v1_imported", {"at": time.strftime("%F %T"), "rows": n})
            except Exception as e:                        # 导不成功也照常用（从空库开始），下次启动再试
                print(f"旧库存导入没成功：{e}")
        self.catalog = Catalog(self.db)
        self.inventory = Inventory(self.db)
        self.market = MarketService(self.db, providers if providers is not None else [UexProvider(), ScmProvider()])
        self.history = History(self.db)
        # 1.6.37：矿和材料从 0.01 SCU 改成按 uSCU 记，旧记录换算一次（换算前备份数据库，2026-10-23 用户同意）
        try:
            self.inventory.migrate_cscu(backup=d / time.strftime("inventory_换算前备份_%Y%m%d_%H%M%S.db"))
        except Exception as e:                            # 换算失败不影响用：旧的 cSCU 记录照样能读
            print(f"库存单位换算没成功：{e}")
        # 1.6.39：以前手打的位置能对上地点列表的（New Babbage、Area18…）改成列表里的叫法（真要改时先备份，记一笔移库能撤销）
        try:
            from ..crafting.stockplaces import match

            def canon(loc):
                p = match(loc)
                return p["label"] if p else None
            self.inventory.normalize_locations(canon, backup=d / time.strftime("inventory_地点归位前备份_%Y%m%d_%H%M%S.db"))
        except Exception as e:                            # 归位失败不影响用：对不上的位置在库存页「未归类」里
            print(f"库存地点归位没成功：{e}")
        # 1.6.55：物品对上游戏类名 + uuid（交易平台用；第一次填之前先备份数据库）
        try:
            self.catalog.fill_keys()
        except Exception as e:                            # 对不上不影响用
            print(f"物品游戏编号没对上：{e}")

    # ---------------------------------------------------------------- 名字
    def label(self, item_id):
        """「中文名（英文名）」。中文名以汉化包为准：记下的中文名可能是 F8 认错的（冷冻舱（刻度）），
        先按汉化包纠正；对不上的才原样用（2026-10-23 用户反馈库存里显示认错的名字）"""
        from .names import canonical, zh_for
        item = self.catalog.get(item_id)
        if not item:
            return item_id
        with self.db.connection() as c:
            zh = [r[0] for r in c.execute("SELECT alias FROM aliases WHERE item_id=?", (item_id,)) if has_chinese(r[0])]
        name = None
        for a in zh:
            hit = canonical(a, "")
            if hit and _similar(_fold(hit[1]), _fold(item.name)):
                name = hit[0]
                break
        name = name or zh_for(item.name) or (zh[0] if zh else None)
        return f"{name}（{item.name}）" if name else item.name

    # ---------------------------------------------------------------- 查价
    def lookup(self, query):
        return self.market.lookup(query)

    def prices(self, item, quality_group="q0", operation="sell", now=None):
        now = now or datetime.now(timezone.utc)
        return self.market.refresh(item, quality_group, operation, now)

    def price_lines(self, item, results, now=None):
        now = now or datetime.now(timezone.utc)
        lines = []
        for r in results:
            src = SOURCE_ZH.get(r.source, r.source)
            if not r.stats:
                lines.append(f"  {src}：{STATE_ZH.get(r.state, r.state) or '暂无报价'}" + (f"（{r.message}）" if r.message and r.state != "empty" else ""))
                continue
            for s in r.stats:
                k = s.key
                parts = [f"均价 {_money(s.mean)}", f"最低 {_money(s.minimum)}", f"{s.count} 条挂牌"]
                if s.week_mean is not None:
                    parts.append(f"7 天均价 {_money(s.week_mean)}")
                local = self.history.window(k, now)
                if local["mean"] is not None and local["days"] >= 2:
                    parts.append(f"本机 7 天记录 {_money(local['mean'])}（{local['days']} 天）")
                tag = STATE_ZH.get(r.state, "")
                lines.append(f"  {src}｜{k.quality_group.upper()}｜{k.unit}｜{k.currency}：" + "，".join(parts)
                             + (f"｜{tag}" if tag else ""))
        return lines

    # ---------------------------------------------------------------- 库存
    def stock_lines(self):
        rows = self.inventory.list_stock()
        if not rows:
            return ["（库存是空的）"]
        from .pricing import value_stock
        cached = self.market.cached_stats()
        out = []
        for line in rows:
            k = line.key
            q = k.quality.replace("exact:", "品质 ") if k.quality.startswith("exact:") else (
                "品质未知" if k.quality == "unknown" else k.quality.upper())
            out.append(f"  {self.label(k.item_id)}｜{q}｜{k.location}｜{line.quantity} {k.unit}")
        for src in ("uex", "scm"):
            versions = {(s.key.version, s.key.currency) for s in cached if s.key.source == src}
            for version, currency in versions:
                v = value_stock(rows, cached, src, version, currency)
                if v["priced_rows"]:
                    out.append(f"参考估值（{SOURCE_ZH[src]} 最低卖价，{currency}）：{_money(v['total'])}"
                               f"｜{v['priced_rows']} 行有报价，{v['unpriced_rows']} 行没有")
        return out


def price_brief(s):
    """悬浮窗里一条报价：有最低价用最低价；没有（UEX 只在样本覆盖全部挂牌时才给最低价）就用当前均价，
    再没有用近 7 天均价；都没有返回 None。前面标明是哪种价，免得把均价当成最低价"""
    if s.minimum is not None:
        return f"最低 {_money(s.minimum)}"
    if s.mean is not None:
        return f"均价 {_money(s.mean)}"
    if s.week_mean is not None:
        return f"7天均价 {_money(s.week_mean)}"
    return None


def hud_prices(results, limit=2):
    """悬浮窗「交易」那一行：每个来源一条，例如「UEX 均价 12,000；SCM 最低 9,500」"""
    parts = []
    for r in results:
        for st in r.stats:
            b = price_brief(st)
            if b:
                parts.append(f"{SOURCE_ZH.get(st.key.source, st.key.source)} {b}")
                break
        else:
            if r.stats:
                parts.append(f"{SOURCE_ZH.get(r.source, r.source)} 有挂牌没标价")
    return "；".join(parts[:limit]) or "暂无报价（UEX、SCM 都没人挂牌）"


def hud_market(results):
    """悬浮窗「市场」那一行：最低 / 最高 / 均价，没有的不写；所有来源都没数据返回 ""。
    最低价优先用来源给的；UEX 样本不全时不给最低价，就用能看到的挂牌里最低的（标「已知最低」）"""
    parts = []
    for r in results:
        src = SOURCE_ZH.get(r.source, r.source)
        for st in r.stats:
            prices = [q.price for q in (r.quotes or ()) if q.key == st.key]
            bits = []
            if st.minimum is not None:
                bits.append(f"最低 {_money(st.minimum)}")
            elif prices:
                bits.append(f"已知最低 {_money(min(prices))}")
            if prices and (st.minimum is None or max(prices) > st.minimum):
                bits.append(f"最高 {_money(max(prices))}")
            mean = st.mean if st.mean is not None else st.week_mean
            if mean is not None:
                bits.append(f"{'均价' if st.mean is not None else '7天均价'} {_money(mean)}")
            if bits:
                parts.append(f"{src} " + "｜".join(bits))
                break
    return "\n".join(parts)


def _money(v):
    if v is None:
        return "—"
    try:
        return f"{float(v):,.0f}"
    except (TypeError, ValueError):
        return str(v)


def _quality(text):
    """'650' → exact:650；'q6' → q6；空 → None"""
    t = (text or "").strip().lower()
    if not t:
        return None
    if t in ("未知", "unknown", "?"):
        return "unknown"
    if t.startswith("q") and t[1:].isdigit() and 0 <= int(t[1:]) <= 7:
        return t
    if t.isdigit() and 0 <= int(t) <= 1000:
        return "exact:" + str(int(t))
    raise ValueError("品质填 0–1000 的数值，或 q0–q7，或「未知」")


def _group(quality):
    from .providers.http import quality_group
    if quality and quality.startswith("exact:"):
        return quality_group(quality[6:])
    return quality if quality and quality.startswith("q") else "q0"


# ---------------------------------------------------------------- 截图框选

def select_region(image):
    """全屏显示截图，拖出一个框，返回裁剪后的图（Esc / 右键取消返回 None）"""
    import tkinter as tk
    from PIL import ImageTk, ImageEnhance
    try:
        from ..app.overlay import hud
        h = hud()
        root = tk.Toplevel(h.root) if h.ok else tk.Tk()
    except Exception:
        root = tk.Tk()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    sx, sy = image.width / sw, image.height / sh
    shown = ImageEnhance.Brightness(image.resize((sw, sh))).enhance(0.55)
    photo = ImageTk.PhotoImage(shown)
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.geometry(f"{sw}x{sh}+0+0")
    cv = tk.Canvas(root, width=sw, height=sh, highlightthickness=0, cursor="crosshair")
    cv.pack()
    cv.create_image(0, 0, image=photo, anchor="nw")
    cv.create_text(30, 30, anchor="nw", fill="white", font=("Microsoft YaHei", 16),
                   text="拖出物品名和数量所在的区域，松开就识别｜Esc 或右键取消")
    state = {"start": None, "rect": None, "box": None, "done": False}

    def press(e):
        state["start"] = (e.x, e.y)
        if state["rect"]:
            cv.delete(state["rect"])
        state["rect"] = cv.create_rectangle(e.x, e.y, e.x, e.y, outline="#43d9c1", width=2)

    def move(e):
        if state["start"]:
            x0, y0 = state["start"]
            cv.coords(state["rect"], x0, y0, e.x, e.y)

    def release(e):
        if not state["start"]:
            return
        x0, y0 = state["start"]
        x1, y1 = e.x, e.y
        if abs(x1 - x0) > 8 and abs(y1 - y0) > 8:
            state["box"] = (int(min(x0, x1) * sx), int(min(y0, y1) * sy), int(max(x0, x1) * sx), int(max(y0, y1) * sy))
        state["done"] = True

    def cancel(_=None):
        state["done"] = True

    cv.bind("<ButtonPress-1>", press)
    cv.bind("<B1-Motion>", move)
    cv.bind("<ButtonRelease-1>", release)
    cv.bind("<Button-3>", cancel)
    root.bind("<Escape>", cancel)
    root.focus_force()
    while not state["done"]:
        root.update()
        time.sleep(0.01)
    root.destroy()
    return image.crop(state["box"]) if state["box"] else None


# ---------------------------------------------------------------- 菜单

HELP = """交易（UEX + SCM 玩家市场 · 库存）
  游戏库存界面里鼠标停在物品上、说明框出来后按 {key} = 认出这个物品、查价，可顺手入库
  直接输入物品名 = 查玩家市场价（中文或英文，例：科力晶 / Carinite / FR-86）
  哪买 物品名 = 游戏里哪些商店卖、多少钱｜维科洛 关键词 = 维科洛兑换要什么材料、去哪弄
  库存 = 看库存和参考估值｜入库 = 手动录入｜截图 = 手动框选一块文字识别入库
  记录 = 最近变动（可撤销）｜q = 返回主菜单"""


def ask(trade=None):
    from ..core import settings
    cfg = settings.load()
    key = cfg.get("trade_capture_key") or "F8"
    t = trade or Trade()
    print(HELP.format(key=key))
    print()
    try:
        from ..app.overlay import hud
        ov = hud()
    except Exception:
        ov = None
    if ov and ov.ok:
        ov.set("交易", f"鼠标停在物品上按 {key}：查价 / 入库\n或在助手窗口输入物品名查价")
    if sys.platform == "win32":
        from ..system.showloc import is_admin
        if not is_admin():
            print(f"⚠ 助手不是管理员身份：游戏是管理员权限运行时，游戏里按 {key} 助手收不到。请重开助手并在确认框点「是」。\n")
    editor = LineEditor("交易 > ")
    prev = False
    try:
        while True:
            if sys.platform == "win32":
                import ctypes
                down = bool(ctypes.windll.user32.GetAsyncKeyState(VK.get(key.upper(), 0x77)) & 0x8000)
                if down and not prev:
                    editor.interrupt("（识别鼠标下的物品）")
                    try:
                        hover_flow(t, ov)
                    except KeyboardInterrupt:
                        print("\n（已取消）")
                    except Exception as e:
                        print(f"截图入库出错：{e}")
                    editor.redraw()
                prev = down
            line = editor.poll()
            if line is not None:
                cmd = line.strip()
                if cmd.lower() in ("q", "quit", "返回"):
                    return
                try:
                    handle(t, cmd, ov)
                except KeyboardInterrupt:
                    print("\n（已取消）")
                except Exception as e:
                    print(f"出错了：{e}")
                editor.redraw()
            if ov:
                ov.sleep(0.03)
            else:
                time.sleep(0.03)
    finally:
        if ov:
            ov.clear("交易")


class LineEditor:
    """不阻塞地读一行控制台输入（Windows 用 msvcrt），这样等输入的同时还能响应游戏里的截图热键"""

    def __init__(self, prompt):
        self.prompt, self.buf = prompt, []
        self.win = sys.platform == "win32"
        self.redraw()

    def redraw(self):
        print(self.prompt + "".join(self.buf), end="", flush=True)

    def interrupt(self, msg):
        print("\n" + msg)
        self.buf = []

    def poll(self):
        if not self.win:
            try:
                return input()
            except EOFError:
                return "q"
        import msvcrt
        while msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                print()
                line, self.buf = "".join(self.buf), []
                return line
            if ch == "\x03":
                raise KeyboardInterrupt
            if ch == "\x08":
                if self.buf:
                    gone = self.buf.pop()
                    w = 2 if ord(gone) > 0x2E7F else 1
                    print("\b" * w + " " * w + "\b" * w, end="", flush=True)
                continue
            if ch in ("\x00", "\xe0"):          # 方向键等功能键，丢掉
                msvcrt.getwch()
                continue
            if ch.isprintable():
                self.buf.append(ch)
                print(ch, end="", flush=True)
        return None


_input = input


def handle(t, cmd, ov=None):
    if not cmd:
        return
    if cmd in ("库存", "kc"):
        print("\n".join(t.stock_lines()))
    elif cmd in ("入库", "rk"):
        manual_import(t)
    elif cmd in ("截图", "jt"):
        capture_flow(t, ov)
    elif cmd in ("记录", "jl"):
        history_flow(t)
    elif _re.match(r"^(哪买|在哪买|哪里买|nm)\s*", cmd):
        finder_flow(_re.sub(r"^(哪买|在哪买|哪里买|nm)\s*", "", cmd))
    elif _re.match(r"^(维科洛|维克洛|wikelo|wk)\s*", cmd, _re.I):
        wikelo_flow(_re.sub(r"^(维科洛|维克洛|wikelo|wk)\s*", "", cmd, flags=_re.I))
    else:
        price_flow(t, cmd, ov)


# ---------------------------------------------------------------- 哪里买 / 维科洛

def material_source(name_en):
    """维科洛材料去哪弄：商店能买就给最便宜的店；是矿就给最好的矿点"""
    from ..crafting import shops
    from ..crafting.wikelo import source_note
    note = source_note(name_en)
    if note:
        return note
    tip = shops.where_by_name(name_en)
    if tip:
        return tip
    try:
        from ..mining.locations import where as mine_where, zh_name
        base = _re.sub(r"\s*\(.*?\)", "", name_en).strip()
        rows = mine_where(base)
        if rows:
            pct, loc = rows[0]
            return f"挖矿：{zh_name(loc)} {pct:.0f}%" + ("（要精炼成纯净的）" if "Pure" in name_en else "")
    except Exception:
        pass
    return loot_source(name_en)


def loot_source(name_en, name_zh=""):
    """开箱掉落一句话（scl.miao.network 的掉落表）：概率最高的箱子在哪些地方；没有掉落返回空"""
    try:
        from ..crafting.loot import info
        d = info(name_en, name_zh, top=2, online=False)   # 本机没有明细就算没有，不在页面里逐个材料联网等（细查 2026-10-28）
    except Exception:
        return ""
    if not d or not d.get("groups"):
        return ""
    g = d["groups"][0]
    regions = "、".join(g["regions"][:3]) + ("等" if len(g["regions"]) > 3 or d.get("more") else "")
    if d.get("mine"):                                  # 副本专属矿：不开箱，只能开采
        return d["note"].split("：")[0] + f"，只能开采：{regions}" + (f"（{g['box']}）" if g["box"] else "")
    if g.get("placed"):                                # 不在箱子里，直接刷在场景里（争夺区奖励室架子上的舰船组件…）
        return f"场景里刷出：{regions}（最高约 {g['p']:.0%}）"
    box = g["box"].split(" · ")[0]
    box = "" if _re.fullmatch(r"\d+.*", box or "") else box
    return f"开箱：{regions}" + (f"（{box} 箱" if box else "（") + f"，单箱最高约 {g['p']:.0%}）"


def finder_flow(query):
    from ..crafting import shops
    from ..crafting import acquire
    from ..crafting import loot
    query = query.strip() or _input("找哪件东西（中文或英文）> ").strip()
    if not query:
        return
    hits = shops.find(query)
    if not hits:
        # 商店数据里没有（多半是限定版）：用掉落数据的物品表找名字
        lh = loot.find(*((("", query) if has_chinese(query) else (query, ""))))
        if not lh:
            print("商店和掉落数据里都没有叫这个的物品（矿物请用主菜单 2 找矿点）")
            return
        u, en, zh, _ = lh[0]
        print(f"【{zh or en}】{en}")
        print(acquire.text(en, zh))
        return
    if len(hits) > 1:
        for i, (_, name, cat) in enumerate(hits, 1):
            print(f"  {i:>2}. {name}｜{cat}")
        sel = _input("选序号（回车 = 第 1 个）> ").strip()
        hit = hits[int(sel) - 1] if sel.isdigit() and 1 <= int(sel) <= len(hits) else hits[0]
    else:
        hit = hits[0]
    print(f"【{hit[1]}】{hit[2]}")
    print(acquire.text(hit[1], "", hit[0]))


def wikelo_flow(query):
    from ..crafting import wikelo
    rows = wikelo.search(query)
    if not rows:
        print("没有相关的维科洛兑换（可以搜奖励名、兑换名或材料名，例：维科洛 阿波罗 / 维科洛 科力晶）")
        return
    if len(rows) > 1:
        for i, c in enumerate(rows[:30], 1):
            print(f"  {i:>2}. {c['t']}｜{c['type']}｜换：{c['rz'] or '、'.join(c['rewards'][:2])}")
        if len(rows) > 30:
            print(f"  …共 {len(rows)} 个，加个词缩小范围")
        sel = _input("看哪个（序号，回车返回）> ").strip()
        if not (sel.isdigit() and 1 <= int(sel) <= min(30, len(rows))):
            return
        rows = [rows[int(sel) - 1]]
    print(wikelo.describe(rows[0], material_source))


def extra_info(zh, en, item=None):
    """悬停识别后附加：怎么弄到（买/同款/掉落）、维科洛兑换用途"""
    from ..crafting import acquire
    return acquire.text(item.name if item else en, zh)


def pick_item(t, query, allow_new=False):
    items, err = t.lookup(query)
    if err:
        print(f"（{err}）")
    if not items:
        print("没找到这个物品" + ("（UEX 只认英文名，对照表里也没有这个中文名）" if has_chinese(query) else ""))
        return None
    items = items[:15]
    for i, it in enumerate(items, 1):
        print(f"  {i:>2}. {t.label(it.id)}　[{it.id.split(':')[0].upper() if ':' in it.id else 'UEX'}]")
    sel = _input("选序号（回车取消）> ").strip()
    if sel.isdigit() and 1 <= int(sel) <= len(items):
        return items[int(sel) - 1]
    return None


def price_flow(t, query, ov=None):
    item = pick_item(t, query)
    if not item:
        return
    try:
        q = _quality(_input("品质（0–1000 或 q0–q7，回车 = q0）> ")) or "q0"
    except ValueError as e:
        print(e)
        return
    op = "buy" if _input("回车 = 出售挂牌价，b = 求购价 > ").strip().lower() == "b" else "sell"
    print(f"查询中（{'求购' if op == 'buy' else '出售'}，{_group(q).upper()}）…")
    results = t.prices(item, _group(q), op)
    lines = t.price_lines(item, results)
    print(f"【{t.label(item.id)}】")
    print("\n".join(lines))
    print("  （玩家挂牌参考价，不是成交价；同一来源结果缓存 1 小时）")
    if ov and ov.ok:
        text = hud_prices(results)
        ov.set("交易", f"{item.name} {_group(q).upper()}\n{text}")


def _location(t):
    last = t.db.get("last_location", "")
    loc = _input(f"存放位置（例：Area18 仓库 / 船名{'，回车 = ' + last if last else ''}）> ").strip() or last
    if loc:
        t.db.set("last_location", loc)
    return loc


def _commit(t, lines, mode="add", image_hash=None):
    preview = t.inventory.prepare(lines, mode, image_hash)
    if preview.duplicate:
        if _input("这张截图之前导入过，确定再导入一次？(y/N) > ").strip().lower() != "y":
            print("已取消")
            return
    print("入库预览：")
    before = {b.key: b.quantity for b in preview.before}
    for line in preview.lines:
        b = before.get(line.key, 0)
        after = b + line.quantity if mode == "add" else line.quantity
        print(f"  {t.label(line.key.item_id)}｜{line.key.quality}｜{line.key.location}：{b} → {after}")
    if _input("确认入库？(Y/n) > ").strip().lower() in ("", "y", "yes", "是"):
        t.inventory.commit(preview, allow_duplicate=preview.duplicate)
        print("✅ 已入库（「记录」里可以撤销）")
    else:
        print("已取消")


def manual_import(t):
    lines = []
    while True:
        name = _input("物品名（回车结束）> ").strip()
        if not name:
            break
        item = pick_item(t, name)
        if not item:
            continue
        qty = _input("数量 > ").strip()
        if not qty.isdigit() or int(qty) <= 0:
            print("数量要是正整数")
            continue
        try:
            q = _quality(_input("品质（0–1000 或 q0–q7，回车 = 未知）> ")) or "unknown"
        except ValueError as e:
            print(e)
            continue
        lines.append((item, int(qty), q))
    if not lines:
        return
    loc = _location(t)
    if not loc:
        print("没填位置，取消")
        return
    _commit(t, [StockLine(StockKey(i.id, q, loc), n) for i, n, q in lines])


# ---------------------------------------------------------------- 悬停识别与说明框查价

def _similar(a, b):
    import difflib
    if not a or not b:
        return False
    return a.startswith(b[:6]) or b.startswith(a[:6]) or difflib.SequenceMatcher(None, a, b).ratio() >= 0.6


def match_tooltip(t, zh, en, online=True):
    """说明框里的名字 → 物品。顺序：中文名查汉化包对照表 → 英文名（容忍 OCR 丢空格、II/ll、截断）。
    先查本机目录（以前查到过的物品、记下的中文名），查到就不联网；本机没有才去 UEX/SCM 搜（每次搜要零点几秒到几秒）。
    返回 (物品或 None, 候选列表)"""
    if zh and hasattr(t.catalog, "by_alias"):
        hit = t.catalog.by_alias(zh)
        if hit:
            return hit, [hit]
    want = []
    if zh:
        want += to_english(zh)[:1] if len(to_english(zh)) == 1 else []
    if en:
        want.append(en)
    best, local = _match_names(t.catalog.search, want)
    if best is not None or not online:
        return best, local
    best, remote = _match_names(lambda q: t.lookup(q)[0], want)
    merged = {i.id: i for i in local + remote}
    return best, list(merged.values())


def _match_names(search, want):
    import difflib
    candidates = {}
    for name in want:
        target = _fold(name)
        # OCR 常把空格丢掉（CQ7Rifle），补回空格再搜
        spaced = _re.sub(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Za-z])(?=")|(?<=")(?=[A-Za-z])', " ", name)
        words = _re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}", spaced)
        for q in dict.fromkeys([name, spaced] + words[:1]):
            items = search(q)
            # 搜不到时有的来源会返回一大串不相干的物品，只留名字像的
            items = [i for i in items if _similar(_fold(i.name), target)]
            for i in items:
                candidates.setdefault(i.id, i)
            if items:
                break
        scored = []
        for i in candidates.values():
            f = _fold(i.name)
            score = 1.0 if f == target else 0.95 if f.startswith(target) and len(target) >= 8 else \
                difflib.SequenceMatcher(None, f, target).ratio()
            scored.append((score, not i.id.startswith("scm:"), i))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        if scored and scored[0][0] >= 0.85:
            return scored[0][2], [x[2] for x in scored]
    return None, list(candidates.values())


def hover_flow(t, ov=None):
    """游戏里把鼠标停在物品上、出现说明框时按热键：认出物品，显示价格，可以顺手入库"""
    from ..mining.screen import grab
    img = grab()
    cx, cy = _cursor_on_image(img) if sys.platform == "win32" else (img.width // 2, img.height // 2)
    res = inspect_item(img, (cx, cy))
    if not res:
        print("没找到物品说明框：把鼠标停在物品上，等说明框出来再按。也可以输入「截图」手动框选")
        _hover_log(img, [], None)
        return
    zh, en = res["zh"], res["en"]
    tokens = res["tokens"]
    _hover_log(img, tokens, (zh, en))
    print(f"认出：{zh} {en}".strip())
    try:
        info = extra_info(zh, en)
        if info:
            print(info)
    except Exception as e:
        print(f"（查商店/维科洛数据出错：{e}）")
    item, items = match_tooltip(t, zh, en)
    if item is None:
        for i, it in enumerate(items[:12], 1):
            print(f"  {i:>2}. {t.label(it.id)}")
        hint = "选序号｜" if items else "UEX、SCM 市场上都没有这个物品（很多装备和配件没人挂牌）｜"
        sel = _input(hint + "n = 按识别到的名字记成本地物品（只入库，不查价）｜回车取消 > ").strip().lower()
        if sel.isdigit() and 1 <= int(sel) <= min(12, len(items)):
            item = items[int(sel) - 1]
        elif sel == "n":
            item = Item("local:" + (en or zh), en or zh)
            t.catalog.upsert([item])
            if zh:
                t.catalog.add_alias(item.id, zh)
            qty = _input("数量（回车 = 1）> ").strip()
            loc = _location(t)
            if loc:
                _commit(t, [StockLine(StockKey(item.id, "unknown", loc), int(qty) if qty.isdigit() and int(qty) > 0 else 1)])
            return
        else:
            return
    if zh and has_chinese(zh):
        t.catalog.add_alias(item.id, zh)
    results = t.prices(item, "q0", "sell")
    print(f"【{t.label(item.id)}】出售挂牌（Q0）")
    print("\n".join(t.price_lines(item, results)))
    if ov and ov.ok:
        text = hud_prices(results)
        ov.set("交易", f"{zh or item.name}\n{text}")
    qty = _input("要入库就输入数量（回车 = 只看价格）> ").strip()
    if not (qty.isdigit() and int(qty) > 0):
        return
    try:
        q = _quality(_input("品质（0–1000 或 q0–q7，回车 = 未知）> ")) or "unknown"
    except ValueError as e:
        print(e)
        return
    loc = _location(t)
    if loc:
        _commit(t, [StockLine(StockKey(item.id, q, loc), int(qty))])


def capture_flow(t, ov=None):
    from ..mining.screen import grab
    if ov:
        ov.hide()
    img = grab()
    crop = select_region(img)
    if ov and ov.ok and ov.sections:
        ov._render()                         # 截完把悬浮窗放回来
    if crop is None:
        print("已取消截图")
        return
    print("识别中…")
    from .ocr import recognize
    tokens = recognize(crop)
    rows = parse_inventory(tokens, t.catalog)
    if not rows:
        print("没认出文字，换个清晰点的区域再试")
        return
    buf = io.BytesIO()
    crop.save(buf, format="PNG")
    image_hash = hashlib.sha256(buf.getvalue()).hexdigest()
    final = review_rows(t, rows)
    if not final:
        return
    loc = _location(t)
    if not loc:
        print("没填位置，取消")
        return
    mode = "count" if _input("回车 = 新增数量，p = 盘点覆盖（按截图数量改写这几项）> ").strip().lower() == "p" else "add"
    _commit(t, [StockLine(StockKey(r.item_id, r.quality, loc, r.unit), r.quantity) for r in final], mode, image_hash)


def review_rows(t, rows):
    """逐行核对：认不准的物品/数量/品质在这里补上"""
    rows = list(rows)
    while True:
        print("识别结果：")
        for i, r in enumerate(rows, 1):
            name = t.label(r.item_id) if r.item_id else f"？{r.raw_name}（没对上物品）"
            q = r.quality.replace("exact:", "品质 ") if r.quality else "品质？"
            print(f"  {i}. {name}｜数量 {r.quantity if r.quantity else '？'}｜{q}")
        cmd = _input("回车 = 全部确认｜改 序号｜删 序号｜q = 放弃 > ").strip()
        if cmd.lower() == "q":
            return None
        if not cmd:
            bad = [i for i, r in enumerate(rows, 1) if not r.item_id or not r.quantity]
            if bad:
                print(f"第 {'、'.join(map(str, bad))} 行还缺物品或数量，先「改」一下或「删」掉")
                continue
            return [ImportRow(r.raw_name, r.item_id, r.quantity, r.quality or "unknown", r.unit, True) for r in rows]
        op, _, num = cmd.partition(" ")
        if not num.strip().isdigit() or not 1 <= int(num) <= len(rows):
            continue
        idx = int(num) - 1
        if op == "删":
            rows.pop(idx)
        elif op == "改":
            r = rows[idx]
            name = _input(f"物品（回车 = {t.label(r.item_id) if r.item_id else r.raw_name}）> ").strip()
            item_id = r.item_id
            if name or not r.item_id:
                item = pick_item(t, name or r.raw_name)
                item_id = item.id if item else item_id
            qty = _input(f"数量（回车 = {r.quantity or '？'}）> ").strip()
            quantity = int(qty) if qty.isdigit() and int(qty) > 0 else r.quantity
            try:
                quality = _quality(_input(f"品质（回车 = {r.quality or '未知'}）> ")) or r.quality
            except ValueError as e:
                print(e)
                quality = r.quality
            rows[idx] = ImportRow(r.raw_name, item_id, quantity, quality, r.unit)


def history_flow(t):
    rows = t.inventory.history()[:20]
    if not rows:
        print("还没有记录")
        return
    batches = []
    for r in rows:
        if not batches or batches[-1][0] != r["batch_id"]:
            batches.append((r["batch_id"], r, []))
        batches[-1][2].append(r)
    for i, (bid, first, items) in enumerate(batches, 1):
        at = datetime.fromisoformat(first["at"]).astimezone().strftime("%m-%d %H:%M")
        what = "，".join(f"{x['name']} {x['delta']:+d}" for x in items[:4]) + ("…" if len(items) > 4 else "")
        print(f"  {i}. {at}｜{first['mode']}｜{what}" + ("｜已撤销" if first["undone"] else ""))
    sel = _input("撤销哪一笔？输入序号（回车返回）> ").strip()
    if sel.isdigit() and 1 <= int(sel) <= len(batches):
        try:
            t.inventory.undo(batches[int(sel) - 1][0])
            print("✅ 已撤销")
        except ValueError as e:
            print(e)
