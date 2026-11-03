"""新展示流 ui/1（UI-K0a）：独立于旧 bus 的发布、订阅与全家福缓存。

- publish_ui()：同一把锁里分配 ui_seq、更新缓存、入每个订阅者自己的有界队列
- subscribe()：锁内原子地生成 conn、取当前 ui_seq 作为 hello，返回独立队列；关闭后返回「已关闭」
- 队列满：标记该订阅断开，交给 SSE 处理函数结束响应，不静默丢
- snapshot()：只读全家福，不修改开关/磁贴；开关刷新走 set_switches()
- drain_and_bye()：先结束剩余活动（摘要通知先于终态），再 bye，并等待队列排空
- 旧通道 /api/events 与 bus.publish / bus.subscribe 完全不动
"""

import copy
import json
import queue
import secrets
import threading
import time

from .presenters.mining import tile_status as mining_tile_status

PROTOCOL = "ui/1"
instance_id = secrets.token_urlsafe(18)  # 进程启动一次，重启就换
INSTANCE_ID = instance_id
_QUEUE_MAX = 2000
ENDED_MAX = 256
SUMMARY_KEEP = 1200
TRANSIENT_KEEP = 10.0

_lock = threading.Lock()
_idle = threading.Condition(_lock)  # 等队列排空时复用同一把锁
_subs = []
_queues = {}
_conn_seq = 0
_seq = 0
_notice_seq = 0
_activities = {}
_tiles = {}
_notices = {}
_notice_times = {}
_ended = {}
_switches = {}
_switch_read_mono = None
_switch_revision = 0  # 仅保护锁外采样提交，不进入展示协议
_shutting_down = False


class _Sub:
    __slots__ = ("conn", "q", "alive", "bye_sent")

    def __init__(self, conn, q):
        self.conn = conn
        self.q = q
        self.alive = True
        self.bye_sent = False


def _wall():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _copy(data):
    try:
        return copy.deepcopy(data)
    except Exception:
        return data


def _kind(kind):
    text = str(kind)
    return text if text.startswith("ui.") else "ui." + text


def _reason_text(reason):
    return {
        "done": "已完成",
        "error": "出错结束",
        "user": "已取消",
        "shutdown": "AT 退出",
        "replaced": "被新任务取代",
        "idle": "空闲结束",
    }.get(reason, "已结束")


def _remove_sub_locked(sub):
    if sub in _subs:
        _subs.remove(sub)
    _queues.pop(id(sub.q), None)
    _idle.notify_all()


def _clean_notices_locked():
    """清掉划掉的、过期的摘要 / 短暂通知；不发消息，客户端按 lifetime 自己收起。"""
    now = time.monotonic()
    for notice_id, notice in list(_notices.items()):
        born = _notice_times.get(notice_id)
        if born is None:
            born = now
            _notice_times[notice_id] = born
        lifetime = notice.get("lifetime")
        remove = bool(notice.get("dismissed"))
        if not remove and lifetime == "summary" and now - born > SUMMARY_KEEP:
            remove = True
        if not remove and lifetime == "transient" and now - born > TRANSIENT_KEEP:
            remove = True
        if remove:
            _notices.pop(notice_id, None)
            _notice_times.pop(notice_id, None)
    for notice_id in list(_notice_times):
        if notice_id not in _notices:
            _notice_times.pop(notice_id, None)


def _send_locked(kind, payload):
    """锁内分配全局 ui_seq，并把带各自 conn 的消息入每个订阅队列"""
    global _seq
    if _shutting_down:
        return _seq
    _seq += 1
    seq = _seq
    dead = []
    for sub in _subs:
        if not sub.alive:
            continue
        msg = {"kind": kind}
        for key, value in payload.items():
            if key in ("kind", "conn", "ui_seq"):
                continue
            msg[key] = value
        msg["conn"] = sub.conn
        msg["ui_seq"] = seq
        try:
            sub.q.put_nowait(msg)
        except queue.Full:
            sub.alive = False
            dead.append(sub)
    for sub in dead:
        _remove_sub_locked(sub)
    _idle.notify_all()
    return seq


