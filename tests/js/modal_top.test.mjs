import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../../astral_toolkit/app/web/app.js", import.meta.url), "utf8");
// 执行产品函数，DOM 替身仅提供元素、选择器和事件边界；不启动服务或读取玩家配置。
class Element extends EventTarget {
  constructor() {
    super();
    this.dataset = {};
    this.classes = new Set();
    this.classList = { add: (c) => this.classes.add(c), remove: (c) => this.classes.delete(c) };
    this.children = [];
    this.nodes = new Map();
    this.removed = false;
  }
  set innerHTML(html) {
    this.html = html;
    this.nodes.clear();
    for (const [, attrs] of html.matchAll(/<[\w-]+\b([^>]*)>/g)) {
      const id = /\bid="([^"]+)"/.exec(attrs)?.[1];
      if (!id) continue;
      const el = new Element();
      Object.assign(el, { attrs, parentNode: this });
      this.nodes.set(`#${id}`, el);
    }
    if (html.includes('class="modal-card')) this.nodes.set(".modal-card", new Element());
    this.closeButtons = [...html.matchAll(/data-close/g)].map(() => new Element());
  }
  get innerHTML() { return this.html; }
  // 只认 [属性] 这一种写法：顺着替身的父节点找带这个属性的
  closest(selector) {
    const attr = /^\[([\w-]+)\]$/.exec(selector)?.[1];
    for (let el = this; attr && el; el = el.parentNode) if (new RegExp(`(^|\\s)${attr}(=|\\s|$)`).test(el.attrs || "")) return el;
    return null;
  }
  querySelector(selector) { return this.nodes.get(selector) || null; }
  querySelectorAll(selector) { return selector === "[data-close]" ? this.closeButtons : []; }
  appendChild(el) { this.children.push(el); return el; }
  remove() { this.removed = true; }
}

function harness() {
  const document = new Element();
  document.body = new Element();
  document.documentElement = new Element();
  document.createElement = () => new Element();
  const ids = new Map(["hk", "where", "banner", "pip-live", "pip-nav", "brandmark"].map((id) => [`#${id}`, new Element()]));
  document.getElementById = (id) => ids.get(`#${id}`);
  document.querySelector = (selector) => ids.get(selector) || document.body.children.at(-1)?.querySelector(selector);
  const keys = new Set();
  const add = document.addEventListener.bind(document), remove = document.removeEventListener.bind(document);
  document.addEventListener = (name, fn, ...args) => { if (name === "keydown") keys.add(fn); add(name, fn, ...args); };
  document.removeEventListener = (name, fn, ...args) => { if (name === "keydown") keys.delete(fn); remove(name, fn, ...args); };
  let writes = 0, messages = 0;
  const window = new EventTarget();
  window.chrome = { webview: { postMessage() { messages++; } } };
  const context = vm.createContext({
    document, window, localStorage: { getItem: () => "dark", setItem() { writes++; } },
    state: { status: null }, esc: String, $: (s) => document.querySelector(s),
    setTimeout: () => 0, clearTimeout: () => {},
    requestAnimationFrame: (fn) => fn(), disclaimerHTML: async () => "<p>说明</p>",
  });
  const blocks = [
    source.slice(source.indexOf("function applyTheme("), source.indexOf("async function refreshStatus(")),
    source.slice(source.indexOf("const MODALS = [];"), source.indexOf("const placeNorm =")),
    source.slice(source.indexOf("async function showDisclaimer("), source.indexOf("(async function init()")),
  ];
  vm.runInContext(blocks.join("\n"), context);
  return { context, document, keys, evaluate: (s) => vm.runInContext(s, context), counts: () => ({ writes, messages }) };
}

function send(el, name, props = {}) {
  const event = new Event(name, { cancelable: true });
  for (const [key, value] of Object.entries(props)) Object.defineProperty(event, key, { value });
  el.dispatchEvent(event);
  return event;
}

test("填过内容的弹窗点外面不关（卡片跳一下），关闭和取消照旧能关", () => {
  const h = harness();
  const cases = [
    ['<input id="value">', "input"],
    ['<select id="value"></select>', "change"],
    ['<textarea id="value"></textarea>', "input"],
    ['<x-seg id="value"></x-seg>', "change"],                           // 分段选择只发 change
    ['<button class="place-pick" id="value"></button>', "placechange"], // 选地点按钮换了地点
  ];
  for (const [body, name] of cases) {
    const md = h.evaluate(`openModal({ title: "编辑", body: ${JSON.stringify(body)}, foot: '<button data-close>取消</button>' })`);
    md.q("#value").value = "未保存内容";
    send(md.el, name, { target: md.q("#value") });
    const down = send(md.el, "mousedown");
    assert.equal(md.el.removed, false, body);
    assert.ok(down.defaultPrevented, body);                         // 输入框不失焦
    assert.ok(md.q(".modal-card").classes.has("nudge"), body);
    assert.ok(md.el.closeButtons.every((b) => b.classes.has("hint")), body);   // 关了动画也看得到
    md.el.closeButtons[1].onclick();
    assert.equal(md.el.removed, true);
  }
});

