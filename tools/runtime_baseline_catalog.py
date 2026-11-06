"""物品查询与 F8 行为基线（IQ-B0）：用本机真实数据录一份输出，改完再录一份逐项比较。

用法（在项目根目录）：
  .venv\\Scripts\\python.exe -X utf8 tools\\runtime_baseline_catalog.py --out <输出.json>
  .venv\\Scripts\\python.exe -X utf8 tools\\runtime_baseline_catalog.py --compare <改前.json> <改后.json>

不联网、不写 userdata、不导入 overlay。Trade 用临时目录，网络、时间、F8 线程和悬浮窗都换成脚本内的替身。
"""

import argparse
import copy
import difflib
import itertools
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OFFLINE = "基线断网"
FIXED_WORDS = [
    "",
    "   ",
    "医疗笔",
    "MedPen",
    "FSK-8",
    "Parallax",
    "Citadel",
    "头盔",
    "铁",
    "lawson",
]
SOURCE_ORDER = ("shop", "loot", "wiki", "loc")


# ---------------------------------------------------------------- 调用适配
# IQ-B5 起物品查询三项调窗口接口（app/api/trade → tasks/catalog + app/presenters/catalog）；
# 全局搜索、商店导航、市场照旧调 tasks.trade；F8 照旧调 tasks.hover。
# IQ-B6 起 F8 的物品卡片、掉落、玩家市场经 bootstrap._hover_links 接（和桌面版同一份）。
def call_search(q=""):
    from astral_toolkit.tasks import trade

    return trade.search(q)


def call_item_search(q=""):
    from astral_toolkit.app.api import trade as api

    return api.item_search(q=q)


def call_item_info(name="", zh="", id=None, loot=True, exact=False):
    from astral_toolkit.app.api import trade as api

    return api.item_info(name=name, zh=zh, id=id, loot=loot, exact=exact)


def call_item_loot(name="", zh=""):
    from astral_toolkit.app.api import trade as api

    return api.item_loot(name=name, zh=zh)


def call_nav_shop(shop="", place=""):
    from astral_toolkit.tasks import trade

    deps: Any = (
        None  # 基线里 _start_nav 换成了只记目标的假的，用不到导航引擎（F 段 B5）
    )
    return trade.nav_shop(deps, shop, place)


def call_market_lookup(q=""):
    from astral_toolkit.tasks import trade

    return trade.market_lookup(q)


def call_market_prices(id="", quality="q0", op="sell"):
    from astral_toolkit.tasks import trade

    return trade.market_prices(id, quality, op)


def call_f8(img=None):
    from astral_toolkit import bootstrap
    from astral_toolkit.tasks import hover

    # IQ-B6：F8 的物品查询由 bootstrap 接，和桌面版同一份（F 段 B5 起当参数传）
    return hover.hover_once(bootstrap._hover_links(), img)


# ---------------------------------------------------------------- 小工具
def _reason(exc) -> str:
    if isinstance(exc, str):
        return exc
    return f"{type(exc).__name__}: {exc}"


def _skipped(exc) -> dict[str, str]:
    return {"skipped": _reason(exc)}


def _safe_deepcopy(value):
    try:
        return copy.deepcopy(value)
    except Exception:
        return value


def _has_cjk(text) -> bool:
    return bool(re.search(r"[一-鿿]", text or ""))


def _fold_name(text) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower().replace("l", "i"))


def _slug(text) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return out or "item"


def _named_noop(name):
    def noop(*_args, **_kwargs):
        return None

    noop.__name__ = name
    return noop


def _return_none(*_args, **_kwargs):
    return None


def _offline(*_args, **_kwargs):
    raise OSError(OFFLINE)


class _FakeDatetimeMeta(type):
    def __getattr__(cls, name):
        return getattr(datetime, name)


class _FakeDatetime(metaclass=_FakeDatetimeMeta):
    def __new__(cls, *args, **kwargs):
        return datetime(*args, **kwargs)

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


