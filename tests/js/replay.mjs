import { readFileSync } from "node:fs";

import { createUiStore } from "../../astral_toolkit/app/web/ui/store.js";

const fixturePath = process.argv[2];
if (!fixturePath) {
  console.error("用法：node tests/js/replay.mjs <fixture.json>");
  process.exit(2);
}

const parsed = JSON.parse(readFileSync(fixturePath, "utf8"));
const steps = Array.isArray(parsed)
  ? parsed
  : parsed.steps ?? parsed.events ?? parsed.ops;
if (!Array.isArray(steps)) {
  throw new Error("夹具需要是数组，或带 steps/events/ops 数组");
}

const store = createUiStore();

for (const step of steps) {
  if (!step || typeof step !== "object") {
    throw new Error("夹具步骤必须是对象");
  }

  let method = step.method ?? step.op ?? step.type;
  if (!method && step.kind) {
    if (step.kind === "ui.hello" || step.kind === "ui.closed") {
      method = "onHello";
    } else if (step.kind === "ui.snapshot") {
      method = "onSnapshot";
    } else {
      method = "onMessage";
    }
  }
  const normalized = String(method ?? "").toLowerCase();

  switch (normalized) {
    case "onhello":
    case "hello":
      store.onHello(step.msg ?? step.message ?? step);
      break;
    case "onmessage":
    case "message":
      store.onMessage(step.msg ?? step.message ?? step);
      break;
    case "onsnapshot":
    case "snapshot":
      store.onSnapshot(step.snap ?? step.snapshot ?? step);
      break;
    case "ondisconnect":
    case "disconnect":
      store.onDisconnect();
      break;
    case "onforbidden":
    case "forbidden":
      store.onForbidden();
      break;
    case "onclosed":
    case "closed":
      store.onClosed();
      break;
    case "hidelive":
    case "hide":
      store.hideLive();
      break;
    default:
      throw new Error(`不认识的夹具步骤：${normalized}`);
  }
}

process.stdout.write(JSON.stringify(store.view()) + "\n");
