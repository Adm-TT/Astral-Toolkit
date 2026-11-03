import test from "node:test";
import assert from "node:assert/strict";

import { createUiStore } from "../../astral_toolkit/app/web/ui/store.js";
import { connectUi } from "../../astral_toolkit/app/web/ui/conn.js";

function snapshot(conn, instance, seq, data = {}) {
  return {
    protocol: "ui/1",
    instance_id: instance,
    conn,
    ui_seq: seq,
    activities: [],
    tiles: [],
    notices: [],
    ended: [],
    ...data,
  };
}

function liveStore({ instance = "i-1", conn = 1, seq = 0 } = {}) {
  const store = createUiStore();
  const helloResult = store.onHello({
    kind: "ui.hello",
    protocol: "ui/1",
    instance_id: instance,
    conn,
    ui_seq: seq,
  });
  assert.deepEqual(helloResult, { needSnapshot: true });
  const snapResult = store.onSnapshot(snapshot(conn, instance, seq));
  assert.deepEqual(snapResult, { adopted: true, needSnapshot: false });
  return store;
}

test("store 采用全家福并排序、过滤已结束活动", () => {
  const store = createUiStore();
  assert.equal(store.view().phase, "idle");

  const result = store.onHello({
    kind: "ui.hello",
    protocol: "ui/1",
    instance_id: "i-1",
    conn: 1,
    ui_seq: 0,
  });
  assert.deepEqual(result, { needSnapshot: true });
  assert.equal(store.view().phase, "syncing");

  const adopted = store.onSnapshot(
    snapshot(1, "i-1", 0, {
      activities: [
        { activity_id: "b", title: "B" },
        { activity_id: "a", title: "A" },
        { activity_id: "dead", title: "D" },
      ],
      tiles: [{ tile_id: "tile-2" }, { tile_id: "tile-1" }],
      notices: [
        { notice_id: "notice-2", dismissed: false },
        { notice_id: "notice-1", dismissed: false },
        { notice_id: "hidden", dismissed: true },
      ],
      ended: ["dead"],
    })
  );
  assert.deepEqual(adopted, { adopted: true, needSnapshot: false });

  const view = store.view();
  assert.equal(view.phase, "live");
  assert.equal(view.instanceId, "i-1");
  assert.equal(view.conn, 1);
  assert.equal(view.watermark, 0);
  assert.equal(view.liveHidden, false);
  assert.deepEqual(
    view.activities.map((item) => item.activity_id),
    ["a", "b"]
  );
  assert.deepEqual(
    view.tiles.map((item) => item.tile_id),
    ["tile-1", "tile-2"]
  );
  assert.deepEqual(
    view.notices.map((item) => item.notice_id),
    ["notice-1", "notice-2"]
  );
  assert.deepEqual(view.ended, ["dead"]);
});

test("store 应用活动、磁贴、通知、终态和未知消息", () => {
  const store = liveStore();

  let result = store.onMessage({
    kind: "ui.activity",
    conn: 1,
    ui_seq: 1,
    activity: { activity_id: "a", title: "A" },
  });
  assert.deepEqual(result, { needSnapshot: false });

  store.onMessage({
    kind: "ui.activity",
    conn: 1,
    ui_seq: 2,
    activity: { activity_id: "b", title: "B" },
  });
  store.onMessage({
    kind: "ui.tile",
    conn: 1,
    ui_seq: 3,
    tile: { tile_id: "t1", on: true },
  });
  store.onMessage({
    kind: "ui.notice",
    conn: 1,
    ui_seq: 4,
    notice: { notice_id: "n1", dismissed: false },
  });
  store.onMessage({
    kind: "ui.notice",
    conn: 1,
    ui_seq: 5,
    notice: { notice_id: "n1", dismissed: true },
  });
  store.onMessage({
    kind: "ui.notice",
    conn: 1,
    ui_seq: 6,
    notice: { notice_id: "n2", dismissed: false },
  });
  store.onMessage({
    kind: "ui.notice_dismiss",
    conn: 1,
    ui_seq: 7,
    notice_id: "n2",
  });
  store.onMessage({
    kind: "ui.activity_end",
    conn: 1,
    ui_seq: 8,
    activity_id: "a",
    end_reason: "done",
    summary_notice_id: "summary:a",
  });
  result = store.onMessage({
    kind: "ui.activity",
    conn: 1,
    ui_seq: 9,
    activity: { activity_id: "a", title: "复活" },
  });
  assert.deepEqual(result, { needSnapshot: false });
  store.onMessage({
    kind: "ui.future",
    conn: 1,
    ui_seq: 10,
  });

  result = store.onMessage({
    kind: "ui.activity",
    conn: 99,
    ui_seq: 11,
    activity: { activity_id: "wrong-conn" },
  });
  assert.deepEqual(result, { needSnapshot: false });

  const view = store.view();
  assert.equal(view.phase, "live");
  assert.equal(view.watermark, 10);
  assert.deepEqual(
    view.activities.map((item) => item.activity_id),
    ["b"]
  );
  assert.deepEqual(
    view.tiles.map((item) => item.tile_id),
    ["t1"]
  );
  assert.deepEqual(view.notices, []);
  assert.deepEqual(view.ended, ["a"]);
  assert.equal(view.lastEnds.length, 1);
  assert.equal(view.lastEnds[0].activity_id, "a");
  assert.equal(view.lastEnds[0].end_reason, "done");
  assert.equal(view.lastEnds[0].summary_notice_id, "summary:a");
});