class _FakeTime:
    def time(self):
        return 1000.0

    def strftime(self, _fmt, *_args):
        return "12:00:00"

    def __getattr__(self, name):
        import time

        return getattr(time, name)


class _FakeThread:
    def __init__(
        self,
        box,
        group=None,
        target=None,
        name=None,
        args=(),
        kwargs=None,
        daemon=None,
        **_extra,
    ):
        self.box = box
        self.group = group
        self.target = target
        self.name = name
        self.args = args or ()
        self.kwargs = kwargs or {}
        self.daemon = daemon

    def start(self):
        target = self.target
        if target is None:
            return
        target_name = getattr(target, "__name__", "")
        if target_name == "_hover_more":
            target(*self.args, **self.kwargs)
        else:
            self.box.calls.append(["thread", target_name])


class _FakeProvider:
    def __init__(self, source, known=None, fallback=False, stats=True):
        self.source = source
        self.known = {key: list(value) for key, value in (known or {}).items()}
        self.fallback = fallback
        self.stats = stats
        self.calls = []

    def lookup(self, q):
        self.calls.append(["lookup", q])
        text = q or ""
        if text in self.known:
            from astral_toolkit.trade.models import Item

            return [Item(item_id, name) for item_id, name in self.known[text]]
        if self.fallback and text.strip():
            from astral_toolkit.trade.models import Item

            return [Item(f"{self.source}:{_slug(text)}", text.strip())]
        return []

    def fetch(self, item, qg, op, now):
        self.calls.append(["fetch", item.id, qg, op])
        from astral_toolkit.trade.models import PriceKey, PriceStats, ProviderResult

        if not self.stats:
            return ProviderResult(self.source, "empty", message="没有挂牌")
        key = PriceKey(self.source, item.id, qg, "UEC", "scu", "4.3", op)
        stat = PriceStats(
            key,
            Decimal("5000"),
            Decimal("4200"),
            3,
            now,
            Decimal("4800"),
        )
        return ProviderResult(self.source, "ok", (stat,), items=(item,))


