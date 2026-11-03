"use strict";

const DEFAULT_ENDED_MAX = 512;
const DEFAULT_LAST_ENDS_MAX = 20;

function clone(value) {
  if (Array.isArray(value)) {
    return value.map(clone);
  }
  if (value && typeof value === "object") {
    const out = {};
    for (const key of Object.keys(value)) {
      out[key] = clone(value[key]);
    }
    return out;
  }
  return value;
}

function idText(value) {
  return value == null ? "" : String(value);
}

function compareIds(left, right) {
  const a = idText(left);
  const b = idText(right);
  if (a < b) {
    return -1;
  }
  if (a > b) {
    return 1;
  }
  return 0;
}

function sortObjects(values, field) {
  return values
    .slice()
    .sort((left, right) => {
      const a = left && left[field];
      const b = right && right[field];
      return compareIds(a, b);
    })
    .map(clone);
}

function toSequence(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : NaN;
}

function sequenceOrZero(value) {
  const number = toSequence(value);
  return Number.isNaN(number) ? 0 : number;
}

function pickLimit(config, keys, fallback) {
  for (const key of keys) {
    const value = config[key];
    if (Number.isInteger(value) && value >= 0) {
      return value;
    }
  }
  return fallback;
}

export function createUiStore(options = {}) {
  const config = options && typeof options === "object" ? options : {};
  const endedMax = pickLimit(
    config,
    ["endedLimit", "maxEnded"],
    DEFAULT_ENDED_MAX
  );
  const lastEndsMax = pickLimit(
    config,
    ["lastEndsLimit", "maxLastEnds"],
    DEFAULT_LAST_ENDS_MAX
  );

  let instanceId = null;
  let conn = null;
  let watermark = 0;
  let ended = [];
  const endedSet = new Set();
  let activities = new Map();
  let tiles = new Map();
  let notices = new Map();
  let phase = "idle";
  let buffer = [];
  let liveHidden = false;
  let lastEnds = [];

  const listeners = new Set();

  function view() {
    return {
      phase,
      instanceId,
      conn,
      watermark,
      liveHidden,
      activities: sortObjects(Array.from(activities.values()), "activity_id"),
      tiles: sortObjects(Array.from(tiles.values()), "tile_id"),
      notices: sortObjects(Array.from(notices.values()), "notice_id"),
      ended: ended.slice().sort(compareIds),
      lastEnds: lastEnds
        .slice()
        .sort((left, right) => compareIds(left.activity_id, right.activity_id))
        .map(clone),
    };
  }

  function notify() {
    for (const listener of Array.from(listeners)) {
      listener(view());
    }
  }

  function runMutating(fn) {
    const before = JSON.stringify(view());
    const result = fn();
    const after = JSON.stringify(view());
    if (after !== before) {
      notify();
    }
    return result;
  }

  function trimEnded() {
    while (ended.length > endedMax) {
      const oldest = ended.shift();
      endedSet.delete(oldest);
    }
  }

  function addEnded(activityId) {
    if (activityId == null || endedSet.has(activityId)) {
      return;
    }
    endedSet.add(activityId);
    ended.push(activityId);
    trimEnded();
  }

  function mergeEnded(values) {
    for (const activityId of values) {
      addEnded(activityId);
    }
  }

  function removeEndedActivities() {
    for (const activityId of endedSet) {
      activities.delete(activityId);
    }
  }

  function rememberEnd(msg) {
    lastEnds.push({
      activity_id: msg.activity_id,
      end_reason: msg.end_reason,
      error: msg.error,
      summary_notice_id: msg.summary_notice_id,
    });
    if (lastEnds.length > lastEndsMax) {
      lastEnds.splice(0, lastEnds.length - lastEndsMax);
    }
  }

  function applyMessage(msg) {
    switch (msg.kind) {
      case "ui.activity": {
        const activity = msg.activity;
        if (activity && activity.activity_id != null) {
          if (!endedSet.has(activity.activity_id)) {
            activities.set(activity.activity_id, clone(activity));
          }
        }
        break;
      }
      case "ui.activity_end": {
        if (msg.activity_id != null) {
          addEnded(msg.activity_id);
          activities.delete(msg.activity_id);
        }
        rememberEnd(msg);
        break;
      }
      case "ui.tile": {
        const tile = msg.tile;
        if (tile && tile.tile_id != null) {
          tiles.set(tile.tile_id, clone(tile));
        }
        break;
      }
      case "ui.notice": {
        const notice = msg.notice;
        if (notice && notice.notice_id != null) {
          if (notice.dismissed) {
            notices.delete(notice.notice_id);
          } else {
            notices.set(notice.notice_id, clone(notice));
          }
        }
        break;
      }
      case "ui.notice_dismiss": {
        if (msg.notice_id != null) {
          notices.delete(msg.notice_id);
        }
        break;
      }
      default:
        break;
    }
  }

  function drainBuffer() {
    buffer.sort((left, right) => {
      const a = toSequence(left && left.ui_seq);
      const b = toSequence(right && right.ui_seq);
      if (Number.isNaN(a) && Number.isNaN(b)) {
        return 0;
      }
      if (Number.isNaN(a)) {
        return 1;
      }
      if (Number.isNaN(b)) {
        return -1;
      }
      return a - b;
    });

    while (buffer.length > 0) {
      const next = buffer[0];
      const seq = toSequence(next && next.ui_seq);
      if (Number.isNaN(seq) || seq <= watermark) {
        buffer.shift();
        continue;
      }
      if (seq !== watermark + 1) {
        phase = "syncing";
        return true;
      }
      buffer.shift();
      applyMessage(next);
      watermark = seq;
    }

    phase = "live";
    return false;
  }

  function handleHello(msg) {
    if (!msg || msg.conn == null || msg.kind === "ui.closed") {
      if (phase !== "exited") {
        phase = "exited";
      }
      return { needSnapshot: false };
    }

    if (msg.instance_id !== instanceId) {
      instanceId = msg.instance_id;
      activities = new Map();
      tiles = new Map();
      notices = new Map();
      ended = [];
      endedSet.clear();
      lastEnds = [];
    }

    conn = msg.conn;
    watermark = sequenceOrZero(msg.ui_seq);
    buffer = [];
    phase = "syncing";
    liveHidden = false;
    return { needSnapshot: true };
  }

  function handleMessage(msg) {
    if (!msg || msg.conn !== conn) {
      return { needSnapshot: false };
    }
    if (phase === "exited" || phase === "forbidden") {
      return { needSnapshot: false };
    }

    if (msg.kind === "ui.heartbeat") {
      if (toSequence(msg.ui_seq) > watermark) {
        phase = "syncing";
        return { needSnapshot: true };
      }
      return { needSnapshot: false };
    }

    if (msg.kind === "ui.bye") {
      phase = "exited";
      return { needSnapshot: false };
    }

    if (phase === "syncing") {
      // 没有有效流水号的残缺帧直接丢，免得缓冲里永远续不上
      if (!Number.isNaN(toSequence(msg.ui_seq))) {
        buffer.push(msg);
      }
      return { needSnapshot: false };
    }

    if (phase !== "live") {
      return { needSnapshot: false };
    }

    const seq = toSequence(msg.ui_seq);
    if (Number.isNaN(seq) || seq <= watermark) {
      return { needSnapshot: false };
    }
    if (seq === watermark + 1) {
      applyMessage(msg);
      watermark = seq;
      return { needSnapshot: false };
    }

    buffer.push(msg);
    phase = "syncing";
    return { needSnapshot: true };
  }

  function handleSnapshot(snap) {
    // 断开 / 退出 / 被拒之后才回来的全家福不采用：否则会把「连接中断」覆盖成 live
    if (phase !== "syncing" && phase !== "live") {
      return { adopted: false };
    }
    if (
      !snap ||
      snap.conn !== conn ||
      snap.instance_id !== instanceId
    ) {
      return { adopted: false };
    }
    const snapSeq = toSequence(snap.ui_seq);
    if (Number.isNaN(snapSeq) || snapSeq < watermark) {
      return { adopted: false };
    }

    const nextActivities = new Map();
    for (const activity of Array.isArray(snap.activities)
      ? snap.activities
      : []) {
      if (activity && activity.activity_id != null) {
        nextActivities.set(activity.activity_id, clone(activity));
      }
    }

    const nextTiles = new Map();
    for (const tile of Array.isArray(snap.tiles) ? snap.tiles : []) {
      if (tile && tile.tile_id != null) {
        nextTiles.set(tile.tile_id, clone(tile));
      }
    }

    const nextNotices = new Map();
    for (const notice of Array.isArray(snap.notices) ? snap.notices : []) {
      if (notice && notice.notice_id != null && !notice.dismissed) {
        nextNotices.set(notice.notice_id, clone(notice));
      }
    }

    activities = nextActivities;
    tiles = nextTiles;
    notices = nextNotices;
    mergeEnded(Array.isArray(snap.ended) ? snap.ended : []);
    removeEndedActivities();

    watermark = snapSeq;
    phase = "syncing";
    const needSnapshot = drainBuffer();
    return { adopted: true, needSnapshot };
  }

  function handleDisconnect() {
    if (phase === "exited" || phase === "forbidden") {
      return { needSnapshot: false };
    }
    phase = "disconnected";
    return { needSnapshot: false };
  }

  function handleForbidden() {
    activities = new Map();
    tiles = new Map();
    notices = new Map();
    phase = "forbidden";
    return { needSnapshot: false };
  }

  function handleClosed() {
    phase = "exited";
    return { needSnapshot: false };
  }

  function handleHideLive() {
    if (phase === "disconnected") {
      liveHidden = true;
    }
    return { needSnapshot: false };
  }

  function subscribe(listener) {
    if (typeof listener !== "function") {
      throw new TypeError("listener 必须是函数");
    }
    listeners.add(listener);
    return function unsubscribe() {
      listeners.delete(listener);
    };
  }

  return {
    onHello(msg) {
      return runMutating(() => handleHello(msg));
    },
    onMessage(msg) {
      return runMutating(() => handleMessage(msg));
    },
    onSnapshot(snap) {
      return runMutating(() => handleSnapshot(snap));
    },
    onDisconnect() {
      return runMutating(handleDisconnect);
    },
    onForbidden() {
      return runMutating(handleForbidden);
    },
    onClosed() {
      return runMutating(handleClosed);
    },
    hideLive() {
      return runMutating(handleHideLive);
    },
    subscribe,
    view,
  };
}
