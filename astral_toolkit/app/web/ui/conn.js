"use strict";

export function connectUi({
  token,
  EventSourceImpl,
  fetchImpl,
  setTimeoutImpl,
  clearTimeoutImpl,
  store,
  hideAfterMs = 10000,
}) {
  let closed = false;
  let stopped = false;
  let sourceClosed = false;
  let hideTimer = null;
  let snapshotRetryTimer = null;
  let snapshotInFlight = false;
  let snapshotAgain = false;
  // 代际：每次新 hello / 出错 +1；之前发出的全家福请求、探测回来时代际不对就作废
  let gen = 0;

  const tokenPart = encodeURIComponent(token);
  const eventUrl = "/api/ui/events?t=" + tokenPart;
  const probeUrl = "/api/ui/snapshot?t=" + tokenPart + "&conn=0";
  const es = new EventSourceImpl(eventUrl);

  function currentView() {
    return store.view();
  }

  function currentConn() {
    const view = currentView();
    return view && view.conn != null ? view.conn : null;
  }

  function snapshotUrl() {
    const conn = currentConn();
    const text = conn == null ? "0" : String(conn);
    return "/api/ui/snapshot?t=" + tokenPart + "&conn=" + encodeURIComponent(text);
  }

  function closeSource() {
    if (sourceClosed) {
      return;
    }
    sourceClosed = true;
    if (es && typeof es.close === "function") {
      es.close();
    }
  }

  function clearHideTimer() {
    if (hideTimer !== null) {
      clearTimeoutImpl(hideTimer);
      hideTimer = null;
    }
  }

  function clearSnapshotRetry() {
    if (snapshotRetryTimer !== null) {
      clearTimeoutImpl(snapshotRetryTimer);
      snapshotRetryTimer = null;
    }
  }

  function terminate() {
    stopped = true;
    snapshotAgain = false;
    clearHideTimer();
    clearSnapshotRetry();
    closeSource();
  }

  function scheduleSnapshotRetry() {
    if (closed || stopped || snapshotRetryTimer !== null) {
      return;
    }
    snapshotRetryTimer = setTimeoutImpl(() => {
      snapshotRetryTimer = null;
      if (!closed && !stopped) {
        void requestSnapshotNow();
      }
    }, 1000);
  }

  async function requestSnapshotNow() {
    if (closed || stopped) {
      return;
    }
    snapshotInFlight = true;
    const myGen = gen;
    try {
      const response = await fetchImpl(snapshotUrl());
      if (closed || stopped || myGen !== gen) {
        return;
      }
      if (
        !response ||
        response.ok === false ||
        (response.status !== undefined && Number(response.status) !== 200)
      ) {
        throw new Error("snapshot failed");
      }
      const snap =
        typeof response.json === "function"
          ? await response.json()
          : response;
      if (closed || stopped || myGen !== gen) {
        return;
      }
      const result = store.onSnapshot(snap);
      snapshotInFlight = false;
      // 没被采用时只在仍在等全家福（syncing）时再要，断开期间不空转
      const again =
        snapshotAgain ||
        Boolean(
          result &&
            (result.needSnapshot ||
              (result.adopted === false && currentView().phase === "syncing"))
        );
      snapshotAgain = false;
      if (again && !closed && !stopped) {
        requestSnapshot();
      }
    } catch (error) {
      if (closed || stopped || myGen !== gen) {
        return;
      }
      snapshotInFlight = false;
      snapshotAgain = false;
      scheduleSnapshotRetry();
    }
  }

  function requestSnapshot() {
    if (closed || stopped) {
      return;
    }
    if (snapshotRetryTimer !== null) {
      clearSnapshotRetry();
    }
    if (snapshotInFlight) {
      snapshotAgain = true;
      return;
    }
    void requestSnapshotNow();
  }

  function startHideTimer() {
    if (hideTimer !== null || closed || stopped) {
      return;
    }
    hideTimer = setTimeoutImpl(() => {
      hideTimer = null;
      if (!closed && !stopped) {
        store.hideLive();
      }
    }, hideAfterMs);
  }

  async function probeCloseReason() {
    const myGen = gen;
    let response;
    try {
      response = await fetchImpl(probeUrl);
    } catch (error) {
      return;
    }
    // 探测期间已经重连（来过新 hello）：旧探测结果不算数
    if (closed || stopped || myGen !== gen) {
      return;
    }
    const status = response ? Number(response.status) : NaN;
    if (status === 403) {
      store.onForbidden();
      terminate();
      return;
    }
    if (status === 503) {
      store.onClosed();
      terminate();
    }
  }

  function handleEvent(event) {
    if (closed || stopped) {
      return;
    }

    let msg;
    try {
      const data =
        event && Object.prototype.hasOwnProperty.call(event, "data")
          ? event.data
          : event;
      msg = typeof data === "string" ? JSON.parse(data) : data;
    } catch (error) {
      return;
    }
    if (!msg || typeof msg !== "object") {
      return;
    }

    if (msg.kind === "ui.hello") {
      clearHideTimer();
      clearSnapshotRetry();
      // 新连接：旧连接在途的全家福请求作废，不能挡住新连接要全家福
      gen += 1;
      snapshotInFlight = false;
      snapshotAgain = false;
      const result = store.onHello(msg);
      if (result && result.needSnapshot) {
        requestSnapshot();
      }
      return;
    }
    if (msg.kind === "ui.closed") {
      store.onHello(msg);
      terminate();
      return;
    }

    const result = store.onMessage(msg);
    if (msg.kind === "ui.bye") {
      terminate();
      return;
    }
    if (result && result.needSnapshot) {
      requestSnapshot();
    }
  }

  function handleError() {
    if (closed || stopped) {
      return;
    }
    const view = currentView();
    const phase = view && view.phase;
    if (phase === "exited" || phase === "forbidden") {
      terminate();
      return;
    }

    gen += 1;
    snapshotInFlight = false;
    snapshotAgain = false;
    clearSnapshotRetry();
    store.onDisconnect();
    startHideTimer();
    void probeCloseReason();
  }

  es.onmessage = handleEvent;
  es.onerror = handleError;

  function close() {
    if (closed) {
      return;
    }
    closed = true;
    snapshotAgain = false;
    clearHideTimer();
    clearSnapshotRetry();
    closeSource();
  }

  return { close };
}