def _current_activity_id(kind):
    found = None
    for activity_id, activity in _activities.items():
        if activity.get("kind") == kind:
            found = activity_id
    return found


def _make_tile(tile_id, on, activity_id=None):
    activity = _activities.get(activity_id) if activity_id else None
    line = "运行中" if on else "已关闭"
    if activity and activity.get("title"):
        line = str(activity["title"])
    return {
        "tile_id": tile_id,
        "on": bool(on),
        "available": {"ok": True},
        "status_line": line,
        "action": None,
        "activity_id": activity_id,
    }


def _derive_tiles_locked(publish):
    """磁贴只从当前活动 + 已读到的开关状态派生，不接受旧活动单独更新"""
    derived = {}
    mining_id = _current_activity_id("mining")
    if "live_on" in _switches or "live_running" in _switches:
        on = bool(_switches.get("live_on") or _switches.get("live_running"))
        derived["mining"] = _make_tile("mining", on, mining_id)
        runtime = _switches.get("mining_runtime")
        if isinstance(runtime, dict):
            derived["mining"].update(mining_tile_status(on, runtime))
    nav_id = _current_activity_id("nav")
    if "nav_running" in _switches:
        derived["nav"] = _make_tile("nav", _switches["nav_running"], nav_id)
    if "position_active" in _switches:
        tile = _make_tile("position", _switches["position_active"])
        derived["position"] = tile
    if "hover_on" in _switches:
        derived["hover"] = _make_tile("hover", _switches["hover_on"])
    if "overlay_on" in _switches:
        derived["overlay"] = _make_tile("overlay", _switches["overlay_on"])
    for tile_id, tile in derived.items():
        old = _tiles.get(tile_id)
        _tiles[tile_id] = _copy(tile)
        if publish and old != tile:
            _send_locked("ui.tile", {"tile": _copy(tile)})


def _remember_ended_locked(activity_id, end):
    _ended[activity_id] = _copy(end)
    try:
        limit = int(ENDED_MAX)
    except Exception:
        limit = 256
    if limit < 0:
        limit = 0
    while len(_ended) > limit:
        _ended.pop(next(iter(_ended)), None)


def _publish_activity_locked(data):
    if _shutting_down:
        return _seq
    activity = data.get("activity", data)
    if not isinstance(activity, dict):
        return _seq
    activity_id = activity.get("activity_id")
    if activity_id is not None:
        if activity_id in _ended:
            return _seq
        _activities[activity_id] = _copy(activity)
    seq = _send_locked("ui.activity", {"activity": activity})
    _derive_tiles_locked(True)
    return seq


def _publish_activity_end_locked(data):
    global _notice_seq
    if _shutting_down:
        return _seq
    activity_id = data.get("activity_id")
    if not activity_id:
        return _send_locked("ui.activity_end", data)
    if activity_id in _ended:
        return _seq
    activity = _activities.get(activity_id) or {}
    reason = data.get("end_reason") or "done"
    error = data.get("error")
    notice_id = data.get("summary_notice_id")
    if not notice_id:
        _notice_seq += 1
        notice_id = f"summary:{activity_id}:{_notice_seq}"
    level = "error" if reason == "error" else "info"
    lifetime = "until_ack" if reason == "error" else "summary"
    title = data.get("notice_title")
    if not title:
        title = f"{activity.get('title') or activity_id}结束"
    body = data.get("notice_body") or _reason_text(reason)
    source = activity.get("kind") or str(activity_id).split(":")[0]
    notice = {
        "notice_id": notice_id,
        "source": source,
        "level": level,
        "title": title,
        "body": body,
        "created_wall": _wall(),
        "link": None,
        "activity_id": activity_id,
        "lifetime": lifetime,
        "dismissed": False,
    }
    _notices[notice_id] = _copy(notice)
    _notice_times.setdefault(notice_id, time.monotonic())
    _send_locked("ui.notice", {"notice": notice})
    _activities.pop(activity_id, None)
    end = {
        "activity_id": activity_id,
        "end_reason": reason,
        "summary_notice_id": notice_id,
    }
    if error is not None:
        end["error"] = str(error)
    _remember_ended_locked(activity_id, end)
    seq = _send_locked("ui.activity_end", end)
    _derive_tiles_locked(True)
    return seq