class _Sandbox:
    """把边界换成脚本替身，退出时逐项还原。"""

    def __init__(self, tmp):
        self.tmp = Path(tmp)
        self._saved = []
        self.calls = []
        self.trade_hud_calls = []
        self.nav_calls = []
        self.inspect_result = None
        self.data_names_ready = True
        self.before_publish = None
        self.hover = None
        self._old_last_hover = {}

    def __enter__(self):
        from astral_toolkit.core import net as net_mod
        from astral_toolkit.core import run_records
        from astral_toolkit.crafting import loot as loot_mod
        from astral_toolkit.update import shops as shops_mod
        from astral_toolkit.navigation import position as position_mod
        from astral_toolkit.tasks import hover as hover_mod
        from astral_toolkit.tasks import navigation as navigation_mod
        from astral_toolkit.tasks import trade as trade_mod
        from astral_toolkit.tasks.system import about as about_mod
        from astral_toolkit.system import train_data
        from astral_toolkit.trade import console as console_mod
        from astral_toolkit.trade import inspector as inspector_mod

        self.hover = hover_mod
        self._old_last_hover = _safe_deepcopy(hover_mod._last_hover)

        self._patch(net_mod, "read", _offline)
        self._patch(loot_mod, "_get", _offline)
        self._patch(shops_mod, "_get", _offline)
        self._patch(console_mod, "datetime", _FakeDatetime)
        self._patch(trade_mod, "_item_hud", self._trade_hud)
        self._patch(trade_mod, "_trade", None)
        self._patch(hover_mod, "time", _FakeTime())
        self._patch(hover_mod, "WIN", False)
        self._patch(hover_mod, "_item_hud", self._hover_hud)
        self._patch(hover_mod, "_seq", itertools.count(1))
        self._patch(hover_mod, "inspect_item", self._inspect)
        self._patch(hover_mod, "threading", SimpleNamespace(Thread=self._thread))
        self._patch(hover_mod.bus, "publish", self._publish)
        self._patch(hover_mod.bus, "runtime_log", self._runtime_log)
        self._patch(hover_mod.preview, "update_preview", _named_noop("update_preview"))
        self._patch(inspector_mod, "_hover_log", _named_noop("_hover_log"))
        self._patch(train_data, "from_tooltip", _named_noop("from_tooltip"))
        self._patch(run_records, "record", _return_none)
        self._patch(about_mod, "data_names_ready", self._names_ready)
        self._patch(navigation_mod, "_start_nav", self._start_nav)
        self._patch(position_mod, "current", _return_none)
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        for obj, name, old in reversed(self._saved):
            setattr(obj, name, old)
        if self.hover is not None:
            self.hover._last_hover.clear()
            self.hover._last_hover.update(self._old_last_hover)
        return False

    def _patch(self, obj, name, value):
        self._saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def _thread(self, *args, **kwargs):
        return _FakeThread(self, *args, **kwargs)

    def _inspect(self, *_args, **_kwargs):
        return _safe_deepcopy(self.inspect_result)

    def _publish(self, topic, payload):
        if self.before_publish is not None:
            try:
                self.before_publish(topic, payload)
            except Exception:
                pass
        self.calls.append(["publish", topic, _safe_deepcopy(payload)])

    def _runtime_log(self, text, tag=None, level=None):
        self.calls.append(["log", level, text])

    def _hover_hud(self, text, secs=None):
        self.calls.append(["hud", text, secs])

    def _trade_hud(self, text, secs=None):
        self.trade_hud_calls.append(["hud", text, secs])

    def _names_ready(self):
        return bool(self.data_names_ready)

    def _start_nav(self, _deps, target, row=None, space_mode=None):
        self.nav_calls.append(
            {
                "target": _safe_deepcopy(target),
                "row": _safe_deepcopy(row),
                "space_mode": space_mode,
            }
        )
        return None

    def reset_hover(self):
        self.calls.clear()
        self.trade_hud_calls.clear()
        self.before_publish = None
        self.inspect_result = None
        self.data_names_ready = True
        if self.hover is not None:
            self.hover._last_hover.clear()
            self.hover._seq = itertools.count(1)


# ---------------------------------------------------------------- 元信息
def _git_head() -> str:
    try:
        done = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return done.stdout.strip() if done.returncode == 0 else ""
    except Exception:
        return ""


def _file_stamp(path) -> dict[str, Any]:
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return {"path": str(p), "exists": False}
    return {
        "path": str(p),
        "exists": True,
        "size": st.st_size,
        "mtime": st.st_mtime,
    }


def _gamedata_version() -> str:
    try:
        from astral_toolkit import gamedata

        return str(gamedata.version())
    except Exception:
        return ""


def _meta() -> dict[str, Any]:
    try:
        from astral_toolkit.core import paths

        data = paths.DATA
    except Exception:
        data = ROOT / "data"
    return {
        "git": _git_head(),
        "gamedata_version": _gamedata_version(),
        "data": {
            "shops": _file_stamp(data / "shops.json"),
            "loot_index": _file_stamp(data / "loot_index.json"),
        },
        "python": platform.python_version(),
        "PYTHONHASHSEED": os.environ.get("PYTHONHASHSEED", ""),
    }


# ---------------------------------------------------------------- 挑查询
def _index_rows():
    from astral_toolkit.tasks.catalog_queries import search

    index = search.build_index()
    return list(index.get("rows") or [])


def _row_source(row) -> str:
    if row.get("shop") is not None:
        return "shop"
    if row.get("loot"):
        return "loot"
    if row.get("wiki"):
        return "wiki"
    return "loc"


def _row_key(row):
    en = row.get("en") or ""
    return (en.lower(), en)