test("store 在跳号后缓冲，并可按全家福续上", () => {
  const store = liveStore({ seq: 2 });

  let result = store.onMessage({
    kind: "ui.tile",
    conn: 1,
    ui_seq: 5,
    tile: { tile_id: "t5" },
  });
  assert.deepEqual(result, { needSnapshot: true });
  assert.equal(store.view().phase, "syncing");

  store.onMessage({
    kind: "ui.activity",
    conn: 1,
    ui_seq: 4,
    activity: { activity_id: "b4" },
  });

  result = store.onSnapshot(
    snapshot(1, "i-1", 3, {
      activities: [{ activity_id: "a3" }],
    })
  );
  assert.deepEqual(result, { adopted: true, needSnapshot: false });

  let view = store.view();
  assert.equal(view.phase, "live");
  assert.equal(view.watermark, 5);
  assert.deepEqual(
    view.activities.map((item) => item.activity_id),
    ["a3", "b4"]
  );
  assert.deepEqual(
    view.tiles.map((item) => item.tile_id),
    ["t5"]
  );

  result = store.onMessage({
    kind: "ui.notice",
    conn: 1,
    ui_seq: 7,
    notice: { notice_id: "n7", dismissed: false },
  });
  assert.deepEqual(result, { needSnapshot: true });

  const stable = {
    activities: [{ activity_id: "a3" }, { activity_id: "b4" }],
    tiles: [{ tile_id: "t5" }],
  };
  result = store.onSnapshot(snapshot(1, "i-1", 5, stable));
  assert.deepEqual(result, { adopted: true, needSnapshot: true });
  assert.equal(store.view().phase, "syncing");

  result = store.onSnapshot(
    snapshot(1, "i-1", 7, {
      ...stable,
      notices: [{ notice_id: "n7", dismissed: false }],
    })
  );
  assert.deepEqual(result, { adopted: true, needSnapshot: false });

  view = store.view();
  assert.equal(view.phase, "live");
  assert.equal(view.watermark, 7);
  assert.deepEqual(
    view.notices.map((item) => item.notice_id),
    ["n7"]
  );
});

test("store 拒绝旧全家福和不匹配的全家福", () => {
  const store = liveStore();
  store.onMessage({
    kind: "ui.activity",
    conn: 1,
    ui_seq: 1,
    activity: { activity_id: "keep" },
  });

  let result = store.onSnapshot(
    snapshot(1, "i-1", 0, {
      activities: [{ activity_id: "old" }],
    })
  );
  assert.deepEqual(result, { adopted: false });

  result = store.onSnapshot(snapshot(2, "i-1", 2));
  assert.deepEqual(result, { adopted: false });

  result = store.onSnapshot(snapshot(1, "i-2", 2));
  assert.deepEqual(result, { adopted: false });

  const view = store.view();
  assert.equal(view.phase, "live");
  assert.equal(view.watermark, 1);
  assert.deepEqual(
    view.activities.map((item) => item.activity_id),
    ["keep"]
  );
});