def _publish_tile_locked(data):
    if _shutting_down:
        return _seq
    tile = data.get("tile", data)
    if not isinstance(tile, dict):
        return _seq
    activity_id = tile.get("activity_id")
    if activity_id is not None and activity_id not in _activities:
        return _seq
    tile_id = tile.get("tile_id")
    if tile_id is not None:
        _tiles[tile_id] = _copy(tile)
    return _send_locked("ui.tile", {"tile": tile})


def _publish_notice_locked(data):
    if _shutting_down:
        return _seq
    notice = data.get("notice", data)
    if not isinstance(notice, dict):
        return _seq
    notice_id = notice.get("notice_id")
    if notice_id is not None:
        _notices[notice_id] = _copy(notice)
        _notice_times.setdefault(notice_id, time.monotonic())
    return _send_locked("ui.notice", {"notice": notice})


def _publish_notice_dismiss_locked(data):
    if _shutting_down:
        return _seq
    notice_id = data.get("notice_id")
    if notice_id is None:
        return _seq
    notice = _notices.get(notice_id)
    if notice is not None:
        if notice.get("dismissed"):
            return _seq
        notice = _copy(notice)
        notice["dismissed"] = True
        _notices[notice_id] = notice
    return _send_locked("ui.notice_dismiss", {"notice_id": notice_id})


def publish_ui(kind, data):
    """发一条新流消息；锁内分配 ui_seq、更新全家福缓存、入各订阅队列"""
    kind = _kind(kind)
    payload = _copy(data if isinstance(data, dict) else {"value": data})
    with _lock:
        if _shutting_down:
            return _seq
        _clean_notices_locked()
        if kind == "ui.activity":
            return _publish_activity_locked(payload)
        if kind == "ui.activity_end":
            return _publish_activity_end_locked(payload)
        if kind == "ui.tile":
            return _publish_tile_locked(payload)
        if kind == "ui.notice":
            return _publish_notice_locked(payload)
        if kind == "ui.notice_dismiss":
            return _publish_notice_dismiss_locked(payload)
        return _send_locked(kind, payload)


def _closed_locked():
    return {
        "kind": "ui.closed",
        "protocol": PROTOCOL,
        "instance_id": INSTANCE_ID,
        "conn": None,
        "ui_seq": _seq,
        "error": "已关闭",
    }


def subscribe(maxsize=None):
    """锁内生成 conn、取当前 ui_seq 作 hello，返回 (hello, 独立有界队列)。

    已关闭时返回 (明确的 ui.closed hello, None)。订阅前先刷新一次开关；
    有变化会走 set_switches() 分配 ui_seq 并广播 ui.tile。
    """
    global _conn_seq
    if maxsize is None:
        maxsize = _QUEUE_MAX
    with _lock:
        if _shutting_down:
            return _closed_locked(), None
    try:
        refresh_switches()
    except Exception:
        pass
    q = queue.Queue(maxsize=maxsize)
    with _lock:
        if _shutting_down:
            return _closed_locked(), None
        _conn_seq += 1
        conn = _conn_seq
        sub = _Sub(conn, q)
        _subs.append(sub)
        _queues[id(q)] = sub
        hello = {
            "kind": "ui.hello",
            "protocol": PROTOCOL,
            "instance_id": INSTANCE_ID,
            "conn": conn,
            "ui_seq": _seq,
        }
    return hello, q