def _select_rows(rows):
    ordered = [row for row in rows if (row.get("en") or "").strip()]
    ordered.sort(key=_row_key)
    groups = {src: [] for src in SOURCE_ORDER}
    for row in ordered:
        groups[_row_source(row)].append(row)

    selected = []
    seen = set()
    counts = {src: 0 for src in SOURCE_ORDER}

    def add(row):
        en = row.get("en") or ""
        key = en.casefold()
        src = _row_source(row)
        if not en or key in seen or len(selected) >= 30:
            return False
        seen.add(key)
        selected.append(row)
        counts[src] += 1
        return True

    for src in SOURCE_ORDER:
        group = groups[src]
        if not group:
            continue
        step = max(1, len(group) // 3)
        for idx in range(0, len(group), step):
            if counts[src] >= 3:
                break
            add(group[idx])
        for row in group:
            if counts[src] >= 3:
                break
            add(row)

    stride = max(1, len(ordered) // 30)
    for idx in range(0, len(ordered), stride):
        if len(selected) >= 30:
            break
        add(ordered[idx])
    for row in ordered:
        if len(selected) >= 30:
            break
        add(row)

    selected.sort(key=_row_key)
    selection = {
        "rows": len(ordered),
        "stride": stride,
        "selected": len(selected),
        "available": {src: len(groups[src]) for src in SOURCE_ORDER},
        "selected_sources": counts,
        "short": {
            src: max(0, 3 - len(groups[src]))
            for src in SOURCE_ORDER
            if len(groups[src]) < 3
        },
    }
    if len(selected) < 30:
        selection["short_total"] = 30 - len(selected)
    return selected, selection


def _row_queries(row):
    en = row.get("en") or ""
    zh = row.get("zh") or ""
    raw = [en, en.lower()]
    if zh:
        raw.extend([zh, zh[:-1]])
    raw.append(en.replace("l", "I", 1) if "l" in en else en)

    out = []
    seen = set()
    for q in raw:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


def _all_queries(selected):
    out = []
    seen = set()

    def add(q):
        if q not in seen:
            seen.add(q)
            out.append(q)

    for q in FIXED_WORDS:
        add(q)
    for row in selected:
        for q in _row_queries(row):
            add(q)
    return out


# ---------------------------------------------------------------- 录制各项
def _store_call(items, key, fn, **kwargs):
    try:
        items[key] = fn(**kwargs)
    except Exception as exc:
        items[key] = _skipped(exc)


def _capture_market(items, key, box, fn, **kwargs):
    box.trade_hud_calls.clear()
    try:
        ret = fn(**kwargs)
    except Exception as exc:
        items[key] = {
            "skipped": _reason(exc),
            "hud": _safe_deepcopy(box.trade_hud_calls),
        }
        return
    items[key] = {
        "ret": ret,
        "hud": _safe_deepcopy(box.trade_hud_calls),
    }


def _collect_queries(items, selected, queries):
    for q in queries:
        _store_call(items, f"item_search.{q}", call_item_search, q=q)

    for row in selected:
        en = row.get("en") or ""
        zh = row.get("zh") or ""
        if not en:
            continue
        _store_call(
            items,
            f"item_info.{en}.exact",
            call_item_info,
            name=en,
            zh=zh,
            id=row.get("shop"),
            loot=True,
            exact=True,
        )
        _store_call(
            items,
            f"item_info.{en}.fuzzy",
            call_item_info,
            name=en,
            zh=zh,
            id=None,
            loot=True,
            exact=False,
        )

    for row in selected[:15]:
        en = row.get("en") or ""
        zh = row.get("zh") or ""
        if en:
            _store_call(
                items,
                f"item_loot.{en}",
                call_item_loot,
                name=en,
                zh=zh,
            )

    for q in FIXED_WORDS:
        _store_call(items, f"search.{q}", call_search, q=q)


def _buy_points(rows, limit=300):
    """按行排序依次列出商店买点 (行, (价格, 店, 地点))，最多 limit 个"""
    from astral_toolkit.tasks.catalog_queries import shops

    ordered = [row for row in rows if (row.get("en") or "").strip()]
    ordered.sort(key=_row_key)
    out = []
    for row in ordered:
        item_id = row.get("shop")
        if item_id is None:
            continue
        try:
            buy, _sell = shops.where(item_id)
        except Exception:
            continue
        for b in buy:
            out.append((row, b))
            if len(out) >= limit:
                return out
    return out


def _collect_nav(items, box, selected, rows):
    """hit：按顺序找第一个能导航的买点（地点在导航数据里）；missing：同一家店、不存在的地点"""
    points = _buy_points(selected) + _buy_points(rows)
    if not points:
        items["nav_shop.hit"] = {"skipped": "没有可用的商店买点"}
        items["nav_shop.missing"] = {"skipped": "没有可用的商店买点"}
        return

    chosen, tried = None, 0
    for _row, (price, shop, place) in points:
        tried += 1
        box.nav_calls.clear()
        try:
            ret = call_nav_shop(shop, place)
        except Exception as exc:
            ret = _skipped(exc)
        if not (isinstance(ret, dict) and ret.get("error") == "导航数据里没有这个地点"):
            chosen = (shop, place, ret, _safe_deepcopy(box.nav_calls))
            break
    if chosen is None:
        _row, (price, shop, place) = points[0]
        box.nav_calls.clear()
        ret = call_nav_shop(shop, place)
        chosen = (shop, place, ret, _safe_deepcopy(box.nav_calls))
    shop, place, ret, calls = chosen
    items["nav_shop.hit"] = {
        "shop": shop,
        "place": place,
        "tried": tried,
        "ret": ret,
        "start_nav": calls,
    }

    box.nav_calls.clear()
    try:
        ret = call_nav_shop(shop, "基线不存在的地点")
    except Exception as exc:
        ret = _skipped(exc)
    items["nav_shop.missing"] = {
        "ret": ret,
        "start_nav": _safe_deepcopy(box.nav_calls),
    }


def _fake_providers(known_uex=None, known_scm=None, fallback=False):
    return [
        _FakeProvider("uex", known_uex, fallback=fallback, stats=True),
        _FakeProvider("scm", known_scm, fallback=False, stats=False),
    ]


def _market_providers():
    return _fake_providers(
        {"Carinite": [("uex:4741", "Carinite")]},
        {
            "Carinite": [("scm:43475", "Carinite")],
            "科力晶": [("scm:43475", "Carinite")],
        },
    )


def _new_trade(tmp, providers, name):
    from astral_toolkit.trade.console import Trade

    directory = Path(tmp) / name
    directory.mkdir(parents=True, exist_ok=True)
    return Trade(directory=directory, providers=providers)


def _seed_trade(trade, entries):
    if not entries:
        return
    from astral_toolkit.trade.models import Item

    trade.catalog.upsert([Item(item_id, name) for item_id, name in entries])


def _bind_alias_recorder(trade):
    calls = []
    try:
        original = trade.catalog.add_alias
    except Exception:
        return calls

    def add_alias(item_id, zh):
        calls.append([item_id, zh])
        return original(item_id, zh)

    try:
        trade.catalog.add_alias = add_alias
    except Exception:
        return calls
    return calls


def _collect_market(items, box):
    _store_call(
        items,
        "market_lookup.Carinite",
        call_market_lookup,
        q="Carinite",
    )

    try:
        from astral_toolkit.tasks import trade as trade_mod
        from astral_toolkit.trade.models import Item

        trade_mod.trade().catalog.upsert([Item("uex:4741", "Carinite")])
    except Exception:
        pass

    for quality in ("q0", "q6"):
        for op in ("sell", "buy"):
            _capture_market(
                items,
                f"market_prices.uex:4741.{quality}.{op}",
                box,
                call_market_prices,
                id="uex:4741",
                quality=quality,
                op=op,
            )

    _capture_market(
        items,
        "market_prices.uex:no-such-item.q0.sell",
        box,
        call_market_prices,
        id="uex:no-such-item",
        quality="q0",
        op="sell",
    )


# ---------------------------------------------------------------- F8 场景
def _hover_result(
    zh,
    en,
    sure=True,
    quality=None,
    qty=None,
    unit=None,
    craft=None,
    canon=None,
    tokens=None,
    where="基线",
    raw=None,
):
    return {
        "zh": zh or "",
        "en": en or "",
        "quality": quality,
        "qty": qty,
        "unit": unit,
        "sure": bool(sure),
        "raw": raw,
        "canon": canon,
        "craft": craft or [],
        "tokens": tokens or [],
        "where": where,
    }


def _run_f8(box, tmp, name, res, seed, providers, data_ready=True, before_publish=None):
    box.reset_hover()
    box.inspect_result = res
    box.data_names_ready = data_ready
    box.before_publish = before_publish

    aliases = []
    ret = None
    error = None
    try:
        trade = _new_trade(tmp, providers, f"f8-{name}")
        _seed_trade(trade, seed)
        aliases = _bind_alias_recorder(trade)
        from astral_toolkit.tasks import trade as trade_mod

        trade_mod._trade = trade
        img = SimpleNamespace(width=1920, height=1080)
        ret = call_f8(img)
    except Exception as exc:
        error = _reason(exc)

    out = {
        "calls": _safe_deepcopy(box.calls),
        "aliases": _safe_deepcopy(aliases),
        "last_hover": _safe_deepcopy(box.hover._last_hover),
    }
    if error is None:
        out["ret"] = ret
    else:
        out["skipped"] = error
    return out


def _pick_shop_row(rows):
    ordered = [row for row in rows if (row.get("en") or "").strip()]
    ordered.sort(key=_row_key)
    for row in ordered:
        if row.get("shop") is not None and _has_cjk(row.get("zh") or ""):
            return row
    for row in ordered:
        if row.get("shop") is not None:
            return row
    return None


def _pick_loot_row(rows):
    ordered = [row for row in rows if (row.get("en") or "").strip()]
    ordered.sort(key=_row_key)
    for row in ordered:
        if _row_source(row) == "loot":
            return row
    return None


def _pick_mineral():
    en = "Carinite"
    zh = "科力晶"
    try:
        from astral_toolkit.core.i18n import mineral_zh

        zh = mineral_zh(en) or zh
    except Exception:
        pass
    return en, zh


def _item_info_id(name):
    from astral_toolkit.crafting import acquire

    data = acquire.info(
        name_en=name,
        name_zh="",
        item_id=None,
        show_loot=False,
        exact=False,
        loot_online=False,
    )
    return data.get("id")


def _make_typo(name):
    for idx, ch in enumerate(name):
        if ch.isalpha():
            repl = "z" if ch.lower() != "z" else "x"
            return name[:idx] + repl + name[idx + 1 :]
    for idx, ch in enumerate(name):
        if ch.isdigit():
            repl = "9" if ch != "9" else "8"
            return name[:idx] + repl + name[idx + 1 :]
    return None


def _pick_typo(rows):
    ordered = [row for row in rows if (row.get("en") or "").strip()]
    ordered.sort(key=_row_key)
    preferred = [
        row
        for row in ordered
        if (row.get("en") or "").casefold() in ("parallax", "citadel")
    ]
    candidates = preferred + ordered
    seen = set()
    tried = 0
    for row in candidates:
        en = row.get("en") or ""
        if not en or en in seen:
            continue
        seen.add(en)
        if row.get("shop") is None and row not in preferred:
            continue
        folded = _fold_name(en)
        if not 7 <= len(folded) <= 8:
            continue
        typo = _make_typo(en)
        if not typo:
            continue
        ratio = difflib.SequenceMatcher(None, _fold_name(typo), _fold_name(en)).ratio()
        if ratio < 0.85:
            continue
        tried += 1
        if tried > 60:
            break
        try:
            if _item_info_id(en) is None:
                continue
            if _item_info_id(typo) is not None:
                continue
        except Exception:
            continue
        return en, typo
    return None, None


def _seq_change_callback(box):
    state = {"done": False}

    def callback(topic, _payload):
        if topic == "hover_more" and not state["done"]:
            state["done"] = True
            box.hover._last_hover["seq"] = -1

    return callback


def _collect_f8(items, box, tmp, rows):
    shop = _pick_shop_row(rows)
    loot = _pick_loot_row(rows)
    mineral_en, mineral_zh = _pick_mineral()
    typo_correct, typo_en = _pick_typo(rows)

    items["f8.miss"] = _run_f8(
        box,
        tmp,
        "miss",
        None,
        None,
        _fake_providers(),
    )

    shop_en = (shop or {}).get("en") or ""
    if shop is None or not shop_en:
        for name in ("shop_sure", "craft", "seq_changed"):
            items[f"f8.{name}"] = {"skipped": "没有可用的商店物品"}
    else:
        shop_zh = shop.get("zh") or ""
        if not _has_cjk(shop_zh):
            try:
                from astral_toolkit.tasks import catalog as catalog_mod

                shop_zh = catalog_mod._zh_of(shop_en) or shop_zh
            except Exception:
                pass

        shop_id = "uex:baseline-shop"
        shop_res = _hover_result(
            shop_zh,
            shop_en,
            sure=True,
            quality=650,
            qty=2,
            unit="个",
            canon=shop_zh,
        )
        shop_seed = [(shop_id, shop_en)]
        items["f8.shop_sure"] = _run_f8(
            box,
            tmp,
            "shop_sure",
            shop_res,
            shop_seed,
            _fake_providers({shop_en: shop_seed}),
        )

        craft_id = "uex:baseline-craft"
        craft_res = _hover_result(
            shop_zh,
            shop_en,
            sure=True,
            quality=650,
            qty=2,
            unit="个",
            craft=[
                {"slot": "框架", "q": 858},
                {"slot": "线缆", "q": 916},
            ],
        )
        craft_seed = [(craft_id, shop_en)]
        items["f8.craft"] = _run_f8(
            box,
            tmp,
            "craft",
            craft_res,
            craft_seed,
            _fake_providers({shop_en: craft_seed}),
        )

        seq_id = "uex:baseline-seq"
        seq_res = _hover_result(
            shop_zh,
            shop_en,
            sure=True,
            quality=650,
            qty=2,
            unit="个",
        )
        seq_seed = [(seq_id, shop_en)]
        items["f8.seq_changed"] = _run_f8(
            box,
            tmp,
            "seq_changed",
            seq_res,
            seq_seed,
            _fake_providers({shop_en: seq_seed}),
            before_publish=_seq_change_callback(box),
        )

    loot_en = (loot or {}).get("en") or ""
    if loot is None or not loot_en:
        items["f8.loot_only_unsure"] = {"skipped": "没有只在掉落数据里的物品"}
    else:
        loot_zh = loot.get("zh") or ""
        loot_id = "uex:baseline-loot"
        loot_seed = [(loot_id, loot_en)]
        loot_res = _hover_result(
            loot_zh,
            loot_en,
            sure=False,
            canon=None,
        )
        items["f8.loot_only_unsure"] = _run_f8(
            box,
            tmp,
            "loot_only_unsure",
            loot_res,
            loot_seed,
            _fake_providers({loot_en: loot_seed}),
            data_ready=False,
        )

    mineral_id = "uex:baseline-mineral"
    mineral_seed = [(mineral_id, mineral_en)]
    mineral_res = _hover_result(
        mineral_zh,
        mineral_en,
        sure=True,
        qty=0.495,
        unit="SCU",
    )
    items["f8.mineral_scu"] = _run_f8(
        box,
        tmp,
        "mineral_scu",
        mineral_res,
        mineral_seed,
        _fake_providers({mineral_en: mineral_seed}),
    )

    if not typo_correct or not typo_en:
        items["f8.typo_en"] = {"skipped": "没有找到合适的英文错字场景"}
    else:
        typo_id = f"uex:baseline-typo-{_slug(typo_correct)}"
        typo_res = _hover_result("", typo_en, sure=True)
        items["f8.typo_en"] = _run_f8(
            box,
            tmp,
            "typo_en",
            typo_res,
            None,
            _fake_providers({typo_en: [(typo_id, typo_correct)]}),
        )


# ---------------------------------------------------------------- 录制与比较
def collect() -> dict[str, Any]:
    tmp = Path(tempfile.mkdtemp(prefix="at_catalog_baseline_"))
    with _Sandbox(tmp) as box:
        try:
            from astral_toolkit import gamedata

            gamedata.ensure()
        except Exception as exc:
            return {"skipped": f"gamedata 不可用：{_reason(exc)}"}

        meta = _meta()
        items: dict[str, Any] = {}

        try:
            rows = _index_rows()
        except Exception as exc:
            items["_index"] = _skipped(exc)
            rows = []

        selected, selection = _select_rows(rows)
        meta["selection"] = selection
        queries = _all_queries(selected)

        from astral_toolkit.tasks import trade as trade_mod

        trade_mod._trade = _new_trade(tmp, _market_providers(), "market")

        _collect_queries(items, selected, queries)
        _collect_nav(items, box, selected, rows)
        _collect_market(items, box)
        _collect_f8(items, box, tmp, rows)

    return {"meta": meta, "items": items}


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _diff(left, right, path, out):
    if len(out) >= 20:
        return
    if type(left) is not type(right):
        out.append((path, left, right))
        return
    if isinstance(left, dict):
        left_keys = list(left)
        right_keys = list(right)
        if left_keys != right_keys:
            out.append((path + ".<keys>", left_keys, right_keys))
            if len(out) >= 20:
                return
        for key in left_keys:
            if len(out) >= 20:
                return
            if key in right:
                _diff(left[key], right[key], f"{path}.{key}", out)
            else:
                out.append((f"{path}.{key}", left[key], "<缺失>"))
        for key in right_keys:
            if len(out) >= 20:
                return
            if key not in left:
                out.append((f"{path}.{key}", "<缺失>", right[key]))
        return
    if isinstance(left, list):
        if len(left) != len(right):
            out.append((path, left, right))
            return
        for idx, (a, b) in enumerate(zip(left, right)):
            if len(out) >= 20:
                return
            _diff(a, b, f"{path}[{idx}]", out)
        return
    if left != right:
        out.append((path, left, right))


def _show(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _compare(path_a, path_b) -> int:
    left = _load_json(path_a).get("items", {})
    right = _load_json(path_b).get("items", {})
    diffs: list[tuple[str, Any, Any]] = []
    _diff(left, right, "items", diffs)
    if not diffs:
        print("items 相同")
        return 0
    for path, a, b in diffs:
        print(path)
        print(f"  A = {_show(a)}")
        print(f"  B = {_show(b)}")
    if len(diffs) >= 20:
        print("（最多显示 20 处差异）")
    return 1


def main(argv=None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description="IQ-B0 物品查询 / F8 行为基线")
    ap.add_argument("--out", metavar="JSON", help="录制输出 JSON 路径")
    ap.add_argument(
        "--compare",
        nargs=2,
        metavar=("A", "B"),
        help="比较两个基线 JSON 的 items",
    )
    args = ap.parse_args(args_list)

    if args.compare:
        return _compare(args.compare[0], args.compare[1])
    if not args.out:
        ap.error("需要 --out 或 --compare")

    if os.environ.get("PYTHONHASHSEED") != "0":
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = "0"
        cmd = [
            sys.executable,
            "-X",
            "utf8",
            str(Path(__file__).resolve()),
            *args_list,
        ]
        return subprocess.run(cmd, env=env, check=False).returncode

    result = collect()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )
    if "skipped" in result:
        print(f"跳过：{result['skipped']}")
    else:
        print(f"基线写到 {out}：{len(result.get('items', {}))} 项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