test("store 重连保留同实例数据，换实例清空", () => {
  const store = liveStore();
  store.onMessage({
    kind: "ui.activity",
    conn: 1,
    ui_seq: 1,
    activity: { activity_id: "ended:1" },
  });
  store.onMessage({
    kind: "ui.activity_end",
    conn: 1,
    ui_seq: 2,
    activity_id: "ended:1",
    end_reason: "done",
    summary_notice_id: "summary:ended:1",
  });
  store.onMessage({
    kind: "ui.tile",
    conn: 1,
    ui_seq: 3,
    tile: { tile_id: "t1" },
  });
  store.onMessage({
    kind: "ui.notice",
    conn: 1,
    ui_seq: 4,
    notice: { notice_id: "n1", dismissed: false },
  });

  assert.equal(store.onDisconnect().needSnapshot, false);
  assert.equal(store.view().phase, "disconnected");
  store.hideLive();
  assert.equal(store.view().liveHidden, true);

  const reconnect = store.onHello({
    kind: "ui.hello",
    protocol: "ui/1",
    instance_id: "i-1",
    conn: 2,
    ui_seq: 8,
  });
  assert.deepEqual(reconnect, { needSnapshot: true });

  let view = store.view();
  assert.equal(view.phase, "syncing");
  assert.equal(view.conn, 2);
  assert.equal(view.watermark, 8);
  assert.equal(view.liveHidden, false);
  assert.deepEqual(view.activities, []);
  assert.deepEqual(
    view.tiles.map((item) => item.tile_id),
    ["t1"]
  );
  assert.deepEqual(
    view.notices.map((item) => item.notice_id),
    ["n1"]
  );
  assert.deepEqual(view.ended, ["ended:1"]);
  assert.equal(view.lastEnds.length, 1);

  store.onHello({
    kind: "ui.hello",
    protocol: "ui/1",
    instance_id: "i-2",
    conn: 9,
    ui_seq: 1,
  });

  view = store.view();
  assert.equal(view.phase, "syncing");
  assert.equal(view.instanceId, "i-2");
  assert.equal(view.conn, 9);
  assert.equal(view.watermark, 1);
  assert.deepEqual(view.activities, []);
  assert.deepEqual(view.tiles, []);
  assert.deepEqual(view.notices, []);
  assert.deepEqual(view.ended, []);
  assert.deepEqual(view.lastEnds, []);
});

test("store 断连、403 与退出状态", () => {
  const store = liveStore();
  store.onMessage({
    kind: "ui.activity",
    conn: 1,
    ui_seq: 1,
    activity: { activity_id: "a" },
  });
  store.onMessage({
    kind: "ui.tile",
    conn: 1,
    ui_seq: 2,
    tile: { tile_id: "t" },
  });
  store.onMessage({
    kind: "ui.notice",
    conn: 1,
    ui_seq: 3,
    notice: { notice_id: "n", dismissed: false },
  });
  store.onMessage({
    kind: "ui.activity_end",
    conn: 1,
    ui_seq: 4,
    activity_id: "a",
    end_reason: "done",
    summary_notice_id: "summary:a",
  });
  store.onMessage({
    kind: "ui.activity",
    conn: 1,
    ui_seq: 5,
    activity: { activity_id: "b" },
  });

  store.onForbidden();
  let view = store.view();
  assert.equal(view.phase, "forbidden");
  assert.deepEqual(view.activities, []);
  assert.deepEqual(view.tiles, []);
  assert.deepEqual(view.notices, []);
  assert.deepEqual(view.ended, ["a"]);
  assert.equal(view.lastEnds.length, 1);

  store.onDisconnect();
  assert.equal(store.view().phase, "forbidden");
  store.hideLive();
  assert.equal(store.view().liveHidden, false);

  store.onClosed();
  view = store.view();
  assert.equal(view.phase, "exited");
});

function makeEventSourceFactory() {
  const instances = [];

  class FakeEventSource {
    constructor(url) {
      this.url = url;
      this.closed = false;
      this.closeCount = 0;
      this.onmessage = null;
      this.onerror = null;
      instances.push(this);
    }

    emit(value) {
      if (this.onmessage) {
        const data =
          typeof value === "string" ? value : JSON.stringify(value);
        this.onmessage({ data });
      }
    }

    fail() {
      if (this.onerror) {
        this.onerror({});
      }
    }

    close() {
      this.closed = true;
      this.closeCount += 1;
    }
  }

  return { EventSourceImpl: FakeEventSource, instances };
}