def unsubscribe(q):
    with _lock:
        sub = _queues.get(id(q))
        if sub is not None:
            _remove_sub_locked(sub)


def is_connected(q):
    with _lock:
        sub = _queues.get(id(q))
        return bool(sub and sub.alive)


def connection_info(q):
    with _lock:
        sub = _queues.get(id(q))
        return (sub.conn if sub else None), _seq


def mark_dequeued(q):
    """SSE 从队列取走一条后调用，让退出排空能及时结束等待"""
    with _lock:
        _idle.notify_all()


def heartbeat(conn):
    with _lock:
        return {
            "kind": "ui.heartbeat",
            "conn": conn,
            "ui_seq": _seq,
        }


def snapshot(conn):
    """返回与同一把锁下状态一致的全家福；只读，不修改开关或磁贴。"""
    with _lock:
        _clean_notices_locked()
        seq = _seq
        activities = _copy(list(_activities.values()))
        tiles = _copy(list(_tiles.values()))
        notices = _copy(
            [notice for notice in _notices.values() if not notice.get("dismissed")]
        )
        ended = list(_ended.keys())
    return {
        "protocol": PROTOCOL,
        "instance_id": INSTANCE_ID,
        "conn": conn,
        "ui_seq": seq,
        "activities": activities,
        "tiles": tiles,
        "notices": notices,
        "ended": ended,
    }


def _clean_switches(switches):
    if not isinstance(switches, dict):
        return {}
    allowed = (
        "live_on",
        "live_running",
        "nav_running",
        "position_active",
        "hover_on",
        "overlay_on",
    )
    clean = {key: bool(switches[key]) for key in allowed if key in switches}
    if isinstance(switches.get("mining_runtime"), dict):
        clean["mining_runtime"] = _copy(switches["mining_runtime"])
    return clean


def set_switches(switches, read_mono=None, expected_revision=None):
    """开关变化唯一入口：锁内派生磁贴，有变化就分配 ui_seq 并广播 ui.tile。"""
    global _switch_read_mono, _switch_revision
    with _lock:
        if _shutting_down:
            return _seq
        if expected_revision is not None and expected_revision != _switch_revision:
            return _seq
        if (
            read_mono is not None
            and _switch_read_mono is not None
            and read_mono < _switch_read_mono
        ):
            return _seq
        if read_mono is not None:
            _switch_read_mono = read_mono
        clean = _clean_switches(switches)
        runtime = _switches.get("mining_runtime")
        if (
            "mining_runtime" not in clean
            and ("live_on" in clean or "live_running" in clean)
            and isinstance(runtime, dict)
        ):
            # 开停消息比采样先到：保留旧线程收尾事实，开启许可等新采样确认。
            _switches["mining_runtime"] = {**runtime, "pending_read": True}
        _switches.update(clean)
        _switch_revision += 1
        _derive_tiles_locked(True)
        return _seq


def _call_running(obj):
    value = getattr(obj, "running", None)
    if value is None:
        return None
    if callable(value):
        value = value()
    return bool(value)


def _read_mining_state(loop):
    """只能在展示锁外读；跨调用碰上会话变化就留待下一轮，不拼接两个时刻。"""
    try:
        state = loop.state()
        can_start = loop.can_start()
        if loop.state() != state:
            return None
        return {
            "state": state.state.value,
            "running": state.state.value in ("starting", "running", "paused"),
            "draining": state.prev_stop_pending,
            "can_start": can_start,
        }
    except Exception:
        return None


