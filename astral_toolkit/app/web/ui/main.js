"use strict";

import { createUiStore } from "./store.js";
import { connectUi } from "./conn.js";

const store = createUiStore();
window.atUi = store;

function publish(view) {
  document.documentElement.dataset.uiConn = view.phase;
  window.dispatchEvent(new CustomEvent("at:ui", { detail: view }));
}

document.documentElement.dataset.uiConn = store.view().phase;
store.subscribe(publish);

try {
  const token = sessionStorage.getItem("t");
  if (token) {
    connectUi({
      token,
      EventSourceImpl: window.EventSource,
      fetchImpl: (url) => window.fetch(url),
      setTimeoutImpl: (fn, ms) => window.setTimeout(fn, ms),
      clearTimeoutImpl: (timer) => window.clearTimeout(timer),
      store,
    });
  }
} catch (error) {
  // 读不到口令就不连
}