function makeTimers() {
  let nextId = 0;
  const timers = new Map();

  return {
    setTimeoutImpl(fn, ms) {
      nextId += 1;
      timers.set(nextId, { fn, ms });
      return nextId;
    },
    clearTimeoutImpl(timer) {
      timers.delete(timer);
    },
    count() {
      return timers.size;
    },
    advance(ms) {
      for (const [timer, item] of Array.from(timers.entries())) {
        if (item.ms <= ms) {
          timers.delete(timer);
          item.fn();
        }
      }
    },
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function snapshotResponse(snap) {
  return {
    ok: true,
    status: 200,
    json: async () => snap,
  };
}

async function settle() {
  await new Promise((resolve) => setImmediate(resolve));
}

test("conn 连接新流、拿全家福并应用增量", async () => {
  const store = createUiStore();
  const factory = makeEventSourceFactory();
  const timers = makeTimers();
  const calls = [];
  const deferreds = [];
  const fetchImpl = (url) => {
    calls.push(url);
    const item = deferred();
    deferreds.push(item);
    return item.promise;
  };

  const client = connectUi({
    token: "a b",
    EventSourceImpl: factory.EventSourceImpl,
    fetchImpl,
    setTimeoutImpl: timers.setTimeoutImpl,
    clearTimeoutImpl: timers.clearTimeoutImpl,
    store,
  });
  const es = factory.instances[0];
  assert.equal(es.url, "/api/ui/events?t=a%20b");

  es.emit({
    kind: "ui.hello",
    protocol: "ui/1",
    instance_id: "i-1",
    conn: 7,
    ui_seq: 0,
  });
  assert.equal(store.view().phase, "syncing");
  assert.equal(calls.length, 1);
  assert.equal(calls[0], "/api/ui/snapshot?t=a%20b&conn=7");

  deferreds[0].resolve(snapshotResponse(snapshot(7, "i-1", 0)));
  await settle();
  assert.equal(store.view().phase, "live");

  es.emit({
    kind: "ui.activity",
    conn: 7,
    ui_seq: 1,
    activity: { activity_id: "a" },
  });
  assert.equal(store.view().watermark, 1);
  assert.deepEqual(
    store.view().activities.map((item) => item.activity_id),
    ["a"]
  );

  client.close();
  assert.equal(es.closed, true);
  assert.equal(timers.count(), 0);
});

test("conn 同一时刻最多一个全家福请求，在途时记一次再拿", async () => {
  const store = createUiStore();
  const factory = makeEventSourceFactory();
  const timers = makeTimers();
  const calls = [];
  const deferreds = [];
  const fetchImpl = (url) => {
    calls.push(url);
    const item = deferred();
    deferreds.push(item);
    return item.promise;
  };

  const client = connectUi({
    token: "t",
    EventSourceImpl: factory.EventSourceImpl,
    fetchImpl,
    setTimeoutImpl: timers.setTimeoutImpl,
    clearTimeoutImpl: timers.clearTimeoutImpl,
    store,
  });
  const es = factory.instances[0];

  es.emit({
    kind: "ui.hello",
    protocol: "ui/1",
    instance_id: "i-1",
    conn: 1,
    ui_seq: 0,
  });
  assert.equal(calls.length, 1);

  es.emit({
    kind: "ui.heartbeat",
    conn: 1,
    ui_seq: 1,
  });
  assert.equal(calls.length, 1);

  deferreds[0].resolve(snapshotResponse(snapshot(1, "i-1", 0)));
  await settle();
  assert.equal(calls.length, 2);
  assert.equal(store.view().phase, "live");

  deferreds[1].resolve(snapshotResponse(snapshot(1, "i-1", 0)));
  await settle();
  assert.equal(calls.length, 2);

  client.close();
});

test("conn 出错后隐藏定时器、探测非 403/503 后继续重连", async () => {
  const store = createUiStore();
  const factory = makeEventSourceFactory();
  const timers = makeTimers();
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(url);
    if (url.includes("conn=0")) {
      return { ok: false, status: 500 };
    }
    const match = /conn=(\d+)/.exec(url);
    const conn = match ? Number(match[1]) : 0;
    return snapshotResponse(snapshot(conn, "i-1", 0));
  };

  const client = connectUi({
    token: "t",
    EventSourceImpl: factory.EventSourceImpl,
    fetchImpl,
    setTimeoutImpl: timers.setTimeoutImpl,
    clearTimeoutImpl: timers.clearTimeoutImpl,
    store,
    hideAfterMs: 50,
  });
  const es = factory.instances[0];

  es.emit({
    kind: "ui.hello",
    protocol: "ui/1",
    instance_id: "i-1",
    conn: 1,
    ui_seq: 0,
  });
  await settle();
  assert.equal(store.view().phase, "live");

  es.fail();
  await settle();
  assert.equal(store.view().phase, "disconnected");
  assert.equal(timers.count(), 1);

  es.emit({
    kind: "ui.hello",
    protocol: "ui/1",
    instance_id: "i-1",
    conn: 2,
    ui_seq: 0,
  });
  assert.equal(timers.count(), 0);
  await settle();
  assert.equal(store.view().phase, "live");

  es.fail();
  await settle();
  assert.equal(timers.count(), 1);
  timers.advance(50);
  assert.equal(store.view().phase, "disconnected");
  assert.equal(store.view().liveHidden, true);

  client.close();
  assert.equal(es.closed, true);
  assert.equal(timers.count(), 0);
});

test("conn 探测 403 进入 forbidden 并关闭连接", async () => {
  const store = createUiStore();
  const factory = makeEventSourceFactory();
  const timers = makeTimers();
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(url);
    return { ok: false, status: 403 };
  };

  const client = connectUi({
    token: "t",
    EventSourceImpl: factory.EventSourceImpl,
    fetchImpl,
    setTimeoutImpl: timers.setTimeoutImpl,
    clearTimeoutImpl: timers.clearTimeoutImpl,
    store,
  });
  const es = factory.instances[0];

  es.fail();
  await settle();

  assert.equal(store.view().phase, "forbidden");
  assert.deepEqual(calls, ["/api/ui/snapshot?t=t&conn=0"]);
  assert.equal(es.closed, true);
  client.close();
});