def read_switches():
    """在锁外读现有开关状态；读不到的项目不放进来，也不生成对应磁贴"""
    out = {}
    engines = live = loop = None
    try:
        from ..tasks.system.common import _engines

        engines = _engines()
        live = getattr(engines, "live", None)
        loop = getattr(live, "loop", None)
    except Exception:
        pass
    if loop is None:
        # 有会话循环时 live_on 以运行事实为准，不用每秒读一次设置文件
        try:
            from ..core import settings

            cfg = settings.load()
            if isinstance(cfg, dict) and "live_on" in cfg:
                out["live_on"] = bool(cfg.get("live_on"))
        except Exception:
            pass
    try:
        if engines is None:
            raise LookupError
        if loop is not None:
            # 运行事实优先于持久化开关；采样不完整时保留上次展示，不用旧设置覆盖。
            out.pop("live_on", None)
            runtime = _read_mining_state(loop)
            if runtime is not None:
                out.update(
                    live_on=runtime["running"],
                    live_running=runtime["running"],
                    mining_runtime=runtime,
                )
        else:
            running = _call_running(live)
            if running is not None:
                out["live_running"] = running
        running = _call_running(getattr(engines, "nav", None))
        if running is not None:
            out["nav_running"] = running
        pos = getattr(engines, "pos", None)
        reader = getattr(pos, "reader", None)
        if reader is not None and hasattr(reader, "active"):
            out["position_active"] = bool(reader.active)
    except Exception:
        pass
    return out


def refresh_switches():
    """刷新一次运行层开关；有变化走 set_switches()，因而会广播 ui.tile。"""
    with _lock:
        if _shutting_down:
            return _seq
        revision = _switch_revision
    read_mono = time.monotonic()
    return set_switches(
        read_switches(), read_mono=read_mono, expected_revision=revision
    )


def dismiss_notice(notice_id):
    """后台权威地划掉一条通知；找不到或已关闭返回 False"""
    with _lock:
        if _shutting_down:
            return False
        notice = _notices.get(notice_id)
        if notice is None:
            return False
        if not notice.get("dismissed"):
            notice = _copy(notice)
            notice["dismissed"] = True
            _notices[notice_id] = notice
            _send_locked("ui.notice_dismiss", {"notice_id": notice_id})
        return True


def _has_pending_locked():
    for sub in _subs:
        if not sub.alive:
            continue
        if not sub.q.empty():
            return True
    return False


def _bye_all_locked():
    global _shutting_down
    _shutting_down = True
    dead = []
    sent = 0
    for sub in _subs:
        if not sub.alive or sub.bye_sent:
            continue
        msg = {
            "kind": "ui.bye",
            "conn": sub.conn,
            "ui_seq": _seq,
        }
        try:
            sub.q.put_nowait(msg)
            sub.bye_sent = True
            sent += 1
        except queue.Full:
            sub.alive = False
            dead.append(sub)
    for sub in dead:
        _remove_sub_locked(sub)
    _idle.notify_all()
    return sent


def bye_all():
    with _idle:
        return _bye_all_locked()


def drain_and_bye(timeout=1.0):
    """退出：结束剩余活动 -> 发 bye -> 最多等 timeout 秒让队列被取空。"""
    deadline = time.monotonic() + float(timeout)
    with _idle:
        for activity_id in list(_activities):
            _publish_activity_end_locked(
                {
                    "activity_id": activity_id,
                    "end_reason": "shutdown",
                }
            )
        sent = _bye_all_locked()
        while _has_pending_locked():
            remain = deadline - time.monotonic()
            if remain <= 0:
                break
            _idle.wait(remain)
        return sent


def encode(msg):
    return "data: " + json.dumps(msg, ensure_ascii=False, default=str) + "\n\n"


def reset_for_tests():
    """只给测试用：清空本模块的进程内状态，不换 instance_id"""
    global _seq, _notice_seq, _conn_seq, _shutting_down, _switches, _switch_read_mono
    global _switch_revision
    with _idle:
        _subs.clear()
        _queues.clear()
        _seq = 0
        _notice_seq = 0
        _conn_seq = 0
        _activities.clear()
        _tiles.clear()
        _notices.clear()
        _notice_times.clear()
        _ended.clear()
        _switches = {}
        _switch_read_mono = None
        _switch_revision = 0
        _shutting_down = False
        _idle.notify_all()
