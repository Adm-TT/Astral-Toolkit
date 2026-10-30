"""原矿记录（1.6.70，用户要求）：采矿助手里点「记录」或游戏里按热键，把这块矿的读数、成分、品质、价格和坐标存下来。
存在 userdata/ore_log.json（升级不动、不打包）。坐标只用 /showlocation 的（和路标同一个规矩），读不到就空着"""
import json
import threading
import time
import uuid

from ..core.paths import USER

FILE = USER / "ore_log.json"
MAX = 2000                      # 最多留这么多条，再多删最旧的
_LOCK = threading.Lock()


def load():
    """原矿记录（查询用：读不到就当没有）"""
    try:
        return _load_strict()
    except RuntimeError:
        return []


def _load_strict():
    """原矿记录（改写前用）：文件读不到或坏了就抛错，别当成空表（细查 2026-10-28：否则接着记一块矿会把整份覆盖掉）"""
    try:
        rows = json.loads(FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except OSError as e:
        raise RuntimeError(f"原矿记录暂时读不到：{e}")
    except ValueError as e:
        raise RuntimeError(f"原矿记录文件损坏（userdata 里的 ore_log.json）：{e}")
    return rows if isinstance(rows, list) else []


def _save(rows):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(FILE)


def from_view(view):
    """采矿助手的结果（tasks.mining.scan_view）→ 一条记录（不含坐标）"""
    ref = (view.get("refine") or [{}])[0] if view.get("refine") else {}
    lots = [{"zh": r.get("zh"), "en": r.get("en"), "pct": r.get("pct"), "q": r.get("q"), "scu": r.get("scu"),
             "inert": bool(r.get("inert"))} for r in view.get("lots") or []]
    return {"rock": view.get("rock") or "?", "mass": view.get("mass"), "resistance": view.get("resistance"),
            "instability": view.get("instability"), "difficulty": view.get("difficulty") or "",
            "total_scu": view.get("total_scu"), "lots": lots, "cut": bool(view.get("cut")),
            "refined_scu": ref.get("scu"), "value": ref.get("value"),
            "plan": f"{ref['method']} · {ref['station']}" if ref.get("method") else "",
            "scanned": view.get("at") or ""}


def add(rec):
    rec = {"id": uuid.uuid4().hex[:12], "at": time.strftime("%Y-%m-%d %H:%M:%S"), **rec}
    with _LOCK:
        rows = _load_strict()
        rows.append(rec)
        _save(rows[-MAX:])
    return rec


def restore(rec):
    """撤销删除：原样放回去（按时间排回原来的位置）"""
    if not isinstance(rec, dict) or not rec.get("id"):
        raise ValueError("没有可恢复的记录")
    with _LOCK:
        rows = [r for r in _load_strict() if r.get("id") != rec["id"]]
        rows.append(rec)
        rows.sort(key=lambda r: r.get("at") or "")
        _save(rows[-MAX:])
    return rec


def update(rid, **kw):
    with _LOCK:
        rows = load()
        for r in rows:
            if r.get("id") == rid:
                r.update(kw)
                _save(rows)
                return r
    return None


def delete(rid):
    with _LOCK:
        rows = load()
        gone = [r for r in rows if r.get("id") == rid]
        if gone:
            _save([r for r in rows if r.get("id") != rid])
    return gone[0] if gone else None