test("conn 探测 503 当退出并关闭连接", async () => {
  const store = createUiStore();
  const factory = makeEventSourceFactory();
  const timers = makeTimers();
  const fetchImpl = async () => ({ ok: false, status: 503 });

  const client = connectUi({
    token: "t",
    EventSourceImpl: factory.EventSourceImpl,
    fetchImpl,
    setTimeoutImpl: timers.setTimeoutImpl,
    clearTimeoutImpl: timers.clearTimeoutImpl,
    store,
  });
  const es = factory.instances[0];

  es.fail();
  await settle();

  assert.equal(store.view().phase, "exited");
  assert.equal(es.closed, true);
  client.close();
});

test("conn 收到 bye 立即关闭，不再探测", async () => {
  const store = createUiStore();
  const factory = makeEventSourceFactory();
  const timers = makeTimers();
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(url);
    return snapshotResponse(snapshot(1, "i-1", 0));
  };

  const client = connectUi({
    token: "t",
    EventSourceImpl: factory.EventSourceImpl,
    fetchImpl,
    setTimeoutImpl: timers.setTimeoutImpl,
    clearTimeoutImpl: timers.clearTimeoutImpl,
    store,
  });
  const es = factory.instances[0];

  es.emit({
    kind: "ui.hello",
    protocol: "ui/1",
    instance_id: "i-1",
    conn: 1,
    ui_seq: 0,
  });
  await settle();
  const before = calls.length;

  es.emit({
    kind: "ui.bye",
    conn: 1,
    ui_seq: 9,
  });
  assert.equal(store.view().phase, "exited");
  assert.equal(es.closed, true);

  es.fail();
  await settle();
  assert.equal(calls.length, before);
  client.close();
});