test("真弹窗里的标记都在：搜索框带 data-filter，分段选择和换地点的事件会冒泡到弹窗，带进来的数量算填过", () => {
  assert.match(source, /id="pp-q" data-filter/);                                    // 选存放地点的搜索框
  assert.match(source, /placeholder="搜索地点" aria-label="搜索地点" data-filter/);  // 库存页地点菜单的搜索框
  assert.match(source, /if \(!e\.target\.closest\?\.\("\[data-filter\]"\)\) p\.dirty = true;/);   // 小表单也认 data-filter
  assert.match(source, /this\.dispatchEvent\(new Event\("change", \{ bubbles: true \}\)\)/);   // x-seg
  assert.match(source, /new CustomEvent\("placechange", \{ bubbles: true/);
  assert.match(source, /if \(\(pre\.qty \?\? ""\) !== "" \|\| \(pre\.quality \?\? ""\) !== ""\) md\.dirty = true;/);
});

test("没填过的弹窗、只在搜索框里打过字的，点外面照旧关", () => {
  const h = harness();
  const blank = h.evaluate(`openModal({ title: "入库", body: '<input id="value" value="带进来的">' })`);
  send(blank.el, "mousedown");
  assert.equal(blank.el.removed, true);
  const pick = h.evaluate(`openModal({ title: "选择存放地点", body: '<input id="q" data-filter><input id="name">' })`);
  send(pick.el, "input", { target: pick.q("#q") });
  send(pick.el, "change", { target: pick.q("#q") });
  send(pick.el, "mousedown");
  assert.equal(pick.el.removed, true);
  const named = h.evaluate(`openModal({ title: "选择存放地点", body: '<input id="q" data-filter><input id="name">' })`);
  send(named.el, "input", { target: named.q("#name") });
  send(named.el, "mousedown");
  assert.equal(named.el.removed, false);
});

test("查看弹窗可点遮罩关闭，卡片内点击不关；关闭回调只执行一次", () => {
  const h = harness();
  h.context.closed = 0;
  const md = h.evaluate('openModal({ title: "查看", body: "<p>说明</p>", onClose: () => closed++ })');
  send(md.el, "mousedown", { target: new Element() });
  assert.equal(md.el.removed, false);
  send(md.el, "mousedown");
  assert.equal(md.el.removed, true);
  md.close();
  assert.equal(h.context.closed, 1);
});

test("Esc 只关闭最上层弹窗，并尊重候选框已消费的 Esc", () => {
  const h = harness();
  const a = h.evaluate('openModal({ title: "底层", body: "<input>" })');
  const b = h.evaluate('openModal({ title: "上层", body: "<input>" })');
  send(h.document, "keydown", { key: "Escape", defaultPrevented: true });
  assert.equal(b.el.removed, false);
  send(h.document, "keydown", { key: "Escape" });
  assert.equal(b.el.removed, true);
  assert.equal(a.el.removed, false);
  a.el.closeButtons[0].onclick();
  assert.equal(a.el.removed, true);
});

test("免责声明每种关闭路径均清除自己的按键监听", async () => {
  const h = harness();
  const baseline = h.keys.size;
  for (const way of ["button", "outside", "escape", "button"]) {
    await h.evaluate("showDisclaimer()");
    const box = h.document.body.children.at(-1);
    assert.equal(h.keys.size, baseline + 1);
    if (way === "button") box.querySelector("#gate-close").onclick();
    else if (way === "outside") send(box, "click");
    else send(h.document, "keydown", { key: "Escape" });
    assert.equal(box.removed, true);
    assert.equal(h.keys.size, baseline);
  }
});

test("重复状态不会重复写主题或发外壳消息，切换主题仍立即生效", () => {
  const h = harness();
  h.evaluate('state.status = { settings: { theme: "dark" }, hover_key: "F8" }');
  const initial = h.counts();
  h.evaluate("renderTop(); renderTop(); renderTop()");
  assert.deepEqual(h.counts(), initial);
  assert.equal(h.document.querySelector("#hk").textContent, "F8");
  h.evaluate('state.status.settings.theme = "light"; renderTop(); renderTop()');
  assert.deepEqual(h.counts(), { writes: initial.writes + 1, messages: initial.messages + 1 });
  assert.equal(h.document.documentElement.dataset.theme, "light");
  h.evaluate('applyTheme("dark"); state.status.settings.theme = "dark"; renderTop()');
  assert.deepEqual(h.counts(), { writes: initial.writes + 2, messages: initial.messages + 2 });
  assert.equal(h.document.documentElement.dataset.theme, undefined);
});