test("conn.close 后到达的全家福和消息全部忽略", async () => {
  const store = createUiStore();
  const factory = makeEventSourceFactory();
  const timers = makeTimers();
  const item = deferred();
  const fetchImpl = () => item.promise;

  const client = connectUi({
    token: "t",
    EventSourceImpl: factory.EventSourceImpl,
    fetchImpl,
    setTimeoutImpl: timers.setTimeoutImpl,
    clearTimeoutImpl: timers.clearTimeoutImpl,
    store,
  });
  const es = factory.instances[0];

  es.emit({
    kind: "ui.hello",
    protocol: "ui/1",
    instance_id: "i-1",
    conn: 1,
    ui_seq: 0,
  });
  client.close();
  assert.equal(es.closed, true);

  item.resolve(snapshotResponse(snapshot(1, "i-1", 0)));
  await settle();
  es.emit({
    kind: "ui.activity",
    conn: 1,
    ui_seq: 1,
    activity: { activity_id: "late" },
  });

  assert.equal(store.view().phase, "syncing");
  assert.equal(store.view().watermark, 0);
  assert.deepEqual(store.view().activities, []);
});

test("store 断开后才回来的全家福不采用，仍是连接中断", () => {
  const store = createUiStore();
  store.onHello({ kind: "ui.hello", instance_id: "i1", conn: 1, ui_seq: 5 });
  store.onDisconnect();
  const result = store.onSnapshot({
    instance_id: "i1",
    conn: 1,
    ui_seq: 6,
    activities: [{ activity_id: "x" }],
    tiles: [],
    notices: [],
    ended: [],
  });
  assert.equal(result.adopted, false);
  assert.equal(store.view().phase, "disconnected");
  assert.deepEqual(store.view().activities, []);
  store.hideLive();
  assert.equal(store.view().liveHidden, true);
});
test("conn 旧连接的全家福挂住时，新 hello 照样要新全家福；旧探测迟到不算数", async () => {
  const store = createUiStore();
  const factory = makeEventSourceFactory();
  const timers = makeTimers();
  const calls = [];
  const deferreds = [];
  const fetchImpl = (url) => {
    calls.push(url);
    const item = deferred();
    deferreds.push(item);
    return item.promise;
  };
  const client = connectUi({
    token: "t",
    EventSourceImpl: factory.EventSourceImpl,
    fetchImpl,
    setTimeoutImpl: timers.setTimeoutImpl,
    clearTimeoutImpl: timers.clearTimeoutImpl,
    store,
  });
  const es = factory.instances[0];
  es.emit({ kind: "ui.hello", protocol: "ui/1", instance_id: "i-1", conn: 1, ui_seq: 0 });
  assert.equal(calls.length, 1, "conn=1 的全家福在途");
  es.fail(); // 出错：会发一次探测（calls[1]）
  assert.equal(calls.length, 2);
  es.emit({ kind: "ui.hello", protocol: "ui/1", instance_id: "i-1", conn: 2, ui_seq: 3 });
  assert.equal(calls.length, 3, "新连接立刻要全家福，不被挂住的旧请求挡住");
  assert.match(calls[2], /conn=2$/);
  deferreds[1].resolve({ ok: false, status: 503 }); // 旧探测迟到
  deferreds[0].resolve(snapshotResponse(snapshot(1, "i-1", 0))); // 旧全家福迟到
  await settle();
  assert.equal(store.view().phase, "syncing");
  assert.equal(es.closed, false);
  deferreds[2].resolve(snapshotResponse(snapshot(2, "i-1", 3)));
  await settle();
  assert.equal(store.view().phase, "live");
  assert.equal(store.view().conn, 2);
  client.close();
});

test("store 缺流水号的残缺帧在缓冲里直接丢，不会永远要全家福", () => {
  const store = createUiStore();
  store.onHello({ kind: "ui.hello", instance_id: "i1", conn: 1, ui_seq: 0 });
  store.onMessage({ kind: "ui.activity", conn: 1, activity: { activity_id: "bad" } });
  store.onMessage({ kind: "ui.activity", conn: 1, ui_seq: 1, activity: { activity_id: "a" } });
  const result = store.onSnapshot(snapshot(1, "i1", 0));
  assert.deepEqual(result, { adopted: true, needSnapshot: false });
  assert.equal(store.view().phase, "live");
  assert.deepEqual(store.view().activities.map((a) => a.activity_id), ["a"]);
});