"use strict";
// 天枢窗口：所有功能都通过 /api/<名字> 调用 Python；实时结果从 /api/events 推过来

const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (v) => (v == null || v === "" ? "—" : Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 }));
const km = (v) => (v < 1 ? `${Math.round(v * 1000).toLocaleString()} m` : `${v.toLocaleString("en-US", { maximumFractionDigits: 1 })} km`);

// 助手打开窗口时在网址里带上一次性口令；读出来存好，然后从地址栏去掉
const TOKEN = (() => {
  const m = location.hash.match(/t=([\w-]+)/);
  if (m) { sessionStorage.setItem("t", m[1]); history.replaceState(null, "", location.pathname + "#home"); }
  try { return sessionStorage.getItem("t") || ""; } catch (e) { return m ? m[1] : ""; }
})();

// 改库存的操作：同一个操作（名字 + 参数一样）还没返回时又点了一次（连点），不再发第二次，等第一次的结果（1.6.58）
const WRITE_API = /^(stock_(?!places$|suggest$|prices$|ledger$)|count_(apply|cancel)|goal_finish)/;
const _inflight = new Map();
function api(name, args = {}) {
  const key = WRITE_API.test(name) ? name + "|" + JSON.stringify(args) : null;
  if (key && _inflight.has(key)) return _inflight.get(key);
  const p = (async () => {
    let r, j;
    try {
      r = await fetch(`/api/${name}`, { method: "POST", headers: { "Content-Type": "application/json", "X-Token": TOKEN }, body: JSON.stringify(args) });
      j = await r.json();
    } catch (e) { throw new Error("连不上 AT 后台（可能正在重启），稍后再试"); }
    if (!j.ok) throw new Error(j.error || "操作失败");
    if (j.data && j.data.error) throw new Error(j.data.error);
    return j.data;
  })();
  if (key) { _inflight.set(key, p); p.finally(() => _inflight.delete(key)).catch(() => {}); }
  return p;
}

function toast(msg, action = null) {                           // action：[按钮文字, 回调]，比如 ["撤销", …]
  const t = $("#toast");
  t.textContent = msg;
  if (action) {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = action[0];
    b.onclick = () => { t.hidden = true; action[1](); };
    t.appendChild(b);
  }
  t.hidden = false;
  t.style.animation = "none"; void t.offsetWidth; t.style.animation = "";      // 新提示顶掉旧的，重新淡入
  // 1.6.63：普通提示 3 秒；带「撤销」这种按钮的 8 秒；鼠标停在上面时不消失
  toast.ms = action ? 8000 : 3000;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), toast.ms);
  if (!t.dataset.hover) {
    t.dataset.hover = "1";
    t.addEventListener("mouseenter", () => clearTimeout(toast.timer));
    t.addEventListener("mouseleave", () => { clearTimeout(toast.timer); toast.timer = setTimeout(() => (t.hidden = true), 1500); });
  }
}

// ================================================================ 1.6.60：弹出层和选择器（规则见 DESIGN.md 第 5、6 节）
// 分段选择（2–5 个选项代替下拉框）。用法和 <select> 一样：.value 读写、onchange
class XSeg extends HTMLElement {
  connectedCallback() {
    if (this._ready) return;
    this._ready = true;
    this.classList.add("seg");
    this.setAttribute("role", "radiogroup");
    const opts = JSON.parse(this.dataset.opts || "[]");
    this.innerHTML = opts.map(([v, l]) => `<button type="button" role="radio" data-v="${esc(v)}">${esc(l)}</button>`).join("");
    this.value = this._v ?? this.getAttribute("value") ?? (opts[0] || [""])[0];
    this.addEventListener("click", (e) => {
      const b = e.target.closest("[data-v]");
      if (!b || b.dataset.v === this._v) return;
      this.value = b.dataset.v;
      this.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }
  get value() { return this._v ?? this.getAttribute("value") ?? ""; }
  set value(v) {
    this._v = String(v);
    this.querySelectorAll("[data-v]").forEach((b) => { const on = b.dataset.v === this._v; b.classList.toggle("on", on); b.setAttribute("aria-checked", on); });
  }
}
customElements.define("x-seg", XSeg);
const segH = (id, opts, value, label = "") =>
  `<x-seg id="${esc(id)}" data-opts="${esc(JSON.stringify(opts.map((o) => (Array.isArray(o) ? o : [String(o), String(o)]))))}" value="${esc(value ?? "")}"${label ? ` aria-label="${esc(label)}"` : ""}></x-seg>`;

// 弹出小框：贴着按钮弹（下面放不下就往上），点外面或 Esc 关。小确认（Popconfirm）和「更多」菜单都用它
const POPS = [];
function popOver(anchor, html, { cls = "", onClose = null, align = "right" } = {}) {
  if (POPS.some((x) => x.anchor === anchor)) { closePops(); return null; }      // 再点一次同一个按钮：收起
  closePops();
  const el = document.createElement("div");
  el.className = `popc ${cls}`;
  el.innerHTML = html;
  document.body.appendChild(el);
  const place = () => {                                          // 贴着按钮放；页面滚动时跟着按钮走
    if (!anchor.isConnected) return;
    const r = anchor.getBoundingClientRect(), w = el.offsetWidth, h = el.offsetHeight;
    const below = r.bottom + 8 + h <= innerHeight - 8 || r.top - 8 - h < 8;
    el.style.top = `${below ? r.bottom + 8 : r.top - 8 - h}px`;
    el.style.left = `${Math.max(8, Math.min(align === "left" ? r.left : r.right - w, innerWidth - w - 8))}px`;
  };
  place();
  const p = { el, q: (s) => el.querySelector(s), anchor, place, form: cls.includes("confirm"), dirty: false };
  el.addEventListener("input", () => { p.dirty = true; });     // 填过东西的小表单：点外面、滚动都不关，只有「取消」或 Esc 关
  p.close = () => { const i = POPS.indexOf(p); if (i < 0) return; POPS.splice(i, 1); el.remove(); if (onClose) onClose(); };
  POPS.push(p);
  anchor.setAttribute("aria-expanded", "true");
  const off = p.close;
  p.close = () => { anchor.removeAttribute("aria-expanded"); off(); };
  return p;
}
function closePops() { while (POPS.length) POPS.at(-1).close(); }
document.addEventListener("mousedown", (e) => {
  if (!POPS.length || e.target.closest(".popc") || POPS.some((p) => p.anchor.contains(e.target))) return;
  [...POPS].forEach((p) => { if (!p.dirty) p.close(); });
}, true);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && POPS.length) { e.preventDefault(); closePops(); } }, true);
addEventListener("resize", () => POPS.forEach((p) => p.place()));
document.addEventListener("scroll", (e) => {
  if (!POPS.length || e.target.closest?.(".popc")) return;
  [...POPS].forEach((p) => (p.form ? p.place() : p.close()));   // 菜单滚动就收起；小表单跟着按钮走
}, true);

// 小确认：title、body（可放输入框）、okText；onOk 返回 false 就不关（比如数填错了）
function popconfirm(anchor, { title, sub = "", body = "", okText = "确认", danger = false, onOk }) {
  const p = popOver(anchor, `<div class="popc-t">${esc(title)}</div>${sub ? `<div class="popc-s">${sub}</div>` : ""}${body}
    <div class="popc-err" role="alert" hidden></div>
    <div class="popc-f"><button type="button" class="btn small" data-x>取消</button><button type="button" class="btn small ${danger ? "stop" : "primary"}" data-ok>${esc(okText)}</button></div>`,
    { cls: "confirm" });
  if (!p) return null;
  p.q("[data-x]").onclick = p.close;
  p.error = (msg) => { const e = p.q(".popc-err"); e.textContent = msg; e.hidden = !msg; p.place(); };   // 出错留在小框里，改了再试
  const ok = p.q("[data-ok]");
  ok.onclick = async () => {
    ok.disabled = true;
    try { if ((await onOk(p)) !== false) p.close(); } finally { ok.disabled = false; }
  };
  p.el.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.tagName === "INPUT") { e.preventDefault(); ok.click(); } });
  const first = p.q("input");
  setTimeout(() => (first ? (first.select(), first.focus()) : ok.focus()), 0);
  return p;
}
// 下拉菜单（下命令）：items = [[文字, 回调], …]
function menu(anchor, items) {
  const p = popOver(anchor, `<div role="menu">${items.map(([t], i) => `<button type="button" role="menuitem" data-i="${i}">${esc(t)}</button>`).join("")}</div>`, { cls: "menu" });
  if (!p) return null;
  p.el.onclick = (e) => { const b = e.target.closest("[data-i]"); if (!b) return; p.close(); items[+b.dataset.i][1](); };
  setTimeout(() => p.q("button")?.focus(), 0);
  return p;
}

// 1.6.63：右边「实时」栏可以收起 / 展开（记住选择）；窗口窄时默认收起，点开浮在右边
(() => {
  const app = document.querySelector(".app"), b = $("#feed-tg");
  if (!app || !b) return;
  let saved = null;
  try { saved = localStorage.getItem("feed"); } catch (e) { /* 存不了就每次按窗口宽度定 */ }
  const set = (on, keep) => {
    app.classList.toggle("feed-on", on); app.classList.toggle("feed-off", !on);
    b.setAttribute("aria-pressed", on); b.classList.toggle("on", on);
    if (keep) try { localStorage.setItem("feed", on ? "1" : "0"); } catch (e) { /* 同上 */ }
  };
  set(saved == null ? innerWidth > 1180 : saved === "1", false);
  b.onclick = () => set(!app.classList.contains("feed-on"), true);
})();

// 悬停小字：页面里的 title 统一换成天枢自己的提示（停 0.3 秒出现，不用浏览器那个慢半拍的）
(() => {
  let tip = null, timer = 0, cur = null;
  const hide = () => { clearTimeout(timer); cur = null; if (tip) tip.hidden = true; };
  document.addEventListener("mouseover", (e) => {
    const t = e.target.closest?.("[title],[data-tip]");
    if (t === cur) return;
    hide();
    if (!t) return;
    if (t.hasAttribute("title")) { const v = t.getAttribute("title"); t.removeAttribute("title"); if (v) t.dataset.tip = v; }
    if (!t.dataset.tip) return;
    cur = t;
    timer = setTimeout(() => {
      if (cur !== t || !t.isConnected) return;
      if (!tip) { tip = document.createElement("div"); tip.className = "tip"; tip.setAttribute("role", "tooltip"); document.body.appendChild(tip); }
      tip.textContent = t.dataset.tip; tip.hidden = false;
      const r = t.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
      tip.style.left = `${Math.max(8, Math.min(r.left + r.width / 2 - w / 2, innerWidth - w - 8))}px`;
      tip.style.top = `${r.top - h - 8 >= 8 ? r.top - h - 8 : r.bottom + 8}px`;
    }, 300);
  });
  document.addEventListener("mousedown", hide, true);
  document.addEventListener("scroll", hide, true);
})();

// 游戏里的热键（和 services.HOTKEYS 一样）：[设置名, 默认键, 名字, 说明]
const HOTKEYS = [["live_key", "F5", "采矿助手开关", "开启后 120 秒未检测到扫描面板和信号自动关闭"], ["count_key", "F6", "盘点", "开始 / 结束盘点"],
  ["mark_key", "", "记录路标", "自动输入 /showlocation，将当前位置保存为路标"], ["trade_capture_key", "F8", "物品识别", "鼠标停在物品上时按下；鼠标移开自动收起，按住 Ctrl 不收；按住 Shift 再按钉住"],
  ["fix_key", "", "一键定位", "手动定位时自动输入 /showlocation"], ["report_key", "F10", "问题反馈", "保存当前截图和识别结果"],
  ["ore_key", "", "原矿记录", "记录当前矿石和坐标"]];

const state = {
  status: null, hud: {}, scan: null, scans: [], signals: null, nav: { active: false }, hover: null,
  logs: {}, tasks: {}, item: null, itemFrom: "", plan: null,
  sel: 0, priceReq: 0,          // 物品选择序号 / 价格请求序号：异步结果回来时核对，旧的丢掉（老大 2026-10-28 定）
};

// ================================================================ 实时消息
function connect() {
  const es = new EventSource(`/api/events?t=${encodeURIComponent(TOKEN)}`);
  es.onmessage = (e) => {
    const { kind, data, replay } = JSON.parse(e.data);       // replay：窗口刚打开时后台补发的旧消息，只恢复状态
    window.dispatchEvent(new CustomEvent("ata:backend", { detail: { kind, data, replay: !!replay } }));   // 阿塔（ata/at-adapter.js）也听这条
    if (kind === "quit") {                       // 天枢退出或重新启动了：这个窗口没用了，关掉
      es.close();
      document.body.innerHTML = `<div class="gate"><div class="gate-card"><h2>AT 已退出或重新启动</h2><p>可以关闭此窗口</p></div></div>`;
      setTimeout(() => window.close(), 300);
      return;
    }
    if (kind === "hud") {
      if (data.text) state.hud[data.section] = data.text;
      else delete state.hud[data.section];
      renderHud();
    } else if (kind === "status") {
      state.status = data; renderTop();
    } else if (kind === "scan") {
      if (!state.scan || state.scan.at !== data.at) state.scans = [data, ...state.scans].slice(0, 12);
      state.scan = data;
      if (page === "live") renderPage();
    } else if (kind === "scan_hint") {           // 采矿助手读不全的原因（面板被屏幕挡住 / 字有色差重影），空的就是收起
      state.scanHint = data.text ? data : null;
      if (page === "live") renderPage();
    } else if (kind === "signals") {             // 过期时后台会把同一条结果带上 stale（从几点起没看到）再发一次
      state.signals = data;
      if (page === "live") renderPage();
    } else if (kind === "live") {               // paused：游戏不在最前面，暂停识别（小灯变黄）
      $("#pip-live").className = "pip" + (data.running ? (data.paused ? " new" : " on") : "");
      if (state.status) { state.status.live = data.running; state.status.live_paused = !!(data.running && data.paused); }
      if (page === "live" || page === "home") renderPage();
    } else if (kind === "count") {             // 盘点开 / 关；结束时带对账结果
      state.count = { ...(state.count || {}), ...data };
      if (page === "stock") countDraw();
    } else if (kind === "ore_log") {             // 原矿记录变了（游戏里按热键记的也走这里）
      window.dispatchEvent(new Event("dubhe:ore"));
    } else if (kind === "waypoints") {
      window.dispatchEvent(new Event("dubhe:waypoints"));
    } else if (kind === "nav") {
      state.nav = data;
      $("#pip-nav").className = "pip" + (data.active ? " on" : "");
      if (page === "nav") renderNavLive();
    } else if (kind === "halo") {               // 小行星带：按 F9 核对在不在带里
      state.haloWhere = data;
      if (page === "nav" && state.navTab === "halo") drawHaloWhere();
    } else if (kind === "hover") {
      state.hover = data;
      if (replay) {
        if (data.state === "ok" && !state.item) {         // 刷新窗口后把上一次 F8 的结果放回来，不跳页、不弹提示
          state.sel++; data.info.marketId = data.market?.id || "";
          state.item = data.info; state.itemFrom = "F8"; state.market = data.market; state.candidates = data.candidates;
          state.prices = null;
          if (page === "item") renderPage();
        }
        $("#pip-hover").className = "pip";
      } else if (data.state === "ok") {
        appendRuntimeLog({ time: new Date().toTimeString().slice(0, 8), tag: "HOVER", level: "INFO", line: `成功识别: ${data.zh || data.en} (品质 ${data.quality ?? "无"})` });
        state.sel++; data.info.marketId = data.market?.id || "";
        state.item = data.info; state.itemFrom = "F8";
        state.market = data.market; state.candidates = data.candidates;
        state.prices = data.pending ? { loading: true, quality: data.tier || "q0", op: "sell" } : null;
        if (data.market && !data.pending) loadPrices(data.market.id, data.tier || "q0");
        location.hash = "#item";
        if (page === "item") renderPage();
      } else if (data.state === "miss") {
        appendRuntimeLog({ time: new Date().toTimeString().slice(0, 8), tag: "HOVER", level: "WARN", line: "未识别到说明框：" + (data.msg || "鼠标停在物品上") });
        toast(data.msg);
      }
      if (data.state === "working") {
        appendRuntimeLog({ time: new Date().toTimeString().slice(0, 8), tag: "HOVER", level: "INFO", line: "正在分析鼠标悬停区域文字..." });
      }
      $("#pip-hover").className = "pip" + (data.state === "working" ? " new" : "");
    } else if (kind === "hover_more") {
      // F8 之后后台补来的：市场里对上的物品、价格、掉落（同一次 F8 才用）
      if (state.hover && state.hover.at === data.at && state.itemFrom === "F8") {
        if (data.info) state.item = { ...data.info, zh: state.item?.zh || data.info.zh, marketId: state.item?.marketId || "" };
        if ("market" in data) { state.market = data.market; state.candidates = data.candidates || []; if (state.item) state.item.marketId = data.market?.id || ""; }
        if (data.prices) state.prices = data.prices;
        else if ("market" in data && !data.market) state.prices = null;
        if ("loot" in data && state.item) state.item.loot = data.loot;
        if (page === "item") drawItem();
        appendRuntimeLog({ time: new Date().toTimeString().slice(0, 8), tag: "HOVER", level: "INFO", line: `市场与价格补全: ${state.item?.zh || state.item?.name || ""}` });
      }
    } else if (kind === "log") {
      (state.logs[data.task] ||= []).push(data.line);
      if (state.logs[data.task].length > 400) state.logs[data.task].shift();
      const el = document.getElementById(`log-${data.task}`);
      if (el) { el.textContent = state.logs[data.task].join("\n"); el.scrollTop = el.scrollHeight; }
      if (data.task === "upgrade") upgProgress(data.line);
    } else if (kind === "runtime_log") {
      appendRuntimeLog(data);
    } else if (kind === "runtime_log_clear") {
      clearRuntimeLogsUi();
    } else if (kind === "runtime_preview") {
      updateRuntimePreview(data);
    } else if (kind === "task") {
      state.tasks[data.id] = data;
      if (replay) { if (page === "settings") renderPage(); return; }
      if (data.id === "update" && data.state !== "running") { toast(data.state === "done" ? "数据已更新" : "数据更新失败，详情见设置页"); refreshStatus(); }
      if (data.id === "upgrade" && data.state === "error") { toast("升级失败：" + (data.error || "详情见设置页")); upgProgress("❌"); }
      else if (data.state === "error" && data.id !== "update") toast(`${data.title || "后台任务"}失败：${data.error || "详情见设置页"}`);
      if (page === "settings") renderPage();
    }
  };
  es.onerror = () => {};
}

// ================================================================ 顶栏 / 实时栏
const HUD_ORDER = ["辅助", "信号", "扫描", "矿袋", "导航", "小行星带", "物品", "交易", "路标", "反馈"];
const HUD_LABEL = { 扫描: "采矿助手", 导航: "导航" };            // 悬浮窗分区显示名（内部还叫扫描 / 导航）
const HUD_COLOR = { 辅助: "#8b98a9", 信号: "#6cb8ff", 扫描: "#55d394", 矿袋: "#b59aff", 导航: "#f2b84b", 小行星带: "#f2b84b", 物品: "#ff9e6e", 交易: "#ff9e6e" };

function renderHud() {
  const keys = Object.keys(state.hud).sort((a, b) => (HUD_ORDER.indexOf(a) + 99) % 99 - (HUD_ORDER.indexOf(b) + 99) % 99);
  $("#feed-tg")?.classList.toggle("has", keys.length > 0);       // 实时栏收起时，按钮上亮个点
  const seen = (renderHud.seen ||= new Set());
  $("#hud").innerHTML = keys.map((k) => {
    const [t, ...rest] = state.hud[k].split("\n");
    const isNew = !seen.has(k);
    return `<div class="hud-sec${isNew ? " new" : ""}" style="--c:${HUD_COLOR[k] || "#6cb8ff"}"><span class="bar"></span><div>
      <div class="k">${esc(HUD_LABEL[k] || k)}</div><div class="t">${esc(t)}</div>${rest.length ? `<div class="b">${esc(rest.join("\n"))}</div>` : ""}</div></div>`;
  }).join("");
  seen.clear(); keys.forEach((k) => seen.add(k));               // 只有新出现的分区淡入；读数变了直接换，不模糊
  $("#hud-empty").hidden = keys.length > 0;
}

// ---------------------------------------------------------------- UI 右下角运行监控 (截图 + 日志)
function appendRuntimeLog(data) {
  state.runtimeLogs ||= [];
  state.runtimeLogs.push(data);
  if (state.runtimeLogs.length > 300) state.runtimeLogs.shift();

  const list = document.getElementById("rt-log-list");
  if (!list) return;
  const row = document.createElement("div");
  const lvl = data.level || "INFO";
  const tag = (data.tag || "SYS").toUpperCase();
  row.className = `rt-log-item ${lvl}`;
  row.innerHTML = `<span class="rt-log-t">${esc(data.time || "")}</span><span class="rt-log-tag ${esc(tag)}">${esc(tag)}</span><span class="rt-log-text">${esc(data.line || "")}</span>`;
  list.appendChild(row);

  if (list.children.length > 300) {
    list.removeChild(list.firstChild);
  }

  const box = document.getElementById("rt-log-box");
  const chk = document.getElementById("rt-autoscroll");
  if (box && (!chk || chk.checked)) {
    box.scrollTop = box.scrollHeight;
  }
}

function clearRuntimeLogsUi() {
  state.runtimeLogs = [];
  const list = document.getElementById("rt-log-list");
  if (list) list.innerHTML = "";
}

function updateRuntimePreview(meta) {
  state.previewMeta = meta;
  const img = document.getElementById("rt-preview-img");
  const dot = document.getElementById("rt-dot");
  if (img) {
    img.src = `/api/screenshot?token=${encodeURIComponent(TOKEN)}&_t=${encodeURIComponent(meta.t || Date.now())}`;
  }
  if (dot) dot.classList.remove("idle");
}

function initRuntimeMonitor() {
  const clearBtn = document.getElementById("rt-clear-btn");
  const toggleBtn = document.getElementById("rt-toggle-btn");
  const monitor = document.getElementById("rt-monitor");

  clearBtn?.addEventListener("click", async () => {
    try {
      await api("runtime_clear_logs");
      clearRuntimeLogsUi();
    } catch (e) {
      clearRuntimeLogsUi();
    }
  });

  toggleBtn?.addEventListener("click", () => {
    if (!monitor) return;
    const isCollapsed = monitor.classList.toggle("collapsed");
    toggleBtn.setAttribute("aria-expanded", !isCollapsed);
    try { localStorage.setItem("rt_monitor_collapsed", isCollapsed ? "1" : "0"); } catch (_) {}
  });

  try {
    if (localStorage.getItem("rt_monitor_collapsed") === "1" && monitor) {
      monitor.classList.add("collapsed");
      toggleBtn?.setAttribute("aria-expanded", "false");
    }
  } catch (_) {}
}

// 外观：深色 / 浅色（2026-10-25 AT 品牌配色）。先用本机记住的，避免打开时闪一下；设置以后台为准
function applyTheme(t) {
  const light = t === "light";
  if (light) document.documentElement.dataset.theme = "light"; else delete document.documentElement.dataset.theme;
  const m = document.getElementById("brandmark");
  if (m) m.src = light ? "at-mark-light.svg" : "at-mark-dark.svg";
  try { localStorage.setItem("theme", light ? "light" : "dark"); } catch (e) { /* 存不了就算了 */ }
  shellSync();
}
// AT 窗口外壳（2026-10-27）：顶条左段和侧边栏同宽同色、跟着主题变；不在外壳里（Edge 窗口、浏览器）时什么也不做
function shellSync() {
  try {
    const wv = window.chrome && window.chrome.webview;
    if (!wv) return;
    document.documentElement.classList.add("in-shell");     // 外壳的顶条里已经画了「AT 星际公民助手」，网页里的品牌行收起（2026-10-28）
    const rail = document.querySelector(".rail");
    wv.postMessage({ type: "chrome", light: document.documentElement.dataset.theme === "light", rail: rail ? rail.getBoundingClientRect().width : 0 });
  } catch (e) { /* 外壳不在就算了 */ }
}
window.addEventListener("resize", () => requestAnimationFrame(shellSync));
window.addEventListener("load", shellSync);
try { applyTheme(localStorage.getItem("theme")); } catch (e) { /* 读不了就用深色 */ }

function renderTop() {
  const s = state.status;
  if (!s) return;
  applyTheme(s.settings?.theme);
  $("#hk").textContent = s.hover_key;
  const p = s.position;
  const sysZh = { Stanton: "斯坦顿", Pyro: "派罗", Nyx: "尼克斯" };
  const sysTag = p && p.sys && sysZh[p.sys] && !p.label.includes(sysZh[p.sys]) ? `<span class="faint">（${sysZh[p.sys]}）</span>` : "";
  $("#where").innerHTML = p ? `位置：<b>${esc(p.label)}</b>${sysTag}${p.live ? `<span class="tag qt" style="margin-left:8px" title="右上角调试信息实时读取">实时</span>` : p.minutes > 10 ? `，${p.minutes} 分钟前` : ""}` : "位置未知：在游戏中打开一次库存即可获取";
  $("#where").title = p && p.live ? "" : "游戏控制台（~）输入 r_DisplayInfo 2，位置可实时显示";
  const b = $("#banner");
  if (s.win && s.game_elevated && !s.admin) {
    b.hidden = false;
    b.textContent = "游戏以管理员身份运行而 AT 没有，F8、自动跑和防挂机在游戏中无法使用。关闭 AT 后重新打开「" + (s.frozen ? "AT" : "Dubhe.exe") + "」，在 Windows 确认框中点击「是」。";
  } else b.hidden = true;
  $("#pip-live").className = "pip" + (s.live ? (s.live_paused ? " new" : " on") : "");
  $("#pip-nav").className = "pip" + (s.nav ? " on" : "");
}

async function refreshStatus() {
  try { state.status = await api("status"); renderTop(); } catch (e) { /* 后台还没好 */ }
  if (!state.upgradedChecked && state.status) {
    state.upgradedChecked = true;
    const u = await api("upgraded").catch(() => ({}));
    if (u && u.to) toast(u.rollback ? `已回滚到 AT ${u.to}` : `已升级到 AT ${u.to}`);
  }
}

// ================================================================ 全局搜索
let omniSel = -1, omniItems = [];
function omniInit() {
  const input = $("#omni"), pop = $("#omni-pop");
  let timer;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (!q) { pop.hidden = true; return; }
    timer = setTimeout(async () => {
      const r = await api("search", { q }).catch(() => null);
      if (!r || input.value.trim() !== q) return;
      omniItems = [];
      const group = (title, rows, fn) => rows.length ? `<h4>${title}</h4>` + rows.map((x) => { omniItems.push(fn(x)); const it = omniItems.at(-1); return `<button data-i="${omniItems.length - 1}">${it.html || esc(it.label)}<span class="sub">${esc(it.sub || "")}</span></button>`; }).join("") : "";
      const html =
        group("矿物", r.minerals, (x) => ({ label: x.zh, sub: x.en, go: () => openMineral(x.en) })) +
        group("物品", r.items, (x) => ({ html: nameHTML(x.zh, x.name), label: x.zh || x.name, sub: x.category || SRC_ZH[x.src] || "", go: () => openItem(x.name, x.zh, x.id, true) })) +
        group("地点", r.places, (x) => ({ label: x.label, sub: `${x.body}｜${x.type}`, go: () => openPlace(x.key) })) +
        group("蓝图", r.blueprints, (x) => ({ html: x.en ? nameHTML(x.zh, x.en) + (x.note ? esc("｜" + x.note) : "") : "", label: x.name, sub: x.kind, go: () => openCraft(x.key) })) +
        group("维科洛兑换", r.wikelo, (x) => ({ label: x.title, sub: x.reward, go: () => openWikelo(x.key) }));
      pop.innerHTML = html || `<div class="empty" style="padding:12px">未找到「${esc(q)}」。地名、物品名可用中文或英文搜索</div>`;
      pop.hidden = false;
      omniSel = -1;
    }, 180);
  });
  pop.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-i]");
    if (b) { omniItems[+b.dataset.i].go(); pop.hidden = true; input.blur(); }
  });
  input.addEventListener("keydown", (e) => {
    const btns = [...pop.querySelectorAll("button[data-i]")];
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      omniSel = Math.max(0, Math.min(btns.length - 1, omniSel + (e.key === "ArrowDown" ? 1 : -1)));
      btns.forEach((b, i) => b.classList.toggle("sel", i === omniSel));
      btns[omniSel]?.scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter") {
      const b = btns[Math.max(0, omniSel)];
      if (b) { omniItems[+b.dataset.i].go(); pop.hidden = true; input.blur(); }
    } else if (e.key === "Escape") { pop.hidden = true; input.blur(); }
  });
  document.addEventListener("click", (e) => { if (!e.target.closest(".omni")) pop.hidden = true; });
  document.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); input.focus(); input.select(); } });
}

document.addEventListener("click", (e) => {                 // 扫描结果里的矿名：点一下看去哪挖、导航
  const a = e.target.closest("[data-ore]");
  if (a) { e.preventDefault(); openMineral(a.dataset.ore); }
});

// ================================================================ 路由
let page = "home";
const PAGES = {};
function route() {
  page = (location.hash || "#home").slice(1);
  if (!PAGES[page]) page = "home";
  document.querySelectorAll(".rail a").forEach((a) => a.classList.toggle("on", a.dataset.page === page));
  renderPage();
  $("#page").scrollTop = 0;
}
function renderPage() { PAGES[page](); }
window.addEventListener("hashchange", route);

// 把命令行风格的多行说明（【标题】、· 列表、｜分隔）排成好读的样子
function linesHTML(text) {
  return `<div class="lines">` + String(text || "").split("\n").map((line) => {
    const indent = line.match(/^\s*/)[0].length;
    let s = line.trim();
    if (!s) return "";
    let cls = indent >= 4 ? "l l2" : indent >= 2 ? "l l1" : "l";
    if (s.startsWith("【")) { cls = "h"; s = s.replace(/^【(.*?)】/, "$1｜"); }
    s = s.replace(/^·\s*/, "");
    const [first, ...parts] = s.split("｜");
    return `<div class="${cls}">${esc(first)}${parts.filter((p) => p.trim()).map((p) => `<span class="seg-part">${esc(p)}</span>`).join("")}</div>`;
  }).join("") + `</div>`;
}

// ================================================================ 总览
PAGES.home = () => {
  const s = state.status || {};
  const set = s.settings || {};
  const d = s.data || {};
  const lastScan = state.scan;
  const nv = s.new_version;
  $("#page").innerHTML = `
    ${nv ? `<div class="panel" style="margin-bottom:14px;border-color:var(--amber)"><div class="row" style="justify-content:space-between">
      <div><b>发现新版本 AT ${esc(nv.version)}</b><div class="muted" style="font-size:13px">${nv.online ? "可在线下载" : `位于「${esc(nv.where)}」（${esc(nv.at)}）`}，当前版本 ${esc(s.version || "")}</div></div>
      <a class="btn primary" href="#settings">升级</a></div></div>` : ""}
    <h1>概览</h1>
    <p class="lede">搜索物品、矿物、地点、蓝图和维科洛兑换。游戏中鼠标停在物品上按 <kbd>${esc(s.hover_key || "F8")}</kbd> 可查看该物品。游戏建议使用无边框全屏，窗口模式也可用，画面越小识别越不准。</p>
    ${resWarn(s)}
    <div class="hello">
      <div>
        <div class="quick">
          <a href="#live"><b>${s.live ? (s.live_paused ? "采矿助手已暂停" : "采矿助手运行中") : "采矿助手"}</b><span>${s.live ? (s.live_paused ? "游戏不在前台，切回游戏后继续" : "在采矿模式下扫描石头") : "识别石头成分，计算破碎方案和精炼收益"}</span></a>
          <a href="#nav"><b>${s.nav ? "导航中" : "导航"}</b><span>${s.nav ? esc(s.nav) : "前往洞穴、残骸和自定义路标"}</span></a>
          <a href="#item"><b>物品查询</b><span>购买地点、掉落和价格；限定版推荐可购买的同款</span></a>
          <a href="#item"><b>矿物开采地点</b><span>在物品查询中搜索矿物名，可导航前往</span></a>
        </div>
        ${lastScan ? `<h2>上一次扫描</h2><div class="panel"><div class="rock-head"><span class="name">${esc(lastScan.rock)}</span><span class="muted">${money(lastScan.mass)} kg｜抗性 ${lastScan.resistance}%</span></div>
          <div class="muted" style="margin-top:6px">${esc(lastScan.plans[0]?.short || "")}</div></div>` : ""}
      </div>
      <div class="panel">
        <h3>数据</h3>
        <dl class="kv">
          <dt>游戏版本</dt><dd>${esc(s.game_version || "")}</dd>
          <dt>数据包</dt><dd>${esc(d.pack || "未下载")}</dd>
          <dt>汉化包</dt><dd>${esc(d.loc || "未下载")}</dd>
          <dt>商店价格</dt><dd>${esc(d.shops || "未下载")}</dd>
          <dt>掉落数据</dt><dd>${esc(d.loot || "未下载")}</dd>
          <dt>星图</dt><dd>${esc(d.starmap || "未下载")}</dd>
        </dl>
        <div class="row" style="margin-top:14px"><a class="btn small" href="#settings">更新数据</a></div>
      </div>
    </div>`;
  bindSwitches();
};

function bindSwitches() {
  document.querySelectorAll("[data-set]").forEach((b) => b.addEventListener("click", async () => {
    const k = b.dataset.set;
    const cfg = await api("set_settings", { [k]: !state.status.settings[k] });
    state.status.settings = cfg;
    renderPage();
  }));
}

// ================================================================ 原矿扫描
PAGES.live = () => {
  const s = state.status || {};
  const sc = state.scan;
  const plans = (sc?.plans || []).map(planHTML).join("");
  $("#page").innerHTML = `
    <div class="row" style="justify-content:space-between;align-items:flex-start">
      <div><h1>采矿助手</h1><p class="lede">扫描石头后识别成分，按下方「配置」计算破碎方案和精炼收益。按 <kbd>${esc(state.status?.settings?.live_key || "F5")}</kbd> 开关，120 秒未检测到扫描面板和信号自动关闭；游戏建议使用无边框全屏，窗口模式也可用，画面越小识别越不准。</p></div>
      <div class="row" style="gap:8px;flex:none"><button type="button" class="btn" id="ore-open">原矿记录</button>
      ${s.live ? `<button class="btn stop" id="live-toggle">停止扫描</button>` : `<button class="btn primary" id="live-toggle">开始扫描</button>`}</div>
    </div>
    ${resWarn(s)}
    ${s.live && s.live_paused ? `<p id="live-paused" style="margin:0 0 12px"><span class="tag noqt">已暂停</span> 游戏不在前台，切回游戏后继续识别</p>` : ""}
    ${s.live && state.scanHint ? `<p id="live-hint" class="note-warn" style="margin:0 0 12px"><b>扫描面板识别不完整</b>（${esc(state.scanHint.at || "")}）：${esc(state.scanHint.text)}</p>` : ""}
    ${sc ? `
      <div class="panel">
        <div class="rock-head"><span class="name">${esc(sc.rock)}</span>${sc.difficulty ? `<span class="tag">游戏评级 ${esc(sc.difficulty)}</span>` : ""}<span class="faint">${esc(sc.at)}</span>${sc.stale ? `<span class="tag noqt">已过期：${esc(sc.stale)} 之后未检测到扫描面板</span>` : ""}<span class="row" style="margin-left:auto;gap:8px">${sc.stale ? "" : `<button type="button" class="btn small" id="ore-rec">记录</button>`}${fbBtn("scan")}</span></div>
        <div class="stats">
          <div><b>${money(sc.mass)}</b>质量 kg</div><div><b>${sc.resistance}%</b>抗性</div><div><b>${sc.instability}</b>不稳定性</div>
          ${sc.minerals.map((m) => `<div><b>${m.scu.toFixed(2)}</b>${m.en ? `<a href="javascript:void 0" data-ore="${esc(m.en)}" title="开采地点和导航">${esc(m.name)}</a>` : esc(m.name)} SCU</div>`).join("")}
        </div>
        ${sc.cut ? `<p class="note-warn" style="margin:10px 0 0">${esc(sc.note)}</p>` : ""}
        ${goalBox((sc.goal || []).map((g) => g.text), (sc.goal || []).some((g) => g.ok))}
      </div>
      ${lotsHTML(sc)}
      <div class="two" style="margin-top:14px">
        <div class="panel"><h3>破碎方案</h3>${plans || `<p class="muted">没有可用方案</p>`}</div>
        <div class="panel"><h3>精炼</h3>
          ${sc.refine.length ? `<table class="t"><tr><th>精炼方式和站点</th><th class="n">价格 aUEC</th><th class="n">时间</th></tr>
            ${sc.refine.map((r) => `<tr><td>${esc(r.method)}<div class="muted" style="font-size:12.5px">${esc(r.station)}${r.bonus ? `｜加成 <span class="good">${esc(r.bonus)}</span>` : ""}｜精炼费 ${money(r.fee)}</div>${r.amount ? `<div class="muted" style="font-size:12.5px">精炼后 ${esc(r.amount)}</div>` : ""}</td><td class="n money">${money(r.value)}</td><td class="n">${r.hours.toFixed(1)} 小时</td></tr>`).join("")}</table>
            ${sc.refine[0]?.lots?.length > 1 ? `<p class="muted" style="margin:6px 0 0;font-size:12.5px">按第一种方式精炼：${sc.refine[0].lots.map((y) => `${esc(y.zh)}${y.q != null ? ` ${y.q}` : ""}：${esc(y.amount)}`).join("；")}</p>`
              : sc.refine[0]?.yield?.length > 1 ? `<p class="muted" style="margin:6px 0 0;font-size:12.5px">按第一种方式精炼：${sc.refine[0].yield.map((y) => `${esc(y.zh)} ${esc(y.amount)}`).join("；")}</p>` : ""}`
            : sc.cut ? `<p class="muted">扫描面板被屏幕边缘遮挡，未识别到总 SCU，无法计算精炼</p>` : `<p class="muted">只有惰性物质</p>`}
          ${sc.sell.length ? `<p class="muted" style="margin:10px 0 0">出售地点：${sc.sell.map((x) => `${esc(x.name)} → ${esc(x.where)}`).join("，")}</p>` : ""}
          ${sc.craft.length || sc.craft_mats?.length ? `<h3 style="margin-top:14px">制造</h3>${(sc.craft_mats || []).map((m) => craftMatBtn(m)).join("")}${sc.craft.map((c) => `<div class="muted">${esc(c)}</div>`).join("")}` : ""}
        </div>
      </div>
      ${sc.bag ? `<div class="panel" style="margin-top:14px"><h3>矿袋 ${sc.bag.used}/${sc.bag.cap} SCU</h3><div class="meter"><i style="width:${Math.min(100, sc.bag.used / sc.bag.cap * 100)}%;background:var(--violet)"></i></div>
        <p class="muted" style="margin:8px 0 0">${sc.bag.items.map((x) => `${esc(x.name)} ${x.scu}`).join("，") || "空"}</p></div>` : ""}
    ` : `<div class="panel"><p class="muted" style="margin:0">${s.live ? (s.live_paused ? "切回游戏后扫描石头" : "扫描中…在游戏中扫描石头") : "暂无扫描结果。点击「开始扫描」后在游戏中扫描石头"}</p></div>`}
    ${state.signals ? `<h2>雷达信号 <span class="faint" style="font-weight:400;font-size:13px">${esc(state.signals.at)}${state.signals.area ? `｜${esc(state.signals.area)}` : ""}</span>${state.signals.stale ? ` <span class="tag noqt">已过期：${esc(state.signals.stale)} 之后未检测到信号</span>` : ""} <span style="float:right">${fbBtn("signal")}</span></h2><div class="panel">${state.signals.lines.map((l) => `<div>${esc(l)}</div>`).join("")}${(state.signals.unknown || []).map((v) => `<div class="row" style="margin-top:8px;gap:8px;align-items:center"><span class="muted">${money(v)}</span><input class="input sig-name" data-v="${v}" size="16" placeholder="起个名字"><button class="btn small" data-sig="${v}">记下</button></div>`).join("")}</div>` : ""}
    ${state.scans.length > 1 ? `<h2>本次扫描记录</h2><div class="panel"><table class="t"><tr><th>时间</th><th>矿物</th><th class="n">质量</th><th class="n">抗性</th><th>方案</th></tr>
      ${state.scans.map((x) => `<tr><td class="faint">${esc(x.at)}</td><td>${esc(x.rock)}</td><td class="n">${money(x.mass)}</td><td class="n">${x.resistance}%</td><td class="muted">${esc(x.plans[0]?.short || "")}</td></tr>`).join("")}</table></div>` : ""}
    <h2>配置</h2>
    <div class="panel" id="gear">加载中…</div>
    <h2>手动计算</h2>
    <div class="panel"><div class="row">
      <label class="field">质量 kg<input class="input" id="m-mass" inputmode="decimal" size="9"></label>
      <label class="field">抗性 %<input class="input" id="m-res" inputmode="decimal" size="5"></label>
      <label class="field">不稳定性<input class="input" id="m-ins" inputmode="decimal" size="6"></label>
      <button class="btn" id="m-go" style="align-self:flex-end">计算破碎方案</button></div>
      <div id="m-out" style="margin-top:10px"></div></div>`;
  $("#live-toggle").onclick = async () => {
    const on = !(state.status && state.status.live);
    if (on && state.gear && !state.gear.chosen) { toast("先在下方「配置」中选择采矿船"); $("#gear").scrollIntoView({ behavior: "smooth" }); return; }
    $("#live-toggle").disabled = true;
    try {
      await api(on ? "live_start" : "live_stop");
      if (state.status) { state.status.live = on; if (!on) state.status.live_paused = false; }
    } catch (err) { toast(err.message); }
    renderPage();
  };
  gearInit();
  $("#ore-open").onclick = oreDrawer;
  if ($("#ore-rec")) $("#ore-rec").onclick = oreRecord;
  $("#m-go").onclick = async () => {
    try {
      const plans = await api("manual_scan", { mass: $("#m-mass").value || 0, resistance: $("#m-res").value || 0, instability: $("#m-ins").value || 0 });
      $("#m-out").innerHTML = plans.map(planHTML).join("") || `<p class="muted">没有可用方案</p>`;
    } catch (e) { toast(e.message); }
  };
};

// ---------------- 配置：选船、每个矿头装什么、几个人同时操作（2026-10-26 改版：平时一行，点「修改配置」展开成矿头卡片）
async function gearInit() {
  try { state.gear = await api("mining_gear"); } catch (e) { $("#gear").innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
  gearRender();
}

const GEAR_STATS = [["power", "功率"], ["res", "抗性"], ["instab", "不稳定性"], ["window", "绿区"], ["rate", "充能"]];
// 读数变化的好坏：功率、绿区、充能越大越好；抗性、不稳定性越小越好
const gearGood = (k, v) => (v === 0 ? "" : (k === "res" || k === "instab" ? v < 0 : v > 0) ? "up" : "dn");
const pctTxt = (v) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v) + "%";

function gearModsText(g, mods) {                                // 「里格 Rieger-C3 ×2，聚焦 Focus III」
  const n = {};
  mods.forEach((m) => { n[m] = (n[m] || 0) + 1; });
  return Object.entries(n).map(([k, c]) => (g.modules.find((x) => x.key === k)?.name || k) + (c > 1 ? ` ×${c}` : "")).join("，");
}

function gearRender() {
  const g = state.gear, box = $("#gear");
  if (!g || !box) return;
  if (!g.chosen) {          // 第一次用：先选船
    box.innerHTML = `<div class="gear-line"><b>选择采矿船</b><span class="muted">破碎方案按所选船的配置计算</span>
      <span class="row" style="gap:8px">${g.ships.map((x) => `<button class="btn g-pick" data-k="${x.key}">${esc(x.name)}</button>`).join("")}</span></div>`;
    box.querySelectorAll(".g-pick").forEach((el) => (el.onclick = async () => {
      try { state.gear = await api("set_mining_gear", { ship: el.dataset.k }); state.gearOpen = true; gearRender(); } catch (e) { toast(e.message); }
    }));
    return;
  }
  const ship = g.ships.find((x) => x.key === g.ship) || g.ships[0];
  const lo = ship.loadout, sum = ship.summary;
  const headName = (k) => g.heads.find((x) => x.key === k)?.name || k;
  if (!state.gearOpen) {    // 平时：一行看完整套配置
    box.innerHTML = `<div class="gear-line">
      <b>${esc(ship.name)}</b>${ship.crew_max > 1 ? `<span class="muted">${lo.crew || 1} 人同时操作</span>` : ""}
      <span class="chips">${lo.heads.map(([k, mods], i) => `<span class="chip">${esc(headName(k))}${(lo.craft || [])[i] ? "（自制）" : ""}${mods.length ? ` <i>+${esc(gearModsText(g, mods))}</i>` : ""}</span>`).join("")}</span>
      <span class="muted num">总功率 <b>${money(sum.power)}</b> W</span>
      <button class="btn small" id="g-open" style="margin-left:auto">修改配置</button></div>
      ${ship.is_default ? `<p class="gear-hint">当前为出厂配置。按实际安装的矿头和模组修改后，破碎方案才准确</p>` : ""}`;
    $("#g-open").onclick = () => { state.gearOpen = true; gearRender(); };
    return;
  }
  const heads = ship.fixed ? g.heads.filter((h) => h.key === ship.fixed)
    : g.heads.filter((h) => h.size === ship.size && !h.ship);
  const craft = lo.craft || [];
  const cards = lo.heads.map(([hk, mods], i) => {
    const h = g.heads.find((x) => x.key === hk), c = craft[i], cd = ship.cards[i], pw = (ship.power || [])[i];
    const slots = Array.from({ length: h.slots }, (_, j) => {
      const m = mods[j] ? g.modules.find((x) => x.key === mods[j]) : null;
      return `<button type="button" class="chip g-slot${m ? "" : " empty"}" data-h="${i}" data-m="${j}" title="${esc(m ? m.desc : "点击选择模组")}">${m ? esc(m.name) : "空槽"}</button>`;
    }).join("");
    return `<div class="gear-card">
      <div class="gear-k"><span>矿头 ${lo.heads.length > 1 ? i + 1 : ""}</span>
        ${h.craft?.length ? segH(`g-src-${i}`, [["shop", "商店购买"], ["craft", "自制"]], c ? "craft" : "shop", "来源") : ""}</div>
      <select class="input g-head" data-h="${i}"${ship.fixed ? " disabled" : ""} title="${esc(h.desc)}">${heads.map((x) => `<option value="${x.key}"${x.key === hk ? " selected" : ""}>${esc(x.name)}</option>`).join("")}</select>
      <div class="gear-pw num">${cd.power !== cd.base ? `<span class="faint">${money(cd.base)} →</span> ` : ""}<b>${money(cd.power)}</b> W</div>
      <div class="gear-stats num">${GEAR_STATS.map(([k, l]) => `<div><span>${l}</span><b class="${gearGood(k, cd.stats[k])}">${cd.stats[k] ? pctTxt(cd.stats[k]) : "0"}</b></div>`).join("")}</div>
      ${h.slots ? `<div class="chips">${slots}</div>` : `<div class="faint" style="font-size:13px">此矿头没有模组槽</div>`}
      ${c ? `<div class="g-craft">
        <div class="faint" style="font-size:12.5px">${pw ? `自制品质使激光功率 ${pw.pct >= 0 ? "+" : ""}${pw.pct}%（两个槽合计）；框架（铁）的品质只影响耐久` : ""}</div>
        <div class="row" style="gap:6px"><button class="btn small g-preset" data-h="${i}" data-q="500" type="button">商店品质 500</button><button class="btn small g-preset" data-h="${i}" data-q="1000" type="button">最佳 1000</button></div>
        <div class="slots">${h.craft.map((s) => craftQHTML(i, s, c[s.slot])).join("")}</div></div>` : ""}
    </div>`;
  }).join("");
  box.innerHTML = `
    <div class="gear-line">
      ${segH("g-ship", g.ships.map((x) => [x.key, x.name]), ship.key, "采矿船")}
      ${ship.crew_max > 1 ? `<span class="muted">同时操作人数</span>${segH("g-crew", Array.from({ length: ship.crew_max }, (_, i) => String(i + 1)), String(lo.crew || 1), "同时操作人数")}` : ""}
      <span class="row" style="gap:8px;margin-left:auto"><span class="faint" style="font-size:13px">套用预设</span>
        ${ship.presets.map((p) => `<button type="button" class="btn small g-pre" data-p="${p.key}">${esc(p.name)}</button>`).join("")}
        <button type="button" class="btn small" id="g-close">收起</button></span>
    </div>
    ${ship.fixed ? `<p class="gear-hint">魔像的矿头不可更换，只能更换模组</p>` : ""}
    <div class="gear-cards">${cards}</div>
    <div class="gear-sum num">
      <div><span>总功率（${sum.crew} 人同时操作）</span><b>${money(sum.power)}<small>W</small></b></div>
      <div><span>可破碎质量（抗性 30%）</span><b>${money(sum.mass)}<small>kg</small></b></div>
      <div><span>可破碎质量（使用${esc(sum.gadget)}）</span><b>${money(sum.mass_gadget)}<small>kg</small></b></div>
      <div><span>保存</span><p>修改后自动保存，当前扫描结果按新配置重新计算</p></div>
    </div>`;
  const save = async (patch) => {
    const cur = JSON.parse(JSON.stringify(lo));
    patch(cur);
    try { state.gear = await api("set_mining_gear", { ship: ship.key, loadout: cur }); gearRender(); toast("已保存"); }
    catch (e) { toast(e.message); }
  };
  $("#g-close").onclick = () => { state.gearOpen = false; gearRender(); };
  $("#g-ship").onchange = async (e) => {
    try { state.gear = await api("set_mining_gear", { ship: e.target.value }); gearRender(); } catch (er) { toast(er.message); }
  };
  if ($("#g-crew")) $("#g-crew").onchange = (e) => save((c) => { c.crew = +e.target.value; });
  box.querySelectorAll(".g-pre").forEach((b) => (b.onclick = async () => {
    const p = ship.presets.find((x) => x.key === b.dataset.p);
    try {
      state.gear = await api("set_mining_gear", p.loadout ? { ship: ship.key, loadout: p.loadout } : { ship: ship.key, reset: true });
      gearRender(); toast(`已套用${p.name}`);
    } catch (e) { toast(e.message); }
  }));
  const setCraft = (c, i, v) => {                             // v：null = 商店买的；{槽名: 品质}
    c.craft = Array.from({ length: c.heads.length }, (_, j) => (c.craft || [])[j] || null);
    c.craft[i] = v;
  };
  box.querySelectorAll(".g-head").forEach((el) => (el.onchange = () => save((c) => { c.heads[+el.dataset.h] = [el.value, []]; setCraft(c, +el.dataset.h, null); })));
  lo.heads.forEach((_, i) => { const el = $(`#g-src-${i}`); if (el) el.onchange = () => save((c) => { setCraft(c, i, el.value === "craft" ? {} : null); }); });
  const setQ = (i, slot, q) => save((c) => { setCraft(c, i, { ...((c.craft || [])[i] || {}), [slot]: q }); });
  box.querySelectorAll(".g-craft .slot").forEach((card) => {                 // 滑块拖动时本地即时算这一槽的变化，松手（change）才保存
    const i = +card.dataset.h, slot = card.dataset.s, h = g.heads.find((x) => x.key === lo.heads[i][0]);
    const s = h.craft.find((x) => x.slot === slot), r = card.querySelector(".sq-r"), n = card.querySelector(".sq-n");
    const show = (v) => { n.value = v; card.querySelector(".fx").innerHTML = craftFxHTML(s, v); };
    const commit = (v) => { v = Math.max(0, Math.min(1000, Math.round(+v) || 0)); r.value = v; show(v); setQ(i, slot, v); };
    r.oninput = () => show(+r.value);
    r.onchange = () => commit(r.value);
    n.onchange = () => commit(n.value);
    n.onkeydown = (e) => { if (e.key === "Enter") n.blur(); };
    card.querySelector(".sq-dn").onclick = () => commit(+r.value - 1);
    card.querySelector(".sq-up").onclick = () => commit(+r.value + 1);
  });
  box.querySelectorAll(".g-preset").forEach((b) => (b.onclick = () => save((c) => {
    const i = +b.dataset.h, h = g.heads.find((x) => x.key === c.heads[i][0]);
    setCraft(c, i, Object.fromEntries(h.craft.map((s) => [s.slot, +b.dataset.q])));
  })));
  // 模组槽：点一下弹出按用途分组的选单，点模组即装上（以前 20 个模组挤在一个下拉框里）
  box.querySelectorAll(".g-slot").forEach((el) => (el.onclick = () => {
    const i = +el.dataset.h, j = +el.dataset.m, cur = lo.heads[i][1][j] || "";
    const p = popOver(el, `<div class="gear-pop">${g.groups.map((grp) => `<div class="gear-grp"><span>${esc(grp)}</span><div class="chips">${
      g.modules.filter((m) => m.group === grp).map((m) => `<button type="button" class="chip${m.key === cur ? " on" : ""}" data-k="${m.key}" title="${esc(m.desc)}">${esc(m.name)} <i>${esc(m.desc.split("，")[0])}</i></button>`).join("")}</div></div>`).join("")}
      <div class="gear-grp"><span></span><div class="chips"><button type="button" class="chip empty" data-k="">留空</button></div></div></div>`, { align: "left", cls: "gear-popc" });
    if (!p) return;
    p.el.querySelectorAll("[data-k]").forEach((b) => (b.onclick = () => {
      p.close();
      save((c) => { const m = c.heads[i][1]; m[j] = b.dataset.k; c.heads[i][1] = m.filter(Boolean); });
    }));
  }));
}

function curveVal(segs, q) {                                   // 品质 → 倍率（和 crafting.curve_value 一样，分段线性）
  for (const [qs, qe, a, b] of segs) if (qs <= q && q <= qe) return qe === qs ? a : a + (b - a) * (q - qs) / (qe - qs);
  return q > segs[segs.length - 1][1] ? segs[segs.length - 1][3] : segs[0][2];
}
function craftQHTML(i, s, q) {                               // 自造矿头一个槽：和制造页一样的卡片——滑块 + 加减 + 数字框，底下即时显示这一槽的激光功率变化（1.6.50）
  const v = q == null ? 500 : Math.round(q);
  return `<div class="slot" data-h="${i}" data-s="${esc(s.slot)}" style="min-width:230px">
    <div class="sh"><b>${esc(s.slot_zh)}</b><span class="faint" style="font-size:12px">${esc(s.mat_zh)}</span></div>
    <div class="qrow"><span class="faint" style="font-size:12px">品质</span><button class="btn small sq-dn" type="button">−</button><input type="range" class="sq-r" min="0" max="1000" step="1" value="${v}"><button class="btn small sq-up" type="button">+</button><input class="input sq-n" value="${v}" inputmode="numeric"></div>
    <div class="fx">${craftFxHTML(s, v)}</div></div>`;
}
function craftFxHTML(s, q) {
  const pct = (curveVal(s.segs, q) - 1) * 100, best = Math.max(...s.segs.map((x) => Math.max(x[2], x[3])));
  const cls = Math.abs(pct) < 0.005 ? "flat" : pct > 0 ? "up" : "down";
  return `<div><span>激光功率</span><span class="${cls}">${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%（最高 +${((best - 1) * 100).toFixed(0)}%）</span></div>`;
}

function lotsHTML(sc) {                                       // 成分表（1.6.42）：每一份（矿 × 品质、惰性物质）一行，精炼后按品质分开
  const lots = sc.lots || [];
  if (!lots.length) return "";
  const n = (v, d = 2) => (v == null ? "—" : Number(v).toFixed(d));
  const useful = lots.filter((r) => !r.inert), inert = lots.filter((r) => r.inert);
  const sum = (rs, k) => rs.reduce((a, r) => a + (r[k] || 0), 0);
  const foot = sc.total_scu ? `矿物 ${n(sum(useful, "scu"))} SCU（${n(sum(useful, "pct"), 0)}%）` + (inert.length ? `，惰性物质 ${n(sum(inert, "scu"))} SCU（${n(sum(inert, "pct"), 0)}%）` : "") : "";
  return `<div class="panel" style="margin-top:14px"><h3>成分 <span class="faint" style="font-weight:400;font-size:13px">${sc.total_scu ? `${n(sc.total_scu)} SCU` : ""}</span></h3>
    <div class="tscroll"><table class="t lots-t"><tr><th>成分</th><th class="n">占比</th><th class="n">原矿</th><th>品质</th><th>精炼后${sc.lots_plan ? `<span class="faint">（${esc(sc.lots_plan)}）</span>` : ""}</th></tr>
    ${lots.map((r) => `<tr${r.inert ? ' class="faint"' : ""}><td>${esc(r.zh)}${r.rank ? ` <span class="tag ${r.rank === "高品质" ? "qt" : ""}">${esc(r.rank)}</span>` : ""}</td>
      <td class="n">${n(r.pct)}%</td><td class="n">${r.scu == null ? "—" : `${n(r.scu)} SCU`}</td>
      <td>${r.inert ? "—" : r.q == null ? `<span class="faint">${sc.cut ? "被遮挡" : "—"}</span>` : `${r.q}${r.tier ? ` <span class="faint">${esc(r.tier)}</span>` : ""}`}</td>
      <td>${esc(r.refined_text || (sc.cut ? "" : "—"))}</td></tr>`).join("")}</table></div>
    <p class="faint" style="margin:8px 0 0;font-size:12.5px">${foot ? foot + "。" : ""}精炼保留品质：同一矿物的不同品质精炼后仍分开存放。4.8 起每种矿物有 7 档品质（F 最低，S 最高），另有少见的 1000 完美品质。</p></div>`;
}

// ---------------- 原矿记录（1.6.70）：点「记录」存下这块矿；抽屉里看全部，能排序、筛矿名、去这里、删除
async function oreRecord(e) {
  const b = e?.currentTarget;
  if (b) b.disabled = true;
  try {
    const r = await api("ore_record");
    toast(`已记录：${r.rock}`, ["撤销", async () => { try { await api("ore_delete", { id: r.id }); toast("已撤销"); } catch (err) { toast(err.message); } }]);
  } catch (err) { toast(err.message); } finally { if (b) b.disabled = false; }
}
const oreLotsText = (r) => (r.lots || []).map((x) => `${x.zh}${x.inert || x.q == null ? "" : ` ${x.q}`} · ${x.pct == null ? "—" : Number(x.pct).toFixed(2) + "%"}`);
async function oreDrawer() {
  const f = { sort: "at", desc: true, q: "" };
  let rows = [];
  const md = openModal({ title: "原矿记录", drawer: true,
    body: `<div class="row" style="gap:12px;align-items:center;margin-bottom:12px">
        <input class="input" id="or-q" placeholder="搜索矿物名" autocomplete="off" style="flex:1;max-width:280px">
        <span class="faint" id="or-n"></span></div>
      <div id="or-list"><p class="muted">加载中…</p></div>`,
    onClose: () => removeEventListener("dubhe:ore", load) });
  md.el.classList.add("wide");
  const sh = (k, label) => `<button type="button" class="th-sort${f.sort === k ? " on" : ""}" data-sort="${k}">${label}${f.sort === k ? (f.desc ? " ↓" : " ↑") : ""}</button>`;
  const draw = () => {
    const q = f.q.trim().toLowerCase();
    const hit = rows.filter((r) => !q || [r.rock, ...(r.lots || []).map((x) => `${x.zh} ${x.en}`)].join(" ").toLowerCase().includes(q));
    const key = (r) => f.sort === "at" ? r.at || "" : f.sort === "rock" ? r.rock || "" : +(r[f.sort] ?? -1);
    hit.sort((a, b) => { const x = key(a), y = key(b); return (x < y ? -1 : x > y ? 1 : 0) * (f.desc ? -1 : 1); });
    md.q("#or-n").textContent = `${hit.length} 条`;
    const box = md.q("#or-list");
    if (!rows.length) { box.innerHTML = `<p class="empty">暂无原矿记录</p>`; return; }
    if (!hit.length) { box.innerHTML = `<p class="empty">没有匹配的记录 <button type="button" class="btn small" id="or-clear">清除筛选</button></p>`;
      md.q("#or-clear").onclick = () => { f.q = ""; md.q("#or-q").value = ""; draw(); }; return; }
    box.innerHTML = `<div class="tscroll"><table class="t ore-t"><tr><th>${sh("at", "时间")}</th><th>${sh("rock", "矿物")}</th><th class="n">${sh("mass", "质量 kg")}</th>
        <th class="n">${sh("resistance", "抗性")}</th><th class="n">${sh("instability", "不稳定性")}</th><th>成分</th>
        <th class="n">${sh("total_scu", "原矿 SCU")}</th><th class="n">${sh("value", "价格 aUEC")}</th><th>坐标</th><th></th></tr>
      ${hit.map((r) => `<tr><td class="faint" style="white-space:nowrap">${esc((r.at || "").slice(5, 16))}</td><td>${esc(r.rock)}${r.difficulty ? `<div class="faint" style="font-size:12px">${esc(r.difficulty)}</div>` : ""}</td>
        <td class="n">${money(r.mass)}</td><td class="n">${r.resistance ?? "—"}%</td><td class="n">${r.instability ?? "—"}</td>
        <td style="font-size:13px">${oreLotsText(r).map((t) => `<div>${esc(t)}</div>`).join("")}</td>
        <td class="n">${r.total_scu == null ? "—" : Number(r.total_scu).toFixed(2)}</td><td class="n">${money(r.value)}</td>
        <td style="font-size:13px">${r.coords ? esc(r.where || "已记录坐标") : `<span class="faint">—</span>`}</td>
        <td style="white-space:nowrap">${r.coords ? `<button type="button" class="btn small" data-go="${esc(r.id)}">导航</button> ` : ""}<button type="button" class="btn small" data-del="${esc(r.id)}">删除</button></td></tr>`).join("")}</table></div>`;
  };
  async function load() {
    try { rows = (await api("ore_list")).rows; } catch (e) { md.q("#or-list").innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
    draw();
  }
  addEventListener("dubhe:ore", load);
  md.q("#or-q").oninput = (e) => { f.q = e.target.value; draw(); };
  md.el.addEventListener("click", async (e) => {
    const so = e.target.closest("[data-sort]");
    if (so) { f.desc = f.sort === so.dataset.sort ? !f.desc : so.dataset.sort === "at" || so.dataset.sort !== "rock"; f.sort = so.dataset.sort; draw(); return; }
    const go = e.target.closest("[data-go]");
    if (go) {
      go.disabled = true;
      try { const r = await api("ore_go", { id: go.dataset.go }); toast(`已开始导航：${r.name}`); } catch (err) { toast(err.message); } finally { go.disabled = false; }
      return;
    }
    const del = e.target.closest("[data-del]");
    if (del) {
      const r = rows.find((x) => x.id === del.dataset.del);
      popconfirm(del, { title: "删除此记录？", sub: esc(`${r?.rock || ""} · ${(r?.at || "").slice(5, 16)}`), okText: "删除", danger: true,
        onOk: async () => {
          try {
            const gone = await api("ore_delete", { id: del.dataset.del });
            toast("已删除", ["撤销", async () => { try { await api("ore_restore", { rec: gone }); toast("已撤销"); } catch (err) { toast(err.message); } }]);
          } catch (err) { toast(err.message); }
        } });
    }
  });
  load();
}

function planHTML(p) {
  const pct = Math.min(100, p.ratio * 100 / 1.6);
  const cls = !p.breakable ? "no" : p.comfortable ? "" : "warn";
  const verdict = !p.breakable ? `<span class="bad">满功率也无法破碎</span>` : `功率调至 <b>${Math.round(p.throttle * 100)}%</b>`;
  return `<div class="plan"><div>${esc(p.heads)}<div class="muted" style="font-size:13px">${verdict}｜功率比 ${Math.round(p.ratio * 100)}%</div></div>
    <div class="meter ${cls}" title="功率比 ${Math.round(p.ratio * 100)}%"><i style="width:${pct}%"></i></div><div class="s">${esc(p.summary)}</div></div>`;
}

// ================================================================ 矿物（搜索并进「物品」页，原来的「找矿点」页拆掉了）
PAGES.mine = () => { location.hash = "#item"; };
async function openMineral(en) {
  const sel = ++state.sel;                                  // 和物品查询共用选择序号：晚回来的互不覆盖（二审 2026-10-28）
  state.itemFrom = "";
  let m;
  try { m = await api("mineral_info", { name: en }); } catch (e) { if (sel === state.sel) toast(e.message); return; }
  if (sel !== state.sel) return;
  state.mineral = m;
  state.item = null;
  if (page !== "item") location.hash = "#item"; else drawMineral();
}
function mineNav(i) {                                       // 矿点的「导航」：Aaron Halo 进小行星带导航，别的去找地点搜它
  const r = state.mineral?.rows[i];
  if (!r) return;
  if (r.nav.kind === "halo") {
    state.halo = { ...(state.halo || { frm: "ARC-L1" }), band: r.nav.band, to: null };
    state.navTab = "halo";
  } else {
    state.navTab = "search"; state.navQuery = r.nav.q; state.navRows = null; state.plan = null;
  }
  location.hash = "#nav";
  if (page === "nav") renderPage();
}
function gateText(m) {                                      // 「其中 5 份要求品质 ≥800」（不写「你这块…」，2026-10-23 用户要求）
  const g = m.gates?.length ? `≥${m.gates.join("/≥")}` : "门槛";
  return `其中 ${m.gated} 份要求品质 ${g}`;
}
function resWarn(s) {                                       // 游戏画面高度低于 1080：识别准确率明显下降（2026-10-25 缩图实测：1080 高全对 80→66 / 90，720 高 22 / 90）
  const g = s?.game_size;
  if (!g || g[1] >= 1080) return "";
  return `<p class="note-warn" style="margin:0 0 12px">游戏画面 ${g[0]}×${g[1]}，高度低于 1080 时识别准确率明显下降。建议调大游戏窗口或使用无边框全屏</p>`;
}
function fbBtn(kind, label) {                                 // 「结果不对？报告问题」：截图 + OCR 原文 + 当时的结果打包到 userdata\feedback
  return `<button class="btn small" data-fb="${kind}" title="保存当前截图、识别文字和结果并发给作者">${label || "报告问题"}</button>`;
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-fb]");
  if (!b) return;
  popconfirm(b, { title: "报告问题", okText: "发送", body: `<input class="input" id="fb-note" placeholder="问题描述（选填）" style="width:100%">`,
    onOk: async (pop) => {                                       // 不用浏览器 prompt（DESIGN §5，2026-10-28 审查）
      const note = (pop.q("#fb-note")?.value || "").trim();
      b.disabled = true;
      try { const r = await api("feedback_report", { kind: b.dataset.fb, note }); toast(r.upload ? "已保存，正在发送给作者" : `已保存（${r.kb} KB），共 ${r.count} 条，可在设置页「问题反馈」导出`); }
      catch (err) { toast(err.message); } finally { b.disabled = false; }
    } });
});
function qtyText(qty, unit) {                                   // 0.495 SCU / 200 个 / 495,000 uSCU
  if (qty == null || qty === "") return "";
  return unit === "uSCU" ? `${money(qty)} uSCU` : `${qty} ${unit || "个"}`;
}
function goalBox(lines, good) {                             // 目标还缺的材料：醒目标出来（扫描、物品、矿物页共用）
  lines = (lines || []).filter(Boolean);
  if (!lines.length) return "";
  return `<div style="margin-top:12px;padding:10px 12px;border:1px solid var(--amber);border-radius:var(--r-sm);background:rgba(255,209,102,.05)">
    ${lines.map((l) => `<div style="font-weight:600">${esc(l)}</div>`).join("")}
    <div class="muted" style="font-size:12.5px;margin-top:4px">来自「目标清单」${good ? "，品质已达标" : ""}</div></div>`;
}
function craftMatBtn(m) {                                   // 「这种矿能做 N 份蓝图」→ 制造页按这种矿筛选
  const ok = m.gated ? "，" + gateText(m) : "";
  return `<button class="btn small" style="margin:0 6px 6px 0" data-craftmat="${esc(m.en)}" data-q="${m.q ?? ""}" data-zh="${esc(m.zh)}">${esc(m.zh)}：可制造 ${m.count} 份蓝图${ok} →</button>`;
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-craftmat]");
  if (!b) return;
  state.craftMat = { en: b.dataset.craftmat, zh: b.dataset.zh, q: b.dataset.q === "" ? null : +b.dataset.q };
  if (page === "craft") renderPage(); else location.hash = "#craft";
});
function drawMineral() {
  const box = $("#iout"), m = state.mineral;
  if (!box || !m) return;
  document.querySelectorAll("#ilist button").forEach((b) => b.classList.toggle("on", b.dataset.m === m.en));
  box.innerHTML = `<div class="panel"><div class="item-head"><span class="name">${esc(m.zh)}</span><span class="muted">${esc(m.en)}</span><span class="tag">${m.gem ? esc(m.gem.kind) : "矿物"}${m.rarity ? "｜" + esc(m.rarity) : ""}</span><span style="margin-left:auto"><button class="btn small" id="to-stock" title="在库存页入库此矿物">入库</button></span></div>
    ${m.gem ? `<p class="muted" style="margin:0">信号 ${money(m.gem.rs)} / 块｜终端价 ${m.gem.price ? `<span class="money">${money(m.gem.price)}</span> aUEC/个` : "暂无"}｜共 ${m.total} 个地点</p>
    <p class="muted" style="margin:4px 0 0">不稳定性 ${esc(m.gem.inst)}｜抗性 ${esc(m.gem.res)}</p>${goalBox([m.goal])}</div>`
    : `<p class="muted" style="margin:0">精炼后 <span class="money">${money(m.price)}</span> /SCU（${esc(m.city || "无收购")}）｜共 ${m.total} 个地点</p>
    ${goalBox([m.goal])}
    <p class="muted" style="margin:4px 0 0">${m.refine.length ? `精炼加成最高：${m.refine.map((r) => `${esc(r.station)} <span class="good">+${r.bonus}%</span>`).join("，")}` : "无可用精炼加成"}</p></div>`}
    <div class="panel"><h3 style="margin-top:0">开采地点<small class="muted" style="font-weight:400">｜按出现概率排序，数据来自 SCMiner</small></h3>
      ${m.rows.map((r, i) => `<div class="route" style="align-items:center"><span class="tag" style="min-width:44px;text-align:center">${Math.round(r.pct)}%</span>
        <span>${esc(r.place)}<div class="muted" style="font-size:12.5px">${esc(r.system)}｜${esc(r.kind)}${r.also.length ? `｜伴生：${esc(r.also.join("、"))}` : ""}</div></span>
        <span class="b">${r.nav.kind === "none" ? `<span class="faint" style="font-size:12.5px;font-weight:400;white-space:nowrap">${esc(r.nav.hint)}</span>` : r.nav.kind === "hint" ? `<span class="faint" style="font-size:12.5px;font-weight:400;white-space:nowrap" title="${esc(r.nav.hint)}">在星图中量子跳跃</span>` : `<button class="btn" data-mnav="${i}" title="${esc(r.nav.hint)}">${r.nav.kind === "halo" ? `小行星带导航（第${r.nav.band}带）` : "导航"}</button>`}</span></div>`).join("")
        || `<p class="muted">SCMiner 没有此矿物的开采地点</p>`}</div>
    ${m.craft_count ? `<div class="panel"><h3 style="margin-top:0">制造</h3>${craftMatBtn({ en: m.en, zh: m.zh, count: m.craft_count, q: null })}${m.uses ? linesHTML(m.uses) : ""}</div>` : m.uses ? `<div class="panel">${linesHTML(m.uses)}</div>` : ""}`;
  box.onclick = (e) => {
    if (e.target.closest("#to-stock")) { state.stockPrefill = { en: m.en, zh: m.zh, kind: "矿物", unit: "SCU", source: "物品查询" }; location.hash = "#stock"; return; }
    const b = e.target.closest("button[data-mnav]"); if (b) mineNav(+b.dataset.mnav);
  };
}

// ================================================================ 制造
PAGES.craft = () => {
  // 蓝图字典：按类别 / 子类 / 部位 / 厂商筛选，点一份看要什么材料；也能直接搜名字
  const f = (state.cb = state.cb || { cat: "", sub: "", part: "", maker: "", q: "", unlocked: false, mat: "", mq: null });
  if (state.craftMat) {                // 从扫描结果 / 矿物页点「可制造 N 份蓝图」过来：只按这种矿筛
    f.cat = f.sub = f.part = f.maker = f.q = ""; f.unlocked = false;
    f.mat = state.craftMat.en; f.mq = state.craftMat.q; state.craftMat = null;
  }
  if (state.craftJump) {               // 从别处点「制造」跳过来：清掉所有筛选（包括「只看默认已解锁」），只按名字搜
    f.cat = f.sub = f.part = f.maker = f.mat = ""; f.mq = null; f.unlocked = false; f.q = state.craftJump.replace(/#\d+$/, ""); state.craftJump = null;
  }
  $("#page").innerHTML = `<h1>制造</h1><p class="lede">查看蓝图所需材料、品质对属性的影响和蓝图来源任务。可按类别筛选或搜索名称。</p>
    <div class="row"><input class="input" id="cq" placeholder="例：P4-AR / 头盔 / Arrowhead" style="width:320px"><button class="btn primary" id="cgo">搜索</button>
      <label class="field" style="flex-direction:row;align-items:center;gap:6px"><input type="checkbox" id="cun">只看默认已解锁</label></div>
    <div class="row" id="cmat" style="margin-top:12px;gap:8px"></div>
    <div class="row" id="ccats" style="margin-top:12px;flex-wrap:wrap;gap:6px"></div>
    <div class="row" id="cfil" style="margin-top:10px;gap:10px"></div>
    <div class="split" style="margin-top:14px"><div><p class="muted" id="ccount" style="margin:0 0 6px"></p><div class="list" id="clist"></div>
      <button class="btn small" id="cmore" style="margin-top:8px;display:none">加载更多</button></div><div id="cout" class="sticky"></div></div>
    ${mixHTML()}`;
  mixInit();
  $("#cq").value = f.q; $("#cun").checked = f.unlocked;
  let shown = 0, batch = 0, busy = false;      // batch：筛选一变就换一批，晚回来的旧请求直接丢掉
  const sel = (id, label, items, val) => items.length > 1 || val
    ? `<label class="field" style="flex-direction:row;align-items:center;gap:6px">${label}<select class="input" id="${id}"><option value="">全部</option>${items.map((x) => `<option value="${esc(x.key)}"${x.key === val ? " selected" : ""}>${esc(x.label)}（${x.count}）</option>`).join("")}</select></label>` : "";
  const row = (r) => `<button data-k="${esc(r.key)}"${r.key === state.craftKey ? ' class="on"' : ""}><span>${esc(r.name)}</span><span class="${r.ok === false ? "tag noqt" : r.ok ? "tag qt" : "faint"}">${r.ok === false ? "品质未达标" : r.ok ? "品质达标" : esc(r.kind)}</span><span class="l2">${r.need ? esc(r.need) + " · " : ""}${esc([r.tags, r.maker].filter(Boolean).join(" · "))}${r.unlocked ? " · 默认已解锁" : ""}</span></button>`;
  const load = async (more) => {
    if (more && busy) return;                // 「加载更多」点两下：第二下不算（Codex 二审：会重复追加、跳过后面的）
    const my = more ? batch : ++batch, offset = more ? shown : 0;
    busy = true; $("#cmore").disabled = true;
    let r;
    try { r = await api("craft_browse", { ...f, offset }); } finally { if (my === batch) { busy = false; $("#cmore").disabled = false; } }
    if (my !== batch || (more && offset !== shown)) return;
    if (!more) {
      $("#cmat").innerHTML = r.mat ? `<span class="tag qt" style="font-size:13px;padding:5px 10px">材料：${esc(r.mat.zh)}${r.mat.q != null ? ` · 品质 ${r.mat.q}` : ""}｜${r.mat.count} 份蓝图使用${r.mat.gated ? "，" + gateText(r.mat) : "，均无品质门槛"}</span><button class="btn small" id="cmatx">✕ 清除材料筛选</button>` : "";
      if ($("#cmatx")) $("#cmatx").onclick = () => { f.mat = ""; f.mq = null; load(); };
      $("#ccats").innerHTML = [{ key: "", label: "全部", count: r.cats.reduce((a, c) => a + c.count, 0) }, ...r.cats]
        .map((c) => `<button class="btn small${c.key === f.cat ? " primary" : ""}" data-cat="${esc(c.key)}">${esc(c.label)} <span class="faint">${c.count}</span></button>`).join("");
      $("#cfil").innerHTML = sel("csub", "子类", r.subs, f.sub) + sel("cpart", "部位", r.parts, f.part) + sel("cmaker", "厂商", r.makers, f.maker);
      ["csub", "cpart", "cmaker"].forEach((id) => { const e = $("#" + id); if (e) e.onchange = () => { f[{ csub: "sub", cpart: "part", cmaker: "maker" }[id]] = e.value; if (id === "csub") f.part = f.maker = ""; if (id === "cpart") f.maker = ""; load(); }; });
      $("#clist").innerHTML = "";
      shown = 0;
    }
    $("#clist").insertAdjacentHTML("beforeend", r.rows.map(row).join("") || (shown ? "" : `<p class="empty">没有符合条件的蓝图</p>`));
    shown += r.rows.length;
    $("#ccount").textContent = `共 ${r.total} 份蓝图` + (r.total > shown ? `，显示前 ${shown} 份` : "");
    $("#cmore").style.display = r.total > shown ? "" : "none";
  };
  const search = () => { f.q = $("#cq").value; load(); };
  $("#cgo").onclick = search;
  $("#cq").onkeydown = (e) => { if (e.key === "Enter") search(); };   // 只管回车，别的键（退格、删除、方向键）照常
  $("#cun").onchange = () => { f.unlocked = $("#cun").checked; load(); };
  $("#ccats").onclick = (e) => { const b = e.target.closest("button[data-cat]"); if (b) { f.cat = b.dataset.cat; f.sub = f.part = f.maker = ""; load(); } };
  $("#cmore").onclick = () => load(true);
  $("#clist").onclick = (e) => { const b = e.target.closest("button[data-k]"); if (b) showCraft(b.dataset.k, b); };
  load().then(() => state.craftKey && showCraft(state.craftKey));
};
async function showCraft(key, btn) {
  state.craftKey = key;
  document.querySelectorAll("#clist button").forEach((b) => b.classList.toggle("on", b.dataset.k === key));
  try {
    const d = await api("craft_detail", { key });
    const h = d.head;
    $("#cout").innerHTML = `<div class="panel">
      <div class="row" style="justify-content:space-between;align-items:flex-start;gap:12px">
        <div><div style="font-size:17px;font-weight:600">${esc(h.zh || h.en)}</div>${h.zh ? `<div class="faint" style="font-size:12.5px">${esc(h.en)}</div>` : ""}
          <div class="tagrow">${h.tags.map((t) => `<span class="tag${/^S\d/.test(t) ? " sz" : ""}">${esc(t)}</span>`).join("")}<span class="tag">${esc(h.kind)}</span>${h.maker ? `<span class="tag">${esc(h.maker)}</span>` : ""}<span class="tag">制造 ${Math.floor(h.sec / 60)} 分 ${h.sec % 60} 秒</span>${h.unlocked ? `<span class="tag qt">默认已解锁</span>` : ""}${h.note ? `<span class="tag noqt">${esc(h.note)}</span>` : ""}</div></div>
        <div class="row" style="gap:6px;flex-wrap:nowrap"><label class="field" style="flex-direction:row;align-items:center;gap:6px">制造数量<input class="input" id="gtimes" size="3" value="1"></label>
          <button class="btn small primary" onclick="goalAdd('craft', ${esc(JSON.stringify(d.key))}, $('#gtimes').value)">加入目标清单</button></div></div>
      <div class="row" style="justify-content:space-between;margin-top:14px"><b>材料槽位</b><span class="row" style="gap:6px"><span class="faint" style="font-size:12.5px">品质：</span>
        <button class="btn small" data-preset="min">最低</button><button class="btn small" data-preset="shop">商店品质 500</button><button class="btn small" data-preset="max">最佳</button></span></div>
      <div class="slots" id="cslots">${d.slots.map((sl) => slotCardHTML(sl, 500)).join("")}</div>
      <div id="cstats" style="margin-top:14px"></div>
      ${d.mine.length ? `<h3 style="margin:16px 0 6px;font-size:14px">开采地点</h3><table class="t">${d.mine.map((m) => `<tr><td><b>${esc(m.zh)}</b></td><td class="muted">${m.spots.map((x) => `${esc(x.loc)} ${x.pct}%`).join("，") || "SCMiner 没有开采地点"}</td><td class="n">精炼后 ${money(m.price)}/SCU${m.city ? `<div class="faint" style="font-size:12px">${esc(m.city)}</div>` : ""}</td></tr>`).join("")}</table>` : ""}
      ${d.sources.length ? `<h3 style="margin:16px 0 6px;font-size:14px">蓝图来源 <span class="faint" style="font-weight:400">${d.nsrc} 个任务${d.nsrc > d.sources.length ? `，列出前 ${d.sources.length} 个` : ""}</span></h3>
        <table class="t srcs">${d.sources.map((x) => `<tr><td><b>${esc(x.title)}</b><div class="faint" style="font-size:12px">${esc(x.who)}${x.kind ? " / " + esc(x.kind) : ""}</div></td><td class="muted">${esc(x.systems || "—")}</td><td class="n"><span class="chance">${x.chance >= 1 ? "必得" : `概率 ${Math.round(x.chance * 100)}%`}</span></td></tr>`).join("")}</table>`
        : h.unlocked ? "" : `<p class="faint" style="margin:12px 0 0">蓝图来源：任务数据中未找到</p>`}</div>`;
    bindSlots($("#cslots"), d.slots, (qs) => craftStatsDraw($("#cstats"), d.key, qs));
    $("#cout").querySelectorAll("[data-preset]").forEach((b) => (b.onclick = () => slotsPreset($("#cslots"), d.slots, b.dataset.preset)));
    craftStatsDraw($("#cstats"), d.key, slotQualities($("#cslots")));
    mixPresets(d.mix || []);
  } catch (e) { $("#cout").innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
// ---- 材料槽位卡片（制造页和目标页共用）：材料、用量、最低品质、品质滑块 + 数字框，底下即时显示这一槽的属性变化
function slotCardHTML(sl, q, label = "") {
  const qv = q == null ? "" : Math.round(q);
  return `<div class="slot" data-i="${sl.idx}">
    <div class="sh"><b>${esc(sl.slot)}</b>${sl.minq > 1 ? `<span class="faint" style="font-size:12px">最低品质 ${sl.minq}</span>` : ""}</div>
    <div class="mat">${sl.mats.map((m, i) => `${i ? `<span class="k" style="grid-column:1/-1">或</span>` : ""}<span class="v">${esc(m.zh)}${m.zh !== m.en ? ` <span class="faint" style="font-weight:400">${esc(m.en)}</span>` : ""}</span><span><span class="k">${esc(m.unit)}</span> <b>${+m.qty.toFixed(3)}</b>${m.unit === "SCU" ? `<span class="faint" style="font-size:11.5px"> · ${Math.round(m.qty * 100)} cSCU</span>` : ""}</span><span><span class="k">最低品质</span> ${m.minq}</span>`).join("")}</div>
    ${sl.curves.length ? `<div class="qrow"><span class="faint" style="font-size:12px">品质</span><button class="btn small sq-dn" type="button">−</button><input type="range" class="sq-r" min="0" max="1000" step="1" value="${qv === "" ? 500 : qv}"><button class="btn small sq-up" type="button">+</button><input class="input sq-n" value="${qv}" placeholder="500"></div>
      <div class="fx"></div>${label ? `<div class="faint" style="font-size:12px;margin-top:4px">${esc(label)}</div>` : ""}`
      : `<div class="faint" style="font-size:12.5px;margin-top:8px">此槽位的品质不影响属性</div>`}</div>`;
}
function slotQualities(box) {
  const qs = {};
  box.querySelectorAll(".slot").forEach((c) => { const n = c.querySelector(".sq-n"); if (n && n.value.trim() !== "") qs[c.dataset.i] = n.value.trim(); });
  return qs;
}
function bindSlots(box, slots, onChange) {
  let timer = null;
  const fire = () => { clearTimeout(timer); timer = setTimeout(() => onChange(slotQualities(box)), 120); };
  box.querySelectorAll(".slot").forEach((c) => {
    const r = c.querySelector(".sq-r"), n = c.querySelector(".sq-n");
    if (!r) return;
    const set = (v) => { v = Math.max(0, Math.min(1000, Math.round(+v) || 0)); r.value = v; n.value = v; fire(); };
    r.oninput = () => { n.value = r.value; fire(); };
    n.onchange = () => set(n.value);
    n.onkeydown = (e) => { if (e.key === "Enter") set(n.value); };
    c.querySelector(".sq-dn").onclick = () => set(+r.value - 1);
    c.querySelector(".sq-up").onclick = () => set(+r.value + 1);
  });
}
function slotsPreset(box, slots, which) {
  box.querySelectorAll(".slot").forEach((c) => {
    const r = c.querySelector(".sq-r"), n = c.querySelector(".sq-n");
    if (!r) return;
    const sl = slots.find((s) => s.idx === +c.dataset.i);
    const v = which === "max" ? 1000 : which === "min" ? Math.max(1, sl ? sl.minq : 1) : which === "shop" ? 500 : (sl && sl.q != null ? sl.q : 500);
    r.value = v; n.value = v;
  });
  const first = box.querySelector(".sq-n"); if (first) first.dispatchEvent(new Event("change"));
}
async function craftStatsDraw(out, key, qs) {
  try {
    const r = await api("craft_stats", { key, qualities: qs });
    const box = out.closest(".panel") || document;
    r.slots.forEach((e) => {                                    // 每个槽卡片底下：这一槽的属性变化
      const fx = box.querySelector(`.slot[data-i="${e.idx}"] .fx`);
      if (!fx) return;
      fx.innerHTML = e.props.map((p) => { const pct = p.text.startsWith(p.name) ? p.text.slice(p.name.length).trim() : p.text; const cls = /^\+0(\.0+)?%?/.test(pct) ? "flat" : pct.startsWith("+") ? "up" : pct.startsWith("-") ? "down" : "flat";
        return `<div><span>${esc(p.name)}</span><span class="${cls}">${esc(pct)}</span></div>${p.next_gate ? `<div class="quality-hint">品质达到 ${p.next_gate} 时属性提升</div>` : ""}`; }).join("")
        + (e.minq && !e.ok ? `<div class="quality-hint">低于品质门槛 ${e.minq}，无法制造</div>` : "");
    });
    out.innerHTML = statsTableHTML(r.stats);
  } catch (e) { out.innerHTML = `<p class="bad">${esc(e.message)}</p>`; }
}
function statsTableHTML(st) {
  if (!st.props.length) return `<p class="faint" style="margin:0">此蓝图的材料品质不影响成品属性</p>`;
  const fmt = (v, unit) => v == null ? "—" : `${Math.abs(v) >= 1000 ? money(Math.round(v)) : +(+v).toFixed(2)}${esc(unit || "")}`;
  const hasBase = st.props.some((p) => p.base != null);
  return `<div class="row" style="justify-content:space-between"><b>属性统计</b>${st.missing.length ? `<span class="faint" style="font-size:12px">${esc(st.missing.join("、"))}未填写品质，按 500 计算</span>` : ""}</div>
    <table class="t stats" style="margin-top:6px"><tr><th>属性</th>${hasBase ? `<th class="n">基础属性</th><th class="n">强化属性</th>` : ""}<th class="n">变化</th><th>来源</th></tr>
    ${st.props.map((p) => { const up = p.lower ? p.delta < 0 : p.delta > 0, cls = Math.abs(p.delta) < 1e-9 ? "" : up ? "up" : "down";
      return `<tr><td>${esc(p.name)}${p.lower ? `<span class="faint" style="font-size:11.5px"> 越低越好</span>` : ""}</td>
        ${hasBase ? `<td class="n">${fmt(p.base, p.unit)}</td><td class="n ${cls}">${p.base == null ? `<span class="faint">暂无数据</span>` : fmt(p.now, p.unit)}</td>` : ""}
        <td class="n ${cls}">${esc(p.text)}</td><td class="faint" style="font-size:12px">${p.slots.map((s) => `${esc(s.slot)} ${p.add ? (s.part >= 0 ? "+" : "") + s.part : (s.part * 100 >= 0 ? "+" : "") + (s.part * 100).toFixed(2) + "%"}`).join(" + ")}${p.slots.length > 1 ? "（相加）" : ""}</td></tr>`; }).join("")}</table>
    ${hasBase ? "" : `<p class="faint" style="font-size:12px;margin:6px 0 0">暂无基础属性数据，仅显示材料带来的变化</p>`}`;
}

// ---------------------------------------------------------------- 混料计算器
// 同一种材料投几箱不同品质：成品这一项的品质 = 按 SCU 加权平均。只要过线的东西用低料打底、补最少的高料；
// 也能算几箱合成一箱后的品质（开工后立刻取消，材料按混合后的品质整箱退回——当前版本的行为，先小量试）
function mixHTML() {
  return `<div class="panel" id="mix" style="margin-top:18px">
    <h3 style="margin:0 0 4px">混料计算器</h3>
    <p class="muted" style="margin:0 0 12px">成品品质 = 各箱材料「品质 × 投入量」之和 ÷ 总投入量。
      只需达到门槛时（例如电源品质 900 增加一格能量），先投入低品质材料，再补充最少的高品质材料。不填目标品质时，计算多箱合并后的品质。</p>
    <div id="mixpre" class="row" style="margin-bottom:10px"></div>
    <div class="row">
      <label class="field">所需 SCU<input class="input" id="mneed" size="7" placeholder="0.14"></label>
      <label class="field">件数<input class="input" id="mcount" size="3" value="1"></label>
      <label class="field">目标品质<input class="input" id="mtarget" size="6" placeholder="900"></label>
      <label class="field">余量<input class="input" id="mmargin" size="3" value="2"></label>
    </div>
    <h3 style="margin:14px 0 6px;font-size:14px">现有材料（每箱一行）</h3>
    <div id="mboxes"></div>
    <div class="row" style="margin-top:8px"><button class="btn" id="madd">添加一箱</button><button class="btn primary" id="mgo">计算</button></div>
    <div id="mout" style="margin-top:12px"></div></div>`;
}
function mixBoxRow(q = "", s = "") {
  return `<div class="row mbox" style="margin-bottom:6px"><input class="input mq" size="6" placeholder="品质" value="${esc(q)}">
    <input class="input ms" size="7" placeholder="SCU" value="${esc(s)}"><span class="faint">品质 · SCU</span></div>`;
}
function mixInit() {
  $("#mboxes").innerHTML = mixBoxRow() + mixBoxRow();
  $("#madd").onclick = () => $("#mboxes").insertAdjacentHTML("beforeend", mixBoxRow());
  $("#mgo").onclick = mixGo;
  $("#mix").addEventListener("keydown", (e) => { if (e.key === "Enter") mixGo(); });
}
function mixPresets(list) {
  const el = $("#mixpre");
  if (!el) return;
  const btns = [];
  list.forEach((m) => {
    if (!m.steps.length) btns.push({ m, q: "", text: `${m.zh} ${m.scu} SCU` });
    m.steps.slice(-2).forEach((st) => btns.push({ m, q: st.q, text: `${m.zh} ${m.scu} SCU → ≥${st.q}（${st.text}）` }));   // 只列最高两档
  });
  el.innerHTML = btns.length ? `<span class="faint">此蓝图：</span>` + btns.map((b, i) => `<button class="btn" data-i="${i}" style="font-size:12.5px;padding:5px 9px">${esc(b.text)}</button>`).join("") : "";
  el.onclick = (e) => {
    const b = e.target.closest("[data-i]");
    if (!b) return;
    const p = btns[+b.dataset.i];
    $("#mneed").value = p.m.scu; $("#mtarget").value = p.q; $("#mcount").value = 1;
    document.querySelector("#mboxes .mq")?.focus();
  };
}
async function mixGo() {
  const num = (id) => parseFloat($(id).value) || 0;
  const need = num("#mneed") * Math.max(1, Math.min(6, Math.round(num("#mcount")) || 1));
  const boxes = [...document.querySelectorAll("#mboxes .mbox")].map((r) => [r.querySelector(".mq").value.trim(), r.querySelector(".ms").value.trim()]).filter(([q, s]) => q && s);
  const r = await api("craft_mix", { need, target: num("#mtarget"), margin: num("#mmargin"), boxes });
  if (!r.ok) { $("#mout").innerHTML = `<p class="bad">${esc(r.msg)}</p>`; return; }
  const goal = r.goal;
  $("#mout").innerHTML = `<p style="margin:0 0 8px"><b>${esc(r.msg)}</b></p>
    <table class="t"><tr><th>投料顺序</th><th class="n">品质</th><th class="n">现有</th><th class="n">投入</th></tr>
    ${r.plan.map((p, i) => `<tr><td>${i + 1}${goal && p.q >= goal ? " · 高品质" : ""}</td><td class="n">${p.q}</td><td class="n">${+p.have.toFixed(3)}</td><td class="n money">${p.use > 0 ? +p.use.toFixed(3) : "不投入"}</td></tr>`).join("")}</table>
    <p class="faint" style="margin:8px 0 0;font-size:12.5px">${goal ? "先投入低品质，再投入高品质；投入后确认制造机显示的品质再开始制造。" : "合并：多箱材料一起投入，开始制造后立即取消，材料按混合后的品质整箱退回（当前游戏版本的机制，建议先用少量测试）。"}</p>`;
}
function openCraft(key) { state.craftKey = key; state.craftJump = key; if (page === "craft") renderPage(); else location.hash = "#craft"; }

// ================================================================ 导航
PAGES.nav = () => {
  const tab = state.navTab || "search";
  $("#page").innerHTML = `<h1>导航</h1><p class="lede">前往没有量子信标的地点：先量子跳跃到最近的信标，再按方位飞行。需先在游戏控制台（~ 键）输入 r_DisplayInfo 2，AT 从屏幕右上角识别实时位置。</p>
    <div id="navlive"></div>
    <div class="seg" style="margin:6px 0 16px"><button data-tab="search" class="${tab === "search" ? "on" : ""}">搜索地点</button><button data-tab="wp" class="${tab === "wp" ? "on" : ""}">我的路标</button><button data-tab="halo" class="${tab === "halo" ? "on" : ""}">小行星带</button></div>
    <div id="navbody"></div>`;
  document.querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => { state.navTab = b.dataset.tab; renderPage(); }));
  renderNavLive();
  if (tab === "search") navSearchView(); else if (tab === "halo") navHaloView(); else navWaypointView();
};

// ---------------------------------------------------------------- 小行星带（Aaron Halo，照 SCMiner 的 Flight Computer）
const gmText = (v) => `${v.toFixed(1)} Gm`;          // 挖矿用，精确到 0.1 Gm 就够
async function navHaloView() {
  const box = $("#navbody");
  const seq = (navHaloView.seq = (navHaloView.seq || 0) + 1);
  const still = () => navHaloView.seq === seq && page === "nav" && state.navTab === "halo" && box.isConnected;   // 等接口期间切走了就别画
  let o;
  try { o = state.haloOpt || (state.haloOpt = await api("halo_options")); }
  catch (e) { if (still()) box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; return; }
  if (!still()) return;
  const h = state.halo || (state.halo = { frm: "ARC-L1", band: 5, to: null });
  box.innerHTML = `<div class="panel">
      <p class="muted" style="margin:0 0 12px">Aaron Halo 是环绕斯坦顿恒星的 10 条小行星带（距恒星 19.67–21.30 Gm）。选择出发点和目标带后，AT 计算量子跳跃的目标，以及剩余距离为多少时按 U 退出，即可停在该带内。数据和算法来自 SCMiner。</p>
      <div class="row" style="gap:10px;flex-wrap:wrap">
        <label>出发点 <select class="input" id="hfrm">${o.points.map((p) => `<option value="${esc(p.key)}" ${p.key === h.frm ? "selected" : ""}>${esc(p.label)}</option>`).join("")}</select></label>
      </div>
      <div class="halo-bands" id="hbands">${o.bands.map((b) => `<button data-b="${b.band}" class="${b.band === h.band ? "on" : ""}" title="${esc(b.ores.join("、"))}">
          <b>第${b.band}带</b><span class="dens"><i style="width:${b.density}%"></i></span><span class="l2">密度 ${b.density}%<br>厚 ${b.thick} Mm</span></button>`).join("")}</div>
      <div id="hband" class="muted" style="margin-top:10px;font-size:13px"></div>
    </div>
    <div id="hwhere"></div>
    <div class="split" style="margin-top:16px"><div class="list" id="hroutes"><p class="faint">计算中…</p></div><div id="hplan"></div></div>`;
  $("#hfrm").onchange = () => { h.frm = $("#hfrm").value; h.to = null; loadHalo(); };
  $("#hbands").onclick = (e) => { const b = e.target.closest("button[data-b]"); if (!b) return; h.band = +b.dataset.b; h.to = null;
    document.querySelectorAll("#hbands button").forEach((x) => x.classList.toggle("on", x === b)); loadHalo(); };
  $("#hroutes").onclick = (e) => { const b = e.target.closest("button[data-to]"); if (b) { h.to = b.dataset.to; drawHaloRoutes(); } };
  drawHaloWhere();
  loadHalo();
}
async function loadHalo() {
  const h = state.halo;
  const want = `${h.frm}|${h.band}`;
  h.want = want;
  h.res = null;                                              // 旧结果立刻撤掉，免得把上一个选项的方案挂出去
  if ($("#hroutes")) { $("#hroutes").innerHTML = `<p class="faint">计算中…</p>`; $("#hplan").innerHTML = ""; }
  let r;
  try { r = await api("halo_routes", { frm: h.frm, band: h.band }); }
  catch (e) { if (h.want === want && $("#hroutes")) $("#hroutes").innerHTML = `<p class="empty">计算失败：${esc(e.message)}</p>`; return; }
  if (h.want !== want || !$("#hroutes")) return;            // 选得快：只画最后一次的结果
  h.res = r;
  if (!h.to && r.rows.length) h.to = r.rows.find((x) => !x.blocked)?.to || r.rows[0].to;
  const b = r.band;
  $("#hband").innerHTML = `第${b.band}带｜距恒星 ${b.lo}–${b.hi} Gm｜${esc(b.rating)}｜主要矿物：${esc(b.ores.join("、"))}`;
  drawHaloRoutes();
}
function drawHaloRoutes() {
  const h = state.halo, r = h.res;
  if (!r || !$("#hroutes")) return;
  $("#hroutes").innerHTML = r.rows.length ? `<p class="faint" style="padding:4px 12px">${r.rows.length} 个目标的航线穿过第${r.band.band}带，按安全窗口从宽到窄排序</p>` + r.rows.map((x) => `<button data-to="${esc(x.to)}" class="${x.to === h.to ? "on" : ""}">
      <span>${esc(x.to_zh)}</span><span class="tag ${x.blocked ? "noqt" : x.wide ? "qt" : "noqt"}">${x.blocked ? "被恒星遮挡" : x.wide ? "窗口宽" : "窗口窄"}</span>
      <span class="l2">剩余约 ${gmText(x.dropout)} 时退出</span></button>`).join("")
    : `<p class="empty">从此出发点没有航线穿过第${r.band.band}带，换一个出发点</p>`;
  const x = r.rows.find((y) => y.to === h.to);
  const plan = state.haloOpt?.plan;
  $("#hplan").innerHTML = !x ? "" : `<div class="panel">
    <div class="item-head"><span class="name">${esc(x.from_zh)} → ${esc(x.to_zh)}</span><span class="tag ${x.wide ? "qt" : "noqt"}">第${x.band}带</span></div>
    <p class="muted" style="margin:0">HUD 上 ${esc(x.to_zh)} 的剩余距离</p>
    <div style="font-size:40px;font-weight:700;margin:4px 0">${gmText(x.dropout)}</div>
    <p class="muted" style="margin:0 0 10px">剩余 ${gmText(x.early)} 至 ${gmText(x.late)} 之间退出均在带内｜${x.wide ? "窗口宽" : "窗口窄，需及时退出"}</p>
    ${x.blocked ? `<p style="color:var(--amber)">⚠️ 此航线距恒星中心仅 ${x.star} Gm，量子跳跃可能被恒星阻挡，建议更换目标</p>` : ""}
    <h3>步骤</h3>
    <ol style="margin:0 0 8px 18px;padding:0;line-height:1.8">
      <li>在 ${esc(x.from_zh)} 选择 ${esc(x.to_zh)}，充能后量子跳跃</li>
      <li>注意 HUD 上 ${esc(x.to_zh)} 的剩余距离</li>
      <li>显示 <b>${gmText(x.dropout)}</b> 左右按 <kbd>U</kbd>（或关闭量子驱动器）退出</li>
      <li>断开后 AT 读右上角位置，自动核对是否位于第${x.band}带内（读不到时在聊天框输入 /showlocation）</li>
    </ol>
    <p class="muted" style="font-size:13px">提示：宁早勿晚，提前退出后再补跳一小段</p>
    <div class="row" style="margin-top:12px"><button class="btn primary" id="hpin">挂到悬浮窗</button>${plan ? `<button class="btn" id="hunpin">从悬浮窗移除</button>` : ""}</div></div>`;
  if (!x) return;
  $("#hpin").onclick = async () => {
    if (!h.res || x.from !== h.frm || x.band !== h.band) { toast("选项已更改，等待新结果计算完成"); return; }
    try { const p = await api("halo_pin", { frm: x.from, to: x.to, band: x.band }); state.haloOpt.plan = p; drawHaloRoutes(); toast("已挂到悬浮窗"); }
    catch (e) { toast(e.message); }
  };
  if ($("#hunpin")) $("#hunpin").onclick = async () => { await api("halo_unpin"); state.haloOpt.plan = null; drawHaloRoutes(); toast("已移除"); };
}
function drawHaloWhere() {
  const box = $("#hwhere"), w = state.haloWhere;
  if (!box) return;
  box.innerHTML = w ? `<div class="panel" style="margin-top:12px"><b>上一次定位</b>${esc(w.text).split("\n").map((l) => `<p style="margin:4px 0">${l}</p>`).join("")}</div>` : "";
}

function navSearchView() {
  $("#navbody").innerHTML = `<div class="row"><input class="input" id="nq" placeholder="例：戴玛尔 洞穴 / Kudre / 残骸 耶拉" style="width:340px"><button class="btn primary" id="ngo">搜索</button>
    <button class="btn" data-near="医院">医院</button><button class="btn" data-near="空港">空港</button><button class="btn" data-near="买船">买船</button></div>
    <div id="nsite"></div>
    <div class="split" style="margin-top:16px"><div class="list" id="nlist"></div><div id="nplan"></div></div>`;
  // 医院 / 空港 / 买船：知道位置就直接导航到最近的，列表按远近排（2026-10-27）
  const near = async (kind) => {
    try {
      const r = await api("nav_near", { kind });
      state.navRows = r;
      listPlaces(r);
      if (r.started) { await showPlan(r.started); toast(`已开始导航：最近的${kind}`); }
      else if (r.error) toast(r.error);
      else if (r.rows.length) toast("当前位置未知，需从列表中选择");
    } catch (e) { toast(e.message); }
  };
  document.querySelectorAll("#navbody [data-near]").forEach((b) => b.onclick = () => near(b.dataset.near));
  // 主城 / 空间站导航：分类按钮常驻；在主城 / 空间站里点一下去最近的，不在就提示（2026-10-27 老大定）
  const SITE_ALL = ["取船", "交易", "货梯", "医院", "武器", "护甲", "服装", "部件", "吃喝", "精炼", "行政", "罚款", "租船", "买船", "地铁"];
  const site = async () => {
    const box = $("#nsite");
    if (!box) { clearInterval(state.navSiteTimer); state.navSiteTimer = null; return; }
    let r = null;
    try { r = await api("nav_site"); } catch (e) { r = null; }
    const all = (r && r.all) || SITE_ALL, have = (r && r.site && r.kinds) || [];
    const key = (r && r.site ? r.site : "") + "|" + have.join(",");
    if (box.dataset.k === key) return;
    box.dataset.k = key;
    box.innerHTML = `<div class="row" style="margin-top:10px;flex-wrap:wrap;gap:6px"><span class="muted" style="margin-right:6px">${r && r.site ? esc(r.name) : "主城 / 空间站"}</span>
      ${all.map((k) => `<button class="btn" data-site="${esc(k)}"${r && r.site && !have.includes(k) ? ' style="opacity:.45"' : ""}>${esc(k)}</button>`).join("")}</div>`;
    box.querySelectorAll("[data-site]").forEach((b) => b.onclick = () => {
      if (!(r && r.site)) { toast("当前不在主城或空间站内，进入后可用"); return; }
      if (!have.includes(b.dataset.site)) { toast(`此处没有${b.dataset.site}`); return; }
      near(b.dataset.site);
    });
  };
  site();
  clearInterval(state.navSiteTimer);
  state.navSiteTimer = setInterval(site, 4000);
  const go = async () => {
    const r = await api("nav_search", { q: $("#nq").value });
    state.navRows = r;
    listPlaces(r);
  };
  $("#ngo").onclick = go;
  $("#nq").onkeydown = (e) => { if (e.key === "Enter") go(); };   // 只管回车，别的键（退格、删除、方向键）照常
  $("#nlist").onclick = (e) => { const b = e.target.closest("button[data-k]"); if (b) showPlan(b.dataset.k); };
  if (state.navQuery) $("#nq").value = state.navQuery;
  if (state.navQuery && !state.navRows) go();               // 从矿物页点「导航」过来：自动搜这个地方
  if (state.navRows) listPlaces(state.navRows);
  if (state.plan) drawPlan(state.plan);
}
function listPlaces(r) {
  $("#nlist").innerHTML = r.rows.map((p) => `<button data-k="${esc(p.key)}"><span>${esc(p.label)}</span><span class="tag ${p.has_qt ? "qt" : "noqt"}">${p.has_qt ? "有信标" : "无信标"}</span><span class="l2">${esc(p.body)}｜${esc(p.type)}${p.dist != null ? "｜" + km(p.dist / 1000) : ""}</span></button>`).join("")
    + (r.total > r.rows.length ? `<p class="faint" style="padding:6px 12px">共 ${r.total} 个，可添加关键词（例如星球名）缩小范围</p>` : "")
    || `<p class="empty">未找到。可尝试其他地名或星球名</p>`;
}
// 升级进度条（2026-10-27）：看升级记录的每一行——「正在下载」「已下载 45%（…）」「下载完成」「已下载 AT x，AT 将关闭…」「❌ …」
function upgProgress(line) {
  const box = document.getElementById("upg-prog");
  if (!box) return;
  const t = $("#upg-prog-t"), p = $("#upg-prog-p"), bar = box.querySelector(".meter"), fill = bar.querySelector("i");
  const set = (text, pct, cls = "") => {
    box.hidden = false; t.textContent = text; bar.className = "meter " + cls;
    if (pct != null) { fill.style.width = pct + "%"; p.textContent = pct + "%"; }
  };
  const m = /已下载 (\d+)%(?:（([^）]+)）)?/.exec(line || "");
  if (line === "开始") set("准备中", 0);
  else if (m) set(m[2] ? `正在下载（${m[2]}）` : "正在下载", +m[1]);
  else if (/正在下载/.test(line)) set("正在下载", null);
  else if (/下载完成|安装包已下载/.test(line)) set("下载完成，正在准备安装", 100);
  else if (/将关闭并自动安装|马上重启/.test(line)) set("正在安装，AT 会自动重新打开", 100);
  else if (/^❌/.test(line)) set("升级失败，详见下方记录", null, "no");
}

async function showPlan(key) {
  try { state.plan = await api("nav_plan", { key }); drawPlan(state.plan); } catch (e) { toast(e.message); }
}
function drawPlan(p) {
  document.querySelectorAll("#nlist button").forEach((b) => b.classList.toggle("on", b.dataset.k === p.key));
  const box = $("#nplan");
  if (!box) return;
  if (p.space) {
    box.innerHTML = `<div class="panel"><div class="item-head"><span class="name">${esc(p.label)}</span><span class="tag noqt">太空路标</span></div>
      <p class="muted" style="margin:0 0 12px">${esc(p.body)}｜太空中没有南北方向，导航时显示直线距离、对准的标记和偏差角度</p>
      <h3>先量子跳跃到最近的参照点</h3>
      ${p.routes.map((r) => `<div class="route"><span class="tag">${esc(r.kind)}</span><span>${esc(r.name)}<div class="muted" style="font-size:12.5px">距目标 ${km(r.direct)}</div></span><span class="b"></span></div>`).join("")}
      <div class="row" style="margin-top:14px"><button class="btn primary" id="nstart">开始导航</button></div></div>`;
    $("#nstart").onclick = async () => { try { await api("nav_start", { key: p.key }); toast("已开始导航"); } catch (err) { toast(err.message); } };
    return;
  }
  if (p.city) {
    box.innerHTML = `<div class="panel"><div class="item-head"><span class="name">${esc(p.label)}</span><span class="tag noqt">${esc(p.cat || p.type)}</span></div>
      <p class="muted" style="margin:0 0 12px">${esc(p.city_zh || p.body)}${p.area ? "｜" + esc(p.area) : ""}</p>
      <p>城内步行：显示直线方位、距离（米）和上下楼层。不在${esc(p.city_zh || p.body)}时先前往该城市</p>
      <div class="row" style="margin-top:14px"><button class="btn primary" id="nstart">开始导航</button></div></div>`;
    $("#nstart").onclick = async () => { try { await api("nav_start", { key: p.key }); toast("已开始导航"); } catch (err) { toast(err.message); } };
    return;
  }
  box.innerHTML = `<div class="panel"><div class="item-head"><span class="name">${esc(p.label)}</span><span class="tag ${p.has_qt ? "qt" : "noqt"}">${esc(p.qt)}</span></div>
    <p class="muted" style="margin:0 0 12px">${esc(p.body)}｜${esc(p.type)}｜纬度 ${p.lat.toFixed(3)}°，经度 ${p.lon.toFixed(3)}°，海拔约 ${money(p.alt)} m</p>
    ${p.has_qt ? `<p>此地点有量子信标，可在星图中选择后量子跳跃</p>` : ""}
    <h3>推荐路线</h3><p class="muted" style="margin:0 0 6px;font-size:13px">先量子跳跃到以下参照点，再按方位飞行</p>
    ${p.routes.map((r) => `<div class="route"><span class="tag">${esc(r.kind)}</span><span>${esc(r.name)}<div class="muted" style="font-size:12.5px">距目标 ${km(r.surface)}（直线 ${km(r.direct)}）</div></span><span class="b">${String(Math.round(r.bearing) % 360).padStart(3, "0")}° ${esc(r.compass)}</span></div>`).join("")}
    <div class="row" style="margin-top:14px"><button class="btn primary" id="nstart">开始导航</button></div></div>`;
  $("#nstart").onclick = async () => { try { await api("nav_start", { key: p.key }); toast("已开始导航"); } catch (err) { toast(err.message); } };
}

function compassSVG(deg) {
  const ticks = [];
  for (let a = 0; a < 360; a += 5) {
    const long = a % 30 === 0;
    const r1 = long ? 136 : 142, r2 = 150;
    const rad = (a - 90) * Math.PI / 180;
    ticks.push(`<line x1="${170 + r1 * Math.cos(rad)}" y1="${170 + r1 * Math.sin(rad)}" x2="${170 + r2 * Math.cos(rad)}" y2="${170 + r2 * Math.sin(rad)}" style="stroke:${long ? "var(--faint)" : "var(--edge)"}" stroke-width="${long ? 2 : 1}"/>`);
  }
  const labels = [["北", 0], ["东", 90], ["南", 180], ["西", 270]].map(([t, a]) => {
    const rad = (a - 90) * Math.PI / 180;
    return `<text x="${170 + 120 * Math.cos(rad)}" y="${170 + 120 * Math.sin(rad) + 5}" text-anchor="middle" style="fill:${a === 0 ? "var(--text)" : "var(--muted)"}" font-size="14" font-weight="400">${t}</text>`;
  }).join("");
  return `<svg viewBox="0 0 340 340" role="img" aria-label="方位 ${deg == null ? "未知" : Math.round(deg) + " 度"}">
    <circle cx="170" cy="170" r="160" style="fill:var(--panel);stroke:var(--line)"/>${ticks.join("")}${labels}
    ${deg == null ? "" : arcPath(deg)}
    <path d="M170 8 L178 22 L162 22 Z" style="fill:var(--muted)"/>
    <g class="needle" style="transform:rotate(${deg ?? 0}deg)">${deg == null ? "" : `<circle cx="170" cy="20" r="11" style="fill:var(--primary)"/><path d="M170 12 L176 24 L170 21 L164 24 Z" style="fill:var(--on-primary)"/>`}</g>
  </svg>`;
}

// 从正北顺时针扫到目标方位的一段弧，一眼看出要转多少
function arcPath(deg) {
  const r = 150, a = ((deg % 360) + 360) % 360;
  if (a < 0.5) return "";
  const rad = (a - 90) * Math.PI / 180;
  const x = 170 + r * Math.cos(rad), y = 170 + r * Math.sin(rad);
  return `<path d="M170 20 A${r} ${r} 0 ${a > 180 ? 1 : 0} 1 ${x} ${y}" fill="none" style="stroke:var(--text)" stroke-width="3" stroke-linecap="round" opacity=".35"/>`;
}

function navModeHTML(n) {
  // 实时 / 手动定位开关（2026-10-27：默认实时读右上角，/showlocation 只在必要时用）
  const cur = state.status?.settings?.nav_mode === "space" ? "space" : "ground";
  return `<div class="seg" id="navmode" title="实时定位：识别右上角调试信息；手动定位：在聊天框输入 /showlocation 更新距离和偏离角">
    <button class="${cur === "ground" ? "on" : ""}" data-mode="ground">实时定位</button>
    <button class="${cur === "space" ? "on" : ""}" data-mode="space">手动定位</button></div>`;
}
function bindNavMode() {
  const el = $("#navmode");
  if (el) el.onclick = async (e) => {
    const b = e.target.closest("button[data-mode]");
    if (!b || b.disabled) return;
    try { await api("nav_mode", { mode: b.dataset.mode }); state.status = await api("status"); renderNavLive(); toast(b.dataset.mode === "space" ? "已切换到手动定位" : "已切换到实时定位"); }
    catch (err) { toast(err.message); }
  };
}

function renderNavLive() {
  const box = $("#navlive");
  if (!box) return;
  const n = state.nav;
  if (!n || !n.active) { box.innerHTML = ""; return; }
  const h = n.here;
  if ((h && h.fix) || (!h && n.target && state.status?.nav_space)) {   // 手动定位：只用 /showlocation，不读屏
    const lines = h ? h.text.split("\n") : [];
    box.innerHTML = `<div class="panel" style="margin-bottom:18px">
      <div class="item-head"><span class="name">${esc(n.target.label)}</span><span class="muted">${esc(n.target.body)}</span><span style="margin-left:auto">${navModeHTML(n)}</span></div>
      ${(state.status?.hotkey_warn || []).filter((w) => /一键定位/.test(w)).map((w) => `<p style="margin:6px 0;color:var(--warn,#d9822b)">⚠️ ${esc(w)}</p>`).join("")}
      ${!h ? `<p style="margin:6px 0">${state.status?.settings?.fix_key ? `在游戏里按 <kbd>${esc(state.status.settings.fix_key)}</kbd>（AT 自动输入 /showlocation），或` : "在游戏"}聊天框输入 /showlocation 后回车。
          ${n.target.city ? "朝目标方向走一段" : "朝目标方向直线飞行一段"}后再按一次，即可计算偏离角度和预计到达时间。</p>`
        : h.arrived || h.far ? `<p class="${h.arrived ? "good" : ""}" style="font-size:20px;margin:6px 0">${esc(lines[0])}</p>`
        : `<div style="font-size:34px;font-weight:700;margin:6px 0">${esc(lines[0])}</div>
           ${lines.slice(1).map((l) => `<p style="margin:4px 0;font-size:${/偏离/.test(l) ? 20 : 15}px">${esc(l)}</p>`).join("")}`}
      <p class="navstat" style="margin-top:12px">${esc(n.status)}${n.at ? `｜${esc(n.at)} 更新` : ""}</p>
      <div class="row" style="margin-top:12px"><button class="btn stop" id="nstop">结束导航</button></div></div>`;
    $("#nstop").onclick = () => api("nav_stop");
    bindNavMode();
    return;
  }
  if (h && h.space) {           // 太空路标实时定位（读右上角）：没有罗盘，给距离 + 机头怎么转 / 对准哪个标记
    box.innerHTML = `<div class="panel" style="margin-bottom:18px">
      <div class="item-head"><span class="name">${esc(n.target.label)}</span><span class="muted">${esc(n.target.body)}</span><span style="margin-left:auto">${navModeHTML(n)}</span></div>
      ${h.far ? `<p style="margin:6px 0">${esc(h.far)}</p>` : h.arrived ? `<p class="good" style="font-size:20px;margin:6px 0">${h.city ? "已到达" : "已到达（1 km 以内）"}</p>`
        : h.close ? `<p style="font-size:20px;margin:6px 0">${esc(h.text)}</p>`
        : `<div style="font-size:34px;font-weight:700;margin:6px 0">${h.city ? `${money(h.direct_m)} m` : km(h.direct)}</div>
          ${h.city && Math.abs(h.updown || 0) > 4 ? `<p style="margin:4px 0">目标在${h.updown > 0 ? "上" : "下"}方 ${money(Math.abs(h.updown))} 米：找电梯${h.updown > 0 ? "上" : "下"}楼</p>` : ""}
          ${h.steer ? `<p style="font-size:22px;font-weight:600;margin:4px 0" class="money">${esc(h.steer.text)}</p>`
            : h.aim ? `<p style="margin:4px 0">对准「<b>${esc(h.aim.name)}</b>」的标记${h.aim.angle < 3 ? "，方向正确" : `，偏离 <b>${Math.round(h.aim.angle)}°</b>（距离减小即方向正确）`}</p>` : ""}
          ${h.qt ? `<p class="money" style="margin:6px 0">距离过远：先量子跳跃到 ${esc(h.qt.name)}（距目标 ${km(h.qt.km)}）</p>` : ""}`}
      <p class="navstat" style="margin-top:12px">${esc(n.status)}${n.at ? `｜${esc(n.at)} 更新` : ""}</p>
      <div class="row" style="margin-top:12px"><button class="btn" id="nrefresh">立即刷新位置</button><button class="btn stop" id="nstop">结束导航</button></div></div>`;
    $("#nstop").onclick = () => api("nav_stop");
    $("#nrefresh").onclick = () => api("nav_refresh");
    bindNavMode();
    return;
  }
  const deg = h && h.same_body && !h.station && !(h.city && (h.close || h.arrived)) ? h.bearing : null;   // 城里很近或到了、空间站里：不给方向
  const readout = !h ? `<div class="deg">—</div><div class="dir">等待位置信息…</div>`
    : !h.same_body ? `<div class="dir" style="max-width:200px;text-align:center">${esc(h.far)}</div>`
    : h.arrived ? `<div class="deg good">已到达</div><div class="dir">${h.city ? `${money(h.direct_m)} m` : "1 km 以内"}</div>`
    : h.station && !h.close ? `<div class="deg">${money(h.direct_m)} m</div>${Math.abs(h.updown) > 4 ? `<div class="dir">目标在${h.updown > 0 ? "上" : "下"}方 ${money(Math.abs(h.updown))} 米</div>` : ""}`
    : h.city && h.close ? `<div class="deg">就在附近</div><div class="dist">${money(h.direct_m)} m</div>${Math.abs(h.updown) > 4 ? `<div class="dir">目标在${h.updown > 0 ? "上" : "下"}方 ${money(Math.abs(h.updown))} 米</div>` : ""}`
    : `<div class="deg">${String(Math.round(h.bearing) % 360).padStart(3, "0")}°</div><div class="dir">${esc(h.compass)}</div><div class="dist">${h.city ? `${money(h.direct_m)} m` : km(h.surface)}</div>${h.city && Math.abs(h.updown) > 4 ? `<div class="dir">目标在${h.updown > 0 ? "上" : "下"}方 ${money(Math.abs(h.updown))} 米</div>` : ""}`;
  box.innerHTML = `<div class="panel" style="margin-bottom:18px"><div class="navgrid">
    <div class="compass">${compassSVG(deg)}<div class="readout">${readout}</div></div>
    <div>
      <div class="item-head"><span class="name">${esc(n.target.label)}</span><span class="muted">${esc(n.target.body)}</span><span style="margin-left:auto">${navModeHTML(n)}</span></div>
      ${h ? `<p style="margin:4px 0">${esc(h.text)}</p>` : ""}
      ${h && h.steer ? `<p style="font-size:18px;font-weight:600;margin:8px 0" class="money">${esc(h.steer.text)}</p>` : ""}
      ${h && h.steps ? h.steps.map((x) => `<p style="margin:2px 0;white-space:pre">${esc(x)}</p>`).join("") : ""}
      ${h && h.same_body && !h.station ? `<dl class="kv" style="margin-top:10px">
        <dt>地表距离</dt><dd>${km(h.surface)}（直线 ${km(h.direct)}）</dd>
        <dt>当前高度</dt><dd>${money(h.height)} m</dd>
        <dt>目标高度</dt><dd>${money(h.target_height)} m（${h.target_height > h.height ? "需上升" : "需下降"} ${money(Math.abs(h.target_height - h.height))} m）</dd>
        ${h.near ? `<dt>附近</dt><dd>${esc(h.near.name)}（${km(h.near.km)}）</dd>` : ""}</dl>` : ""}
      ${h && h.hint ? `<p class="money" style="margin-top:10px">${esc(h.hint)}</p>` : ""}
      <p class="navstat" style="margin-top:12px">${esc(n.status)}${n.at ? `｜${esc(n.at)} 更新` : ""}</p>
      ${n.msgs && n.msgs.length ? `<ul class="msgs">${n.msgs.map((m) => `<li>${esc(m)}</li>`).join("")}</ul>` : ""}
      <div class="row" style="margin-top:12px"><button class="btn" id="nrefresh">立即刷新位置</button><button class="btn stop" id="nstop">结束导航</button></div>
    </div></div></div>`;
  $("#nstop").onclick = () => api("nav_stop");
  $("#nrefresh").onclick = () => api("nav_refresh");
  bindNavMode();
}

async function navWaypointView() {
  const wps = await api("waypoints").catch(() => []);
  $("#navbody").innerHTML = `<div class="panel">
    ${wps.length ? `<table class="t"><tr><th>名称</th><th>星球</th><th>位置</th><th></th></tr>
      ${wps.map((w) => `<tr><td>${esc(w.name)}</td><td class="muted">${esc(w.body)}</td><td class="muted">${w.space ? "太空固定点" : `纬度 ${w.lat.toFixed(3)}° 经度 ${w.lon.toFixed(3)}° 高度 ${money(w.alt)} m`}</td>
        <td class="n"><button class="btn small" data-go="${esc(w.key)}">导航</button> <button class="btn small" data-del="${esc(w.name)}">删除</button></td></tr>`).join("")}</table>`
      : `<p class="muted" style="margin:0">暂无路标</p>`}
    <p class="muted" style="margin:10px 0 0">点「用当前位置新建」后，在游戏聊天框输入 /showlocation 回车即可保存${state.status?.settings?.mark_key ? `，或按 <b>${esc(state.status.settings.mark_key)}</b> 由 AT 自动输入（需英文输入法）` : ""}。星球表面和太空均可使用。</p>
  </div>
  <h2>新建路标</h2>
  <div class="panel">
    <p class="muted" style="margin:0 0 10px">在游戏聊天框输入 <b>/showlocation</b> 后回车，坐标会复制到剪贴板；粘贴到下方，填写名称后保存。</p>
    <div class="row">
      <label class="field" style="flex:1 1 420px">/showlocation 结果<input class="input" id="w-text" placeholder="Coordinates: x:… y:… z:…" style="width:100%"></label>
      <button class="btn" id="w-paste" style="align-self:flex-end">粘贴</button></div>
    <p id="w-where" class="muted" style="margin:8px 0 0;min-height:1.4em"></p>
    <div class="row" style="margin-top:8px">
      <label class="field">名称<input class="input" id="w-name" size="18" placeholder="例：戴玛尔 大洞"></label>
      <button class="btn primary" id="w-add" style="align-self:flex-end">保存路标</button>
      <button class="btn" id="w-here" style="align-self:flex-end" title="切回游戏，在聊天框输入 /showlocation，AT 自动保存">用当前位置新建</button></div></div>`;
  $("#navbody").onclick = async (e) => {
    const g = e.target.closest("[data-go]"), d = e.target.closest("[data-del]");
    if (g) { try { await api("nav_start", { key: g.dataset.go }); toast("已开始导航"); } catch (err) { toast(err.message); } }
    if (d) popconfirm(d, { title: "删除此路标？", sub: esc(d.dataset.del), okText: "删除", danger: true,
      onOk: async () => { try { await api("waypoint_delete", { name: d.dataset.del }); navWaypointView(); } catch (err) { toast(err.message); } } });
  };
  if (!state.wpListen) {           // 游戏里按 F7 记了新路标：在这页的话马上刷新
    state.wpListen = true;
    window.addEventListener("dubhe:waypoints", () => { if (page === "nav" && (state.navTab || "search") === "wp") navWaypointView(); });
  }
  let previewSeq = 0;
  const preview = async () => {                            // 粘贴后马上认星球、经纬度
    const text = $("#w-text").value.trim(), my = ++previewSeq, out = $("#w-where");
    if (!text) { out.textContent = ""; return; }
    try {
      const r = await api("waypoint_preview", { text });
      if (my !== previewSeq) return;
      out.innerHTML = `<span class="good">✓</span> ${esc(r.desc)}`;
      if (!$("#w-name").value) $("#w-name").placeholder = r.space ? `例：${r.body_zh} 矿区` : `例：${r.body_zh} 洞穴`;
    } catch (e) { if (my === previewSeq) out.innerHTML = `<span class="bad">${esc(e.message)}</span>`; }
  };
  $("#w-text").oninput = preview;
  $("#w-text").onpaste = () => setTimeout(preview, 0);
  $("#w-paste").onclick = async () => {
    try { const t = await navigator.clipboard.readText(); $("#w-text").value = t; preview(); }
    catch { toast("无法读取剪贴板，在输入框中按 Ctrl+V 粘贴"); $("#w-text").focus(); }
  };
  $("#w-add").onclick = async () => {
    try {
      const r = await api("waypoint_from_text", { name: $("#w-name").value, text: $("#w-text").value });
      toast(`已保存：${r.desc}`); navWaypointView();
    } catch (e) { toast(e.message); }
  };
  $("#w-here").onclick = async () => {
    try {
      const r = await api("waypoint_add", { name: $("#w-name").value, here: true });
      if (r && r.pending) { toast(r.message); return; }
      toast("已添加路标"); navWaypointView();
    } catch (e) { toast(e.message); }
  };
}
async function openPlace(key) {
  state.navTab = "search";
  try { state.plan = await api("nav_plan", { key }); } catch (e) { toast(e.message); }
  if (page === "nav") renderPage(); else location.hash = "#nav";
}

// ================================================================ 物品
PAGES.item = () => {
  $("#page").innerHTML = `<h1>物品查询</h1><p class="lede">查询物品的购买地点、掉落、维科洛兑换用途和玩家市场价格，以及矿物的开采地点。游戏中鼠标停在物品上按 <kbd>${esc(state.status?.hover_key || "F8")}</kbd> 也可打开此页。</p>
    <div class="row"><input class="input" id="iq" placeholder="例：牵引光束 / CQ7 / 量子 / 金" style="width:340px"><button class="btn primary" id="igo">搜索</button></div>
    <div class="split" style="margin-top:18px"><div class="list" id="ilist"></div><div id="iout"></div></div>`;
  const go = async () => {
    const q = $("#iq").value;
    const [rows, ores] = await Promise.all([api("item_search", { q }), api("mineral_search", { q }).catch(() => [])]);
    state.itemRows = rows; state.oreRows = ores;
    listItems(rows);
    if (ores.length && !rows.length) openMineral(ores[0].en);      // 只搜到矿：直接打开
  };
  $("#igo").onclick = go;
  $("#iq").onkeydown = (e) => { if (e.key === "Enter") go(); };   // 只管回车，别的键（退格、删除、方向键）照常
  $("#ilist").onclick = (e) => {
    const m = e.target.closest("button[data-m]");
    if (m) { openMineral(m.dataset.m); return; }
    const b = e.target.closest("button[data-i]"); if (b) { const r = state.itemRows[+b.dataset.i]; openItem(r.name, r.zh, r.id, true); }
  };
  listItems(state.itemRows);
  if (state.item) drawItem(); else if (state.mineral) drawMineral();
};
function listItems(rows) {
  const ores = state.oreRows || [];
  $("#ilist").parentElement.classList.toggle("solo", !rows && !ores.length);
  if (!rows && !ores.length) return;
  rows = rows || [];
  $("#ilist").innerHTML = ores.map((o) => `<button data-m="${esc(o.en)}"><span>${esc(o.zh)}</span><span class="tag qt">矿物</span><span class="l2">${esc(o.en)}｜开采地点</span></button>`).join("")
    + rows.map((r, i) => `<button data-i="${i}"><span>${nameHTML(r.zh, r.name)}</span><span class="faint">${r.src === "loot" ? "掉落" : ""}</span><span class="l2">${esc([r.category || (r.src === "loc" ? SRC_ZH.loc : ""), r.src === "wiki" ? SRC_ZH.wiki : ""].filter(Boolean).join("｜"))}</span></button>`).join("") || (ores.length ? "" : `<p class="empty">未找到此物品</p>`);
}
// 物品名统一一行「中文 English」，英文浅色（2026-10-26）；没有中文名的只写英文
const nameHTML = (zh, en) => (zh ? `${esc(zh)} <span class="en">${esc(en)}</span>` : esc(en));
const SRC_ZH = { loot: "仅掉落或特殊获取", loc: "商店和掉落中均没有", wiki: "wiki 有记录，暂无购买和掉落数据" };
async function openItem(name, zh, id, exact = false) {      // exact：从搜索结果点进来的，名字是准的
  const sel = ++state.sel;                                  // 点新物品那一刻旧请求全部作废：详情、市场、价格、掉落回来都核对这个序号
  state.itemFrom = ""; state.mineral = null;
  state.market = null; state.prices = null; state.candidates = [];
  let info;
  try { info = await api("item_info", { name, zh: zh || "", id, exact }); } catch (e) { if (sel === state.sel) toast(e.message); return; }
  if (sel !== state.sel) return;
  info.sel = sel; info.marketId = "";
  state.item = info;
  if (page !== "item") location.hash = "#item"; else drawItem();
  if (info.loot && info.loot.pending) {                     // 掉落明细本机没有：后台取，取到再补上（不卡页面）
    api("item_loot", { name: info.name, zh: zh || "" }).then((r) => { if (sel === state.sel) { info.loot = r.loot; drawItem(); } })
      .catch(() => { if (sel === state.sel) { info.loot = null; drawItem(); } });
  }
  api("market_lookup", { q: name }).then((r) => {
    if (sel !== state.sel) return;
    const exact = r.items.find((x) => x.label.toLowerCase().includes(name.toLowerCase()));
    state.candidates = r.items.slice(0, 8);
    if (exact) { state.market = exact; info.marketId = exact.id; loadPrices(exact.id); } else drawItem();
  }).catch(() => {});
}
// UEX 玩家市场的品质档（2026-10-23 用户问 q0–q7 是什么：显示成品质区间，也能直接输入品质数字）
const TIERS = [["q0", "无品质（0）"], ["q1", "品质 1–499"], ["q2", "品质 500–599"], ["q3", "品质 600–699"], ["q4", "品质 700–799"],
  ["q5", "品质 800–899"], ["q6", "品质 900–949"], ["q7", "品质 950–1000"]];
function tierOf(q) {
  if (q === "" || q == null || isNaN(+q)) return null;
  q = +q;
  if (q < 0 || q > 1000) return null;
  return q === 0 ? "q0" : q < 500 ? "q1" : q < 600 ? "q2" : q < 700 ? "q3" : q < 800 ? "q4" : q < 900 ? "q5" : q < 950 ? "q6" : "q7";
}
const tierLabel = (t) => (TIERS.find((x) => x[0] === String(t || "").toLowerCase()) || [0, t])[1];
async function loadPrices(id, quality = "q0", op = "sell") {
  const sel = state.sel, req = ++state.priceReq;            // 物品换了、或同物品又发了新一次价格查询（换品质 / 买卖）：晚回来的丢掉
  state.prices = { loading: true, quality, op };
  if (page === "item") drawItem();
  let next;
  try { const r = await api("market_prices", { id, quality, op }); next = { ...r, quality, op }; }
  catch (e) { next = { error: e.message, quality, op }; }
  if (sel !== state.sel || req !== state.priceReq) return;
  state.prices = next;
  if (page === "item") drawItem();
}

function shopsHTML(rows) {
  // 点一处商店就导航过去（2026-10-28 用户定）
  return rows.map((r) => `<div class="shop" data-navshop="${esc(r.shop)}" data-navplace="${esc(r.place)}" title="导航到这里" style="cursor:pointer"><span class="d">${esc(r.dist || "")}</span><span>${esc(r.shop)}</span><span class="p">${money(r.price)}</span><span class="w">${esc(r.place)}</span></div>`).join("");
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-navshop]");
  if (!b) return;
  try {
    const r = await api("nav_shop", { shop: b.dataset.navshop, place: b.dataset.navplace });
    state.plan = await api("nav_plan", { key: r.key });
    toast(`已开始导航：${r.label}`);
    location.hash = "#nav";
  } catch (err) { toast(err.message); }
});

function drawItem() {
  const box = $("#iout");
  if (!box || !state.item) return;
  const it = state.item;
  const near = it.here ? `按距当前位置远近排序：${it.here.label}${it.here.minutes > 10 ? `，${it.here.minutes} 分钟前` : ""}` : "按价格从低到高排序（打开过游戏库存后按远近排序）";
  const ways = [];
  if (it.nowhere) {                                          // 只有汉化包里有名字（1.6.41）
    const c = it.craft;
    ways.push(["var(--coral)", `商店、掉落、蓝图、维科洛和 wiki 中均没有记录<small>可能是任务或活动奖励，或已下架</small>`,
      c ? `<div class="muted">可制造：<a href="javascript:void 0" id="it-craft" data-key="${esc(c.key)}">${esc(c.name)}</a>${c.unlocked ? "（默认已解锁）" : c.missions.length ? `｜蓝图来源任务：${esc(c.missions.join("、"))}${c.nsrc > c.missions.length ? ` 等 ${c.nsrc} 个` : ""}` : ""}</div>` : ""]);
  }
  if (it.buyable) {
    ways.push(["var(--sky)", `商店购买<small>共 ${it.buy_total} 处｜${esc(near)}</small>`, shopsHTML(it.buy)]);
  } else if (it.variants.length) {
    if (!it.nowhere) ways.push(["var(--coral)", `商店无售<small>限定或特殊版本</small>`, ""]);
    it.variants.forEach((v) => ways.push(["var(--sky)", `可购买的同款：${esc(v.name)}<small>${v.total} 处有售｜${esc(near)}</small>`, shopsHTML(v.buy)]));
  } else if (!it.nowhere) {
    ways.push(["var(--coral)", `商店无售<small>未找到可购买的同款</small>`, ""]);
  }
  const L = it.loot;
  if (L && L.pending) ways.push(["var(--violet)", "掉落", `<p class="muted">掉落数据获取中…</p>`]);
  else if (L && L.error) ways.push(["var(--violet)", "掉落", `<p class="muted">${esc(L.error)}</p>`]);
  else if (L && L.mine) ways.push(["var(--violet)", `开采<small>${esc(L.note)}｜${esc(L.src || "")}</small>`,
    L.groups.map((g) => `<div class="loot"><span class="p">${(g.p * 100).toFixed(2)}%</span><span>${esc(g.regions.slice(0, 8).join("、"))}${g.regions.length > 8 ? ` 等 ${g.regions.length} 类` : ""}<div class="box">${esc(g.box || "")}</div></span></div>`).join("")
    + (L.more ? `<p class="faint" style="margin:6px 0 0">另有 ${L.more} 类地点概率更低</p>` : "")]);
  else if (L) ways.push(["var(--violet)", `掉落<small>单个箱子或刷新点的最高概率｜scl.miao.network</small>`,
    L.groups.map((g) => `<div class="loot"><span class="p">${(g.p * 100).toFixed(2)}%</span><span>${esc(g.regions.slice(0, 8).join("、"))}${g.regions.length > 8 ? ` 等 ${g.regions.length} 类` : ""}<div class="box">${g.box ? esc(g.box) + (g.placed ? "" : " 箱") : ""}</div></span></div>`).join("")
    + (L.more ? `<p class="faint" style="margin:6px 0 0">另有 ${L.more} 类地点概率更低</p>` : "")]);
  if (it.how) ways.push(["var(--sky)", "获取方式", `<div class="muted">${esc(it.how)}</div>`]);
  if ((it.ships || []).length) ways.push(["var(--sky)", `随船自带<small>${it.ships.length} 条船出厂装着</small>`,
    `<div class="muted">${it.ships.map(esc).join("、")}</div>`]);
  if (it.wikelo.length) ways.push(["var(--amber)", "维科洛兑换用途", it.wikelo.map((w) => `<div class="muted">${esc(w.title)}（${w.q}${w.u === "个" ? "" : " " + esc(w.u)}）→ ${esc(w.reward)}</div>`).join("")]);

  const pr = state.prices;
  const market = state.market ? `
    <div class="row" style="justify-content:space-between"><h3 style="margin:0">玩家市场价格｜${esc(state.market.label)}</h3>
      <div class="row"><div class="seg" id="op"><button data-op="sell" class="${(pr?.op || "sell") === "sell" ? "on" : ""}">出售挂牌</button><button data-op="buy" class="${pr?.op === "buy" ? "on" : ""}">求购</button></div>
      <input class="input" id="qnum" size="7" placeholder="输入品质" title="输入 0–1000 的品质，自动选择对应档位">
      <select class="input" id="qsel" title="UEX 玩家市场按品质分档报价">${TIERS.map(([v, l]) => `<option value="${v}" ${pr?.quality === v ? "selected" : ""}>${l}</option>`).join("")}</select></div></div>
    ${!pr ? "" : pr.loading ? `<p class="muted">查询中…</p>` : pr.error ? `<p class="bad">${esc(pr.error)}</p>` :
      `<table class="t" style="margin-top:8px"><tr><th>来源</th><th class="n">最低</th><th class="n">均价</th><th class="n">7 天均价</th><th class="n">挂牌</th></tr>
      ${pr.rows.map((r) => r.mean !== undefined ? `<tr><td>${esc(r.src)} <span class="faint">${esc(tierLabel(r.quality))}｜${esc(r.unit)}</span></td><td class="n money">${esc(r.min)}</td><td class="n">${esc(r.mean)}</td><td class="n">${esc(r.week || "—")}</td><td class="n">${r.count}</td></tr>`
        : `<tr><td>${esc(r.src)}</td><td colspan="4" class="muted">${esc(r.state)}</td></tr>`).join("")}</table>
      <p class="faint" style="margin:8px 0 0;font-size:12.5px">玩家挂牌参考价，非成交价；结果缓存 1 小时。UEX 按品质分 8 档报价：无品质（0）、1–499、500–599……950–1000</p>`}
    <details style="margin-top:12px" ${state.itemFrom === "F8" ? "open" : ""}><summary class="muted" style="cursor:pointer">入库</summary>
      <div class="row" style="margin-top:10px">
        <label class="field">数量<input class="input" id="s-qty" value="1" size="7"></label>
        <div class="field">单位${segH("s-unit", ["个", "SCU", "uSCU"], "个", "单位")}</div>
        <label class="field">品质<input class="input" id="s-q" placeholder="0–1000，选填" size="10"></label>
        <div class="field">存放地点${placeBtnHTML(defaultPlace())}</div>
        <button class="btn" id="s-add" style="align-self:flex-end">入库</button></div></details>`
    : state.candidates?.length ? `<h3>玩家市场</h3><p class="muted" style="margin:0 0 6px">市场中没有同名物品，选择一个查询价格：</p><div class="list" id="cands">${state.candidates.map((c) => `<button data-id="${esc(c.id)}"><span>${esc(c.label)}</span></button>`).join("")}</div>` : "";

  box.innerHTML = `<div class="panel">
    <div class="item-head"><span class="name">${esc(it.zh || it.name)}</span>${it.zh ? `<span class="muted">${esc(it.name)}</span>` : ""}${it.category ? `<span class="tag">${esc(it.category)}</span>` : ""}${state.itemFrom ? `<span class="tag qt">${esc(state.itemFrom)} 识别 ${esc(state.hover?.at || "")}</span>` : ""}${state.itemFrom === "F8" && state.hover?.quality != null ? `<span class="tag">品质 ${state.hover.quality}</span>` : ""}${state.itemFrom === "F8" && state.hover?.qty ? `<span class="tag">${esc(qtyText(state.hover.qty, state.hover.unit))}</span>` : ""}<span style="margin-left:auto" class="row"><button class="btn small" id="to-stock" title="带上名称、单位、品质和数量，在库存页入库">入库</button>${fbBtn("item", "报告问题")}</span></div>
    ${goalBox([it.goal])}
    ${it.aka && it.aka.length ? `<p class="faint" style="margin:0 0 6px;font-size:12.5px">别名：${esc(it.aka.join("、"))}（汉化包旧译名）</p>` : ""}
    ${it.desc ? `<details class="desc" style="margin:0 0 10px" open><summary class="muted" style="cursor:pointer">描述<span class="faint" style="font-size:12px"> · 游戏内说明</span></summary><div class="desc-body">${esc(it.desc)}</div></details>` : ""}
    ${it.sell ? `<p class="muted" style="margin:0">商店最高收购价 <span class="money">${money(it.sell.price)}</span>｜${esc(it.sell.shop)}</p>` : ""}
    <div class="ways">${ways.map(([c, h, body]) => `<div class="way" style="--c:${c}"><span class="dot"></span><div class="body"><h3>${h}</h3>${body}</div></div>`).join("")}</div>
  </div>
  ${market ? `<div class="panel">${market}</div>` : ""}`;

  $("#it-craft")?.addEventListener("click", (e) => openCraft(e.currentTarget.dataset.key));
  $("#op")?.addEventListener("click", (e) => { const b = e.target.closest("[data-op]"); if (b) loadPrices(state.market.id, $("#qsel").value, b.dataset.op); });
  $("#qsel")?.addEventListener("change", () => loadPrices(state.market.id, $("#qsel").value, state.prices?.op || "sell"));
  $("#cands")?.addEventListener("click", (e) => { const b = e.target.closest("[data-id]"); if (b) { state.market = state.candidates.find((c) => c.id === b.dataset.id); if (state.item) state.item.marketId = b.dataset.id; loadPrices(b.dataset.id); } });
  const f8 = state.itemFrom === "F8" ? state.hover || {} : {};
  if ($("#s-q") && f8.quality != null) $("#s-q").value = f8.quality;              // F8 认出的品质（没写品质的是 0）
  if ($("#s-qty") && f8.qty) $("#s-qty").value = f8.qty;                           // F8 认出的数量（矿：0.495 SCU；物品：格子上的 200x）
  if ($("#s-unit")) $("#s-unit").value = f8.unit || "个";
  if ($("#qnum") && f8.quality != null) $("#qnum").value = f8.quality;
  $("#qnum")?.addEventListener("change", () => {
    const t = tierOf($("#qnum").value.trim());
    if (!t) { toast("品质需为 0–1000 的数字"); return; }
    $("#qsel").value = t; loadPrices(state.market.id, t, state.prices?.op || "sell");
  });
  $("#to-stock")?.addEventListener("click", () => {
    const unit = $("#s-unit")?.value || f8.unit || "个";
    const q = $("#s-q")?.value;
    state.stockPrefill = { en: it.name, zh: it.zh || "", kind: unit === "个" ? "物品" : "矿物", id: state.market?.id || "",
      unit, qty: $("#s-qty")?.value || f8.qty || null, quality: q !== undefined && q !== "" ? q : f8.quality,
      place: $("#iout .place-pick")?.dataset.place || "", source: state.itemFrom === "F8" ? "F8" : "物品查询" };
    location.hash = "#stock";
  });
  $("#s-add")?.addEventListener("click", async () => {
    try {
      const unit = $("#s-unit").value;
      const place = $("#iout .place-pick").dataset.place;
      if (!place) { toast("先选择存放地点"); return; }
      const r = await api("stock_add_named", { name: it.zh || it.name, en: it.name, zh: it.zh || "", kind: unit === "个" ? "物品" : "矿物",
        id: it.marketId || "", qty: $("#s-qty").value, unit, quality: $("#s-q").value, location: place,
        source: state.itemFrom === "F8" ? "F8" : "物品查询" });
      state.stockData = r; state.lastLocation = r.last_location; toast(`已入库：${r.added}｜${place}（可在库存页撤销）`);
    } catch (e) { toast(e.message); }
  });
}

// ================================================================ 维科洛
PAGES.wikelo = () => {
  $("#page").innerHTML = `<h1>维科洛兑换</h1><p class="lede">搜索奖励、兑换或材料名称，查看所需材料及获取方式。</p>
    <div class="row"><input class="input" id="wq" placeholder="例：阿波罗 / 科力晶 / 重组样本" style="width:340px"><button class="btn primary" id="wgo">搜索</button></div>
    <div class="split" style="margin-top:18px"><div class="list" id="wlist"></div><div id="wout" class="sticky"></div></div>`;
  const go = async () => {
    const rows = await api("wikelo_search", { q: $("#wq").value });
    $("#wlist").innerHTML = rows.map((r) => `<button data-k="${esc(r.key)}"><span>${esc(r.title)}</span><span class="faint">${esc(r.type)}</span><span class="l2">奖励：${esc(r.reward)}</span></button>`).join("") || `<p class="empty">没有相关兑换</p>`;
    if (state.wkKey && !rows.some((r) => r.key === state.wkKey)) state.wkKey = null;
  };
  $("#wgo").onclick = go;
  $("#wq").onkeydown = (e) => { if (e.key === "Enter") go(); };   // 只管回车，别的键（退格、删除、方向键）照常
  $("#wlist").onclick = (e) => { const b = e.target.closest("button[data-k]"); if (b) showWikelo(b.dataset.k); };
  go().then(() => state.wkKey && showWikelo(state.wkKey));
};
async function showWikelo(key) {
  state.wkKey = key;
  document.querySelectorAll("#wlist button").forEach((b) => b.classList.toggle("on", b.dataset.k === key));
  try {
    const c = await api("wikelo_detail", { key });
    $("#wout").innerHTML = `<div class="panel"><div class="item-head"><span class="name">${esc(c.title)}</span><span class="tag">${esc(c.type)}</span>
        <button class="btn small primary" style="margin-left:auto" onclick="goalAdd('wikelo', ${esc(JSON.stringify(c.id))})">加入目标清单</button></div>
      <p class="muted" style="margin:0 0 12px">奖励：${esc(c.reward)}</p>
      <table class="t"><tr><th>材料</th><th class="n">数量</th><th>获取方式</th></tr>
      ${c.req.map((r) => `<tr><td>${esc(r.name)}</td><td class="n">${esc(r.q)}</td><td class="muted">${esc(r.tip || "—")}</td></tr>`).join("")}</table></div>`;
  } catch (e) { $("#wout").innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
function openWikelo(key) { state.wkKey = key; if (page === "wikelo") renderPage(); else location.hash = "#wikelo"; }

// ================================================================ 库存
// ================================================================ 弹窗、选地点（库存页、物品页、目标页共用）
const MODALS = [];
document.addEventListener("keydown", (e) => {                 // Esc 关掉最上面的弹窗（候选框开着时先关候选框）
  if (e.key === "Escape" && MODALS.length && !e.defaultPrevented) { e.preventDefault(); MODALS.at(-1).close(); }
});
function openModal({ title, sub = "", body = "", foot = "", wide = false, onClose = null, drawer = false }) {
  const m = document.createElement("div");
  m.className = drawer ? "drawer" : "modal";                   // drawer：从右边拉出，不挡左边的表格（边看边改）
  m.innerHTML = `<div class="modal-card${wide ? " wide" : ""}" role="dialog" aria-modal="${drawer ? "false" : "true"}" aria-label="${esc(title)}">
    <div class="modal-head"><div><h2>${esc(title)}</h2>${sub ? `<p>${sub}</p>` : ""}</div><button type="button" class="btn small" data-close>关闭</button></div>
    <div class="modal-body">${body}</div>${foot ? `<div class="modal-foot">${foot}</div>` : ""}</div>`;
  document.body.appendChild(m);
  const md = { el: m, q: (s) => m.querySelector(s) };
  md.close = () => {
    const i = MODALS.indexOf(md);
    if (i < 0) return;
    MODALS.splice(i, 1);
    m.remove();
    if (onClose) onClose();
  };
  MODALS.push(md);
  m.addEventListener("mousedown", (e) => { if (e.target === m) md.close(); });
  m.querySelectorAll("[data-close]").forEach((b) => (b.onclick = md.close));
  return md;
}

const placeNorm = (s) => String(s || "").toLowerCase().replace(/[\s·・\-_'’.,()（）]/g, "");
async function pickPlace(current = "") {
  let d;
  try { d = await api("stock_places"); } catch (e) { toast(e.message); return null; }
  return new Promise((resolve) => {
    let result = null;
    const md = openModal({
      title: "选择存放地点", wide: true, onClose: () => resolve(result),
      sub: "游戏中可存放物品的空间站、城市、星门和休息站。飞船、前哨等不在列表中的地点，可在下方自定义",
      body: `<input class="input" id="pp-q" placeholder="搜索地点：新巴贝奇 / Area18 / 弧 L1 / 派罗" autocomplete="off">
        <div id="pp-list" class="pp-list"></div>
        <div class="row" style="align-items:flex-end;border-top:1px solid var(--line);padding-top:12px">
          <label class="field" style="flex:1">自定义地点（飞船、前哨等）<input class="input" id="pp-name" placeholder="例：MOLE 货舱"></label>
          <button type="button" class="btn" id="pp-add">使用此名称</button></div>` });
    const card = (p) => `<button type="button" data-p="${esc(p.label)}" class="${p.label === current ? "on" : ""}"><b>${esc(p.label)}</b><small>${esc(p.path)}</small></button>`;
    const draw = () => {
      const q = placeNorm(md.q("#pp-q").value);
      const hit = (p) => !q || [p.label, p.zh, p.en, p.path].some((x) => placeNorm(x).includes(q));
      let html = "";
      if (d.here && !q) html += `<h4>当前位置 <span class="faint">游戏中最后打开库存的地点${d.here.minutes > 10 ? `，${d.here.minutes} 分钟前` : ""}</span></h4><div class="place-grid">${card(d.here)}</div>`;
      const mine = d.custom.filter((c) => !q || placeNorm(c).includes(q));
      if (mine.length) html += `<h4>自定义地点</h4><div class="place-grid">${mine.map((c) => card({ label: c, path: "自定义地点" })).join("")}</div>`;
      const groups = {};
      d.places.filter(hit).forEach((p) => (groups[p.sys_zh] ||= []).push(p));
      for (const [sys, ps] of Object.entries(groups)) html += `<h4>${esc(sys)}</h4><div class="place-grid">${ps.map(card).join("")}</div>`;
      md.q("#pp-list").innerHTML = html || `<p class="muted" style="margin:0">未找到「${esc(md.q("#pp-q").value)}」，可尝试其他名称，或在下方自定义</p>`;
    };
    draw();
    md.q("#pp-q").oninput = draw;
    md.q("#pp-q").onkeydown = (e) => {
      if (e.key !== "Enter") return;
      const b = md.q("#pp-list [data-p]");
      if (b) { e.preventDefault(); result = b.dataset.p; md.close(); }
    };
    md.q("#pp-list").onclick = (e) => { const b = e.target.closest("[data-p]"); if (b) { result = b.dataset.p; md.close(); } };
    md.q("#pp-add").onclick = async () => {
      try { const r = await api("stock_place_add", { name: md.q("#pp-name").value }); result = r.label; md.close(); }
      catch (e) { toast(e.message); }
    };
    md.q("#pp-name").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); md.q("#pp-add").click(); } };
    setTimeout(() => md.q("#pp-q").focus(), 0);
  });
}

// 「放在哪」按钮：点一下弹出选地点（库存页、物品页、目标页都用这个）
function placeBtnHTML(label) {
  return `<button type="button" class="btn place-pick" data-place="${esc(label || "")}"><span>${label ? esc(label) : "选择地点"}</span><span class="faint">选择地点 ▾</span></button>`;
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest(".place-pick");
  if (!b) return;
  e.preventDefault();
  const v = await pickPlace(b.dataset.place);
  if (v) {
    b.dataset.place = v; b.querySelector("span").textContent = v;
    b.dispatchEvent(new CustomEvent("placechange", { bubbles: true, detail: v }));
  }
});
function defaultPlace() {                                     // 入库默认放在：游戏里最后打开库存的地方 > 上次放的地方
  const here = state.stockData?.here;
  if (here && !here.custom) return here.label;
  return state.status?.place?.label || state.lastLocation || "";
}

// 名字联想：打字就出候选（矿物、物品，中文 / 英文 / 名字的一部分 / 错一两个字）
function attachSuggest(input, box, { onPick, onTop }) {
  let rows = [], on = -1, timer = null;
  const show = () => {
    box.hidden = !rows.length;
    box.innerHTML = rows.map((r, i) => `<button type="button" data-k="${i}" class="${i === on ? "on" : ""}"><span>${esc(r.zh || r.en)}${r.zh ? `<span class="faint"> ${esc(r.en)}</span>` : ""}</span><span class="tag ${r.kind === "矿物" ? "qt" : ""}">${esc(r.kind)}｜${esc(r.unit)}</span></button>`).join("");
  };
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (!q) { rows = []; show(); return; }
    timer = setTimeout(async () => {
      let r = [];
      try { r = await api("stock_suggest", { q }); } catch { r = []; }
      if (input.value.trim() !== q) return;                  // 又打了字：等下一次
      rows = r; on = r.length ? 0 : -1; show();
      if (onTop && r.length) onTop(r[0]);                     // 没点选也按最像的那个预选单位
    }, 180);
  });
  input.addEventListener("keydown", (e) => {
    if (box.hidden) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); on = (on + (e.key === "ArrowDown" ? 1 : rows.length - 1)) % rows.length; show(); }
    else if (e.key === "Enter" && rows[on]) { e.preventDefault(); const r = rows[on]; rows = []; show(); onPick(r); }
    else if (e.key === "Escape") { e.preventDefault(); rows = []; show(); }
  });
  input.addEventListener("blur", () => setTimeout(() => { rows = []; show(); }, 180));
  box.addEventListener("mousedown", (e) => { const b = e.target.closest("[data-k]"); if (b) { e.preventDefault(); const r = rows[+b.dataset.k]; rows = []; show(); onPick(r); } });
}

// ================================================================ 库存
const STOCK_SORTS = [["name", "按名称"], ["qty", "按数量"], ["q", "按品质"], ["value", "按估值"], ["changed", "按最近变动"]];
const OUT_REASONS = ["卖出", "消耗", "维科洛兑换", "用于制造", "丢失", "其他"];
const MAIN_BIN = "总仓";

function stockShow(d) {                                       // 库存接口返回的新数据：记下来，库存页开着就重画
  state.stockData = d;
  if (d.last_location) state.lastLocation = d.last_location;
  if (page === "stock") stockDraw();
}
function stockGroups() {
  const d = state.stockData;
  return [...d.tree.flatMap((t) => t.places), ...d.custom, ...d.unmatched];
}
function stockSelParts() {                                    // 选中的是「地点」还是「地点｜仓位」
  const sel = state.stockSel || "";
  const i = sel.indexOf("｜");
  return i < 0 ? { place: sel, bin: null } : { place: sel.slice(0, i), bin: sel.slice(i + 1) };
}
function binMeta(place) {                                     // 这个地点建过的仓位：{bins: [{name, desc}], default}
  return (state.stockData?.bins || {})[place] || { bins: [], default: "" };
}
function binOptionsHTML(place, current) {
  const meta = binMeta(place);
  const names = [MAIN_BIN, ...(meta.bins || []).map((b) => b.name)];
  const def = current || meta.default || MAIN_BIN;
  return names.map((n) => `<option value="${esc(n)}" ${n === def ? "selected" : ""}>${esc(n)}${n === meta.default ? "（默认）" : ""}</option>`).join("");
}
function bindBinSelect(md, sel) {                             // 换了地点：仓位下拉跟着换
  md.el.addEventListener("placechange", (e) => { sel.innerHTML = binOptionsHTML(e.detail, ""); });
}
function stockRows() {
  const d = state.stockData, f = state.stockF, { place, bin } = stockSelParts();
  const q = f.q.trim().toLowerCase();
  let rows = d.rows.map((r, i) => ({ ...r, _i: i }));
  if (place) rows = rows.filter((r) => r.place === place && (bin == null || r.bin === bin));
  if (q) rows = rows.filter((r) => `${r.item} ${r.zh} ${r.en}`.toLowerCase().includes(q));
  if (f.kind) rows = rows.filter((r) => r.kind === f.kind);
  if (f.qr === "none") rows = rows.filter((r) => r.q == null);
  else if (f.qr) rows = rows.filter((r) => r.q != null && tierOf(r.q) === f.qr);
  if (f.goal === "used") rows = rows.filter((r) => r.goal_qty > 0);
  else if (f.goal === "free") rows = rows.filter((r) => !r.goal_qty && !r.reserved);
  else if (f.goal === "reserved") rows = rows.filter((r) => r.reserved);
  const key = { name: (r) => r.zh || r.en, qty: (r) => +r.qty, q: (r) => (r.q == null ? -1 : r.q), value: (r) => r.value || 0,
    changed: (r) => r.changed || "" }[f.sort] || ((r) => r.zh || r.en);
  rows.sort((a, b) => {
    const x = key(a), y = key(b);
    const c = typeof x === "number" ? x - y : String(x).localeCompare(String(y), "zh-CN");
    return f.desc ? -c : c;
  });
  return rows;
}
function stockTreeHTML() {
  const d = state.stockData, sel = state.stockSel || "";
  const hereL = d.here && !d.here.custom ? d.here.label : "";
  const btn = (key, label, sub, count, extra = "", cls = "") => `<button type="button" data-sel="${esc(key)}" class="${cls} ${sel === key ? "on" : ""}">
    <span class="nm">${esc(label)}${extra}</span><b>${count}</b>${sub ? `<small>${esc(sub)}</small>` : ""}</button>`;
  const place = (p, sub, extra = "") => {
    let h = btn(p.label, p.label, sub, p.count, extra);
    if ((p.bins || []).some((b) => b.name !== MAIN_BIN))         // 分了仓位的地点：下面列出各个仓位
      h += p.bins.map((b) => btn(`${p.label}｜${b.name}`, b.name, "", b.count, b.default && b.name !== MAIN_BIN ? ` <span class="tag">默认</span>` : "", "bin")).join("");
    return h;
  };
  let html = `<div class="tree-head"><b>地点与仓位</b><button type="button" class="btn small" id="st-newbin">＋ 新建仓位</button></div>`;
  html += btn("", "全部地点", "", d.rows.length);
  for (const g of d.tree) {
    html += `<div class="grp">${esc(g.sys)}</div>`;
    html += g.places.map((p) => place(p, p.path.split(" / ").slice(1, -1).join(" / "), p.label === hereL ? ` <span class="tag qt">当前位置</span>` : "")).join("");
  }
  if (d.custom.length) html += `<div class="grp">自定义地点</div>` + d.custom.map((p) => place(p, "")).join("");
  if (d.unmatched.length) html += `<div class="grp warn">未归类（手动输入的旧地点）</div>` + d.unmatched.map((p) => btn(p.label, p.label, "点击归入游戏地点", p.count)).join("");
  return html;
}
function moneyText(v) { return v ? `≈ ${money(v)} aUEC` : ""; }
function stockMainHTML() {
  const d = state.stockData, { place, bin } = stockSelParts();
  const rows = stockRows();
  const g = place ? stockGroups().find((x) => x.label === place) : null;
  const shownValue = rows.reduce((s, r) => s + (r.value || 0), 0);
  let head;
  if (!place) {
    head = `<div class="stock-head"><h2>全部地点</h2><span class="faint">${d.rows.length} 条${d.value_total ? `｜估值 <span class="money">${moneyText(d.value_total)}</span>` : ""}</span>
      <span class="row" style="margin-left:auto;gap:6px"><button type="button" class="btn small" id="st-price" title="在玩家市场（UEX / SCM）查询已填品质物品的价格">查询估值</button></span></div>`;
  } else if (bin != null) {
    const b = (g?.bins || []).find((x) => x.name === bin) || { name: bin, count: 0, desc: "" };
    head = `<div class="stock-head"><h2>${esc(place)} <span class="faint">/</span> ${esc(bin)}</h2>
      <span class="faint">${b.count} 条${b.default && bin !== MAIN_BIN ? "｜默认仓位" : ""}${shownValue ? `｜估值 <span class="money">${moneyText(shownValue)}</span>` : ""}</span>
      <span class="row" style="margin-left:auto;gap:6px"><button type="button" class="btn small" id="st-in-here">入库到此处</button>
        ${bin !== MAIN_BIN ? `<button type="button" class="btn small" id="st-binset">仓位设置</button>` : ""}</span></div>
      ${b.desc ? `<p class="faint" style="margin:-4px 0 10px">${esc(b.desc)}</p>` : ""}`;
  } else {
    const where = g?.state === "known" ? g.path : g?.state === "custom" ? "自定义地点" : "手动输入的旧地点";
    head = `<div class="stock-head"><h2>${esc(place)}</h2><span class="faint">${esc(where)}｜${g?.count ?? 0} 条${g?.value ? `｜估值 <span class="money">${moneyText(g.value)}</span>` : ""}</span>
      <span class="row" style="margin-left:auto;gap:6px">${g?.state === "unmatched"
        ? `<button type="button" class="btn small primary" id="st-reloc">归入地点</button><button type="button" class="btn small" id="st-keep">保留为自定义地点</button>`
        : `<button type="button" class="btn small" id="st-in-here">入库到此处</button><button type="button" class="btn small" id="st-newbin2">新建仓位</button>`}</span></div>
      ${g?.state === "unmatched" ? `<p class="note-warn">此地点与游戏地点不匹配（手动输入的旧地点）。点击「归入地点」选择游戏地点，此处物品将一并移入；如名称本身正确（例如船名），点击「保留为自定义地点」。</p>` : ""}`;
  }
  const showPlace = !place, showBin = place && bin == null && (g?.bins || []).some((b) => b.name !== MAIN_BIN);
  const goalTag = (r) => r.reserved ? ` <span class="tag noqt" title="目标不使用此行">不用于目标</span>`
    : r.goal_qty ? ` <span class="tag qt" title="${esc(r.goal_titles.join("、"))}">目标占用 ${esc(qtyText(+r.goal_qty.toFixed(6), r.unit))}</span>` : "";
  const f = state.stockF, sh = (k, label) => `<button type="button" class="th-sort${f.sort === k ? " on" : ""}" data-sort="${k}">${label}${f.sort === k ? (f.desc ? " ↓" : " ↑") : ""}</button>`;
  const table = rows.length ? `<div class="tscroll"><table class="t stock-t"><tr><th>${sh("name", "物品")}</th><th>${sh("q", "品质")}</th>${showPlace ? "<th>地点</th>" : ""}${showBin ? "<th>仓位</th>" : ""}<th class="n">${sh("qty", "数量")}</th><th class="n" title="可用 = 数量 − 目标占用">可用</th><th class="n">${sh("value", "估值 aUEC")}</th><th class="n">${sh("changed", "最近变动")}</th></tr>
    ${rows.map((r) => `<tr><td>${esc(r.item)}${goalTag(r)}</td>
      <td class="${r.qkey === "unknown" ? "bad" : "muted"}" style="white-space:nowrap">${qCell(r)}</td>
      ${showPlace ? `<td class="muted" style="white-space:nowrap">${esc(r.place)}${r.bin !== MAIN_BIN ? ` <span class="faint">/ ${esc(r.bin)}</span>` : ""}${r.place_state === "unmatched" ? ` <span class="tag noqt">未归类</span>` : ""}</td>` : ""}
      ${showBin ? `<td class="muted">${esc(r.bin)}</td>` : ""}
      <td class="n">${esc(qtyText(r.qty, r.unit))}</td>
      <td class="n ${r.avail < r.qty ? "" : "muted"}" style="white-space:nowrap">${esc(qtyText(+(+r.avail).toFixed(6), r.unit))}</td>
      <td class="n ${r.value ? "money" : "faint"}">${r.value ? money(r.value) : "—"}</td>
      <td class="n"><span class="acts" data-i="${r._i}"><button type="button" class="btn small" data-a="out">出库</button><button type="button" class="btn small" data-a="set">改数量</button><button type="button" class="btn small more" data-a="more" aria-haspopup="menu">更多</button></span></td></tr>`).join("")}</table></div>`
    : `<div class="empty">${!d.rows.length ? "库存为空。点击右上角「入库」添加第一条记录" : place && !(bin != null ? (g?.bins || []).find((x) => x.name === bin)?.count : g?.count) ? "此处暂无物品，点击「入库到此处」添加" : "没有匹配的库存"}</div>`;
  const foot = !place && d.rows.length ? `<p class="faint" style="margin:10px 0 0;font-size:12.5px">${d.value_total ? `估值按玩家市场最低出售挂牌价计算（${d.priced} 行有报价，${d.rows.length - d.priced} 行无报价；品质未知的不计入）。` : "暂无估值：点击「查询估值」在玩家市场查询。"}目标占用：此行已分配给目标的数量；「保留」的行不分配给目标。可用 = 数量 − 目标占用。</p>` : "";
  return `<div class="panel">${head}${table}${foot}</div>`;
}
function ledgerEntryHTML(x, full = false) {
  const tagCls = { 入库: "qt", 出库: "out" };
  const when = new Date(x.at).toLocaleString("zh-CN", full ? { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }
    : { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  return `<tr><td class="faint" style="white-space:nowrap">${esc(when)}</td>
    <td style="white-space:nowrap"><span class="tag ${tagCls[x.type] || ""}">${esc(x.type)}</span>${x.source ? `<div class="faint" style="font-size:12px">${esc(x.source)}</div>` : ""}</td>
    <td>${x.items.slice(0, full ? 12 : 4).map((t) => `<div>${esc(t)}</div>`).join("")}${x.items.length > (full ? 12 : 4) ? `<div class="faint">…另有 ${x.items.length - (full ? 12 : 4)} 行</div>` : ""}
      ${x.reason || x.note ? `<div class="faint" style="font-size:12.5px">${esc([x.reason, x.note].filter(Boolean).join("："))}</div>` : ""}</td>
    <td class="n">${x.undone ? `<span class="faint">已撤销</span>` : x.type === "撤销" ? "" : `<button type="button" class="btn small" data-undo="${esc(x.batch)}">撤销</button>`}</td></tr>`;
}
function stockHistHTML() {
  const h = state.stockData.history;
  if (!h.length) return `<p class="muted" style="margin:0">暂无记录</p>`;
  return `<table class="t"><tr><th>时间</th><th>类型</th><th>内容</th><th></th></tr>${h.map((x) => ledgerEntryHTML(x)).join("")}</table>`;
}
function stockDraw() {
  const d = state.stockData;
  if (d && $("#ss-table")) { stockSimpleDraw(); return; }
  if (!d || !$("#st-tree")) return;
  const { place, bin } = stockSelParts();
  const g = place ? stockGroups().find((x) => x.label === place) : null;
  if (place && (!g || (bin != null && !(g.bins || []).some((b) => b.name === bin)))) state.stockSel = g ? place : "";
  $("#st-tree").innerHTML = stockTreeHTML();
  $("#st-main").innerHTML = stockMainHTML();
  $("#st-hist").innerHTML = stockHistHTML();
  countDraw();
}

// ---------------------------------------------------------------- 盘点（F6）
function countDraw() {
  const c = state.count || {}, key = state.status?.settings?.count_key || "F6";
  const b = $("#st-count");
  if (b) { b.innerHTML = `${c.running ? "结束盘点" : "盘点"} <kbd>${esc(key)}</kbd>`; b.className = "btn" + (c.running ? " primary" : ""); }
  const box = $("#st-review");
  if (!box) return;
  const rv = c.review;
  if (!rv) { box.innerHTML = ""; return; }
  const q = (v) => (v == null || v === "" ? "" : ` Q${v}`);
  const num = (v, u) => esc(qtyText(+(+v).toFixed(6), u));
  const diff = rv.rows.filter((r) => r.delta), same = rv.rows.length - diff.length;
  box.innerHTML = `<div class="panel" style="margin:12px 0"><h3 style="margin:0 0 8px">对账｜${esc(rv.place)}</h3>
    <table class="t">${diff.map((r) => `<tr><td>${esc(r.zh || r.en)}${q(r.quality)}${r.craft ? ` <span class="faint" style="font-size:12.5px">${esc(r.craft.map((x) => `${x.slot} ${x.q}`).join(" · "))}</span>` : ""}</td><td class="n">${num(r.book, r.unit)} → ${num(r.game, r.unit)}</td>
      <td class="n" style="color:var(${r.delta > 0 ? "--mint" : "--coral"})">${r.delta > 0 ? "+" : "−"}${num(Math.abs(r.delta), r.unit)}</td></tr>`).join("")}
    ${rv.missing.map((m, i) => `<tr><td>${esc(m.item)}${q(m.quality)}</td><td class="n muted">${num(m.qty, m.unit)} 未盘到</td>
      <td class="n"><label style="white-space:nowrap"><input type="checkbox" data-zero="${i}"> 清零</label></td></tr>`).join("")}</table>
    ${same ? `<p class="faint" style="margin:6px 0 0">${same} 项数量一致</p>` : ""}
    <div class="row" style="justify-content:flex-end;gap:8px;margin-top:10px"><button type="button" class="btn small" id="cr-no">取消</button><button type="button" class="btn small primary" id="cr-ok">确认</button></div></div>`;
  $("#cr-no").onclick = async () => { await api("count_cancel"); state.count = { ...c, review: null }; countDraw(); };
  $("#cr-ok").onclick = async () => {
    const zero = [...box.querySelectorAll("[data-zero]:checked")].map((x) => rv.missing[+x.dataset.zero].key);
    try { stockShow(await api("count_apply", { zero })); state.count = { ...c, review: null }; countDraw(); toast("已按盘点结果更新"); }
    catch (err) { toast(err.message); }
  };
}

function stockInDialog(pre = {}) {
  let pick = pre.en ? { en: pre.en, zh: pre.zh || "", kind: pre.kind || "", id: pre.id || "", unit: pre.unit || "" } : null;
  let unitTouched = !!pre.unit;
  const here = state.stockData?.here || (state.status?.place ? { ...state.status.place } : null);
  const place0 = pre.place || defaultPlace();
  const md = openModal({
    title: "入库", sub: "选择候选项后自动设置单位：矿物按 SCU，其他按个（1 SCU = 1,000,000 uSCU）。品质可留空，之后在表格中「改品质」补充",
    body: `<div class="row" style="gap:10px;align-items:flex-end">
        <div class="field" style="flex:1">存放地点${placeBtnHTML(place0)}</div>
        <label class="field">仓位<select class="input" id="si-bin">${binOptionsHTML(place0, pre.bin)}</select></label></div>
      ${here && !here.custom ? `<span class="faint" style="font-size:12px;margin-top:-8px">当前位置：${esc(here.label)}（游戏中最后打开库存的地点${here.minutes > 10 ? `，${here.minutes} 分钟前` : ""}）</span>` : ""}
      <label class="field" style="position:relative">物品（输入中文或英文名称）<input class="input" id="si-name" autocomplete="off" placeholder="例：钛 / 冷冻 / taran / CQ7" value="${esc(pre.zh || pre.en || "")}"><div class="suggest" id="si-sug" hidden></div></label>
      <div class="row" style="gap:10px;align-items:flex-end">
        <label class="field">数量<input class="input" id="si-qty" size="10" placeholder="例：0.495" value="${esc(pre.qty ?? "")}"></label>
        <div class="field">单位${segH("si-unit", ["个", "SCU", "uSCU"], "个", "单位")}</div>
        <label class="field">品质<input class="input" id="si-q" size="10" placeholder="0–1000，选填" value="${esc(pre.quality ?? "")}"></label></div>
      <div id="si-craft" hidden></div>
      <label class="field">备注<textarea class="input" id="si-note" rows="2" placeholder="选填"></textarea></label>`,
    foot: `<button type="button" class="btn" data-close>取消</button><button type="button" class="btn" id="si-more">保存并继续</button><button type="button" class="btn primary" id="si-ok">保存</button>` });
  if (pre.unit) md.q("#si-unit").value = pre.unit;
  bindBinSelect(md, md.q("#si-bin"));
  // 1.6.67：能制造的东西，按材料槽填品质（品质栏自动算平均）
  let craftSlots = [];
  const craftBox = md.q("#si-craft");
  const craftAvg = () => {
    const qs = [...craftBox.querySelectorAll("input")].map((x) => x.value.trim()).filter((v) => v !== "").map(Number);
    if (qs.length) md.q("#si-q").value = Math.round(qs.reduce((a, b) => a + b, 0) / qs.length);
  };
  const loadCraft = async (en, zh) => {
    craftSlots = [];
    craftBox.hidden = true; craftBox.innerHTML = "";
    if (!en && !zh) return;
    try { craftSlots = await api("craft_slots_for", { en, zh }); } catch (e) { craftSlots = []; }
    if (!craftSlots.length) return;
    craftBox.innerHTML = `<div class="field">材料品质<div class="row" style="gap:8px;margin-top:4px">${craftSlots.map((x, i) =>
      `<label class="field" style="font-size:12.5px">${esc(x.slot)} · ${esc(x.mat)}<input class="input num" data-i="${i}" size="6" inputmode="numeric" list="si-tiers-${i}"><datalist id="si-tiers-${i}">${(x.tiers || []).map((t) => `<option value="${t}">`).join("")}</datalist></label>`).join("")}</div></div>`;
    craftBox.hidden = false;
    craftBox.oninput = craftAvg;
  };
  const craftData = () => craftSlots.map((x, i) => ({ idx: x.idx, slot: x.slot, mat: x.mat, mat_en: x.mat_en, q: craftBox.querySelector(`[data-i="${i}"]`)?.value.trim() ?? "" }))
    .filter((x) => x.q !== "");
  if (pre.en) loadCraft(pre.en, pre.zh || "");
  attachSuggest(md.q("#si-name"), md.q("#si-sug"), {
    onPick: (r) => { pick = r; md.q("#si-name").value = r.zh || r.en; if (!unitTouched) md.q("#si-unit").value = r.unit; md.q("#si-qty").focus(); loadCraft(r.en, r.zh); },
    onTop: (r) => { if (!unitTouched) md.q("#si-unit").value = r.unit; },
  });
  md.q("#si-name").addEventListener("input", () => { pick = null; });
  md.q("#si-unit").onchange = () => { unitTouched = true; };
  const save = async (more) => {
    const place = md.q(".place-pick").dataset.place;
    if (!place) { toast("先选择存放地点"); return; }
    try {
      const r = await api("stock_add_named", { name: md.q("#si-name").value, qty: md.q("#si-qty").value, unit: md.q("#si-unit").value,
        quality: md.q("#si-q").value, location: place, bin: md.q("#si-bin").value, note: md.q("#si-note").value,
        en: pick?.en || "", zh: pick?.zh || "", kind: pick?.kind || "", id: pick?.id || "", source: pre.source || "库存页", craft: craftData() });
      stockShow(r);
      const b = md.q("#si-bin").value;
      toast(`已入库：${r.added}｜${place}${b && b !== MAIN_BIN ? " / " + b : ""}`);
      if (more) {
        ["#si-name", "#si-qty", "#si-q", "#si-note"].forEach((s) => (md.q(s).value = ""));
        pick = null; unitTouched = false; pre = { source: pre.source }; loadCraft("", "");
        md.q("#si-name").focus();
      } else md.close();
    } catch (e) { toast(e.message); }
  };
  md.q("#si-more").onclick = () => save(true);
  md.q("#si-ok").onclick = () => save(false);
  md.q("#si-qty").onkeydown = md.q("#si-q").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); save(false); } };
  setTimeout(() => (pre.en ? md.q("#si-qty") : md.q("#si-name")).focus(), 0);
}

const rowSub = (r) => `${esc(r.item)}｜${esc(r.quality)}｜${esc(r.place)}${r.bin && r.bin !== MAIN_BIN ? " / " + esc(r.bin) : ""}｜当前 <b>${esc(qtyText(r.qty, r.unit))}</b>`;
const popSub = (r) => `${esc(r.quality)}｜${esc(r.place)}${r.bin && r.bin !== MAIN_BIN ? " / " + esc(r.bin) : ""}｜现有 ${esc(qtyText(r.qty, r.unit))}`;
const rowArgs = (r) => ({ id: r.id, qkey: r.qkey, location: r.location, ukey: r.ukey });
async function stockDo(md, name, args, msg) {
  try { stockShow(await api(name, args)); toast(msg); md.close(); } catch (e) { toast(e.message); }
}
// 1.6.60：出库、改数量、改品质改成按钮旁边的小确认（Popconfirm），不再弹整个窗口
async function stockPopDo(name, args, msg, p = null) {
  try {
    const r = await api(name, args), batch = r.history?.[0]?.batch;
    stockShow(r);
    toast(msg, batch ? ["撤销", async () => { try { stockShow(await api("stock_undo", { batch })); toast("已撤销"); } catch (e) { toast(e.message); } }] : null);
    return true;
  } catch (e) { if (p) p.error(e.message); else toast(e.message); return false; }
}
function stockOutDialog(r, anchor) {
  let reason = "";
  const p = popconfirm(anchor, { title: `出库 · ${r.item}`, sub: popSub(r), okText: "出库", body: `
    <div class="row" style="gap:6px;flex-wrap:nowrap"><input class="input numin" id="so-qty" inputmode="decimal" aria-label="出库数量"><span class="faint">${esc(r.unit)}</span>
      <button type="button" class="btn small" id="so-all">全部</button></div>
    <div class="chips" id="so-why">${OUT_REASONS.map((x) => `<button type="button" data-r="${x}">${x}</button>`).join("")}</div>
    <input class="input" id="so-note" placeholder="备注">`,
    onOk: (p) => stockPopDo("stock_out", { ...rowArgs(r), qty: p.q("#so-qty").value, reason, note: p.q("#so-note").value }, "已出库", p) });
  if (!p) return;
  p.q("#so-all").onclick = () => { p.q("#so-qty").value = r.qty; };
  p.q("#so-why").onclick = (e) => {
    const b = e.target.closest("[data-r]");
    if (!b) return;
    reason = reason === b.dataset.r ? "" : b.dataset.r;
    p.dirty = true;
    p.q("#so-why").querySelectorAll("button").forEach((x) => x.classList.toggle("on", x.dataset.r === reason));
  };
}
function stockSetDialog(r, anchor) {
  popconfirm(anchor, { title: `改数量 · ${r.item}`, sub: popSub(r), okText: "保存", body: `
    <div class="row" style="gap:6px;flex-wrap:nowrap"><input class="input numin" id="ss-qty" inputmode="decimal" value="${esc(r.qty)}" aria-label="数量"><span class="faint">${esc(r.unit)}</span></div>
    <input class="input" id="ss-note" placeholder="备注">`,
    onOk: (p) => stockPopDo("stock_set_qty", { ...rowArgs(r), qty: p.q("#ss-qty").value, note: p.q("#ss-note").value }, "数量已更新", p) });
}
function stockMoveDialog(r) {
  const md = openModal({ title: "移库", sub: rowSub(r), body: `
    <div class="row" style="gap:10px;align-items:flex-end">
      <div class="field" style="flex:1">移至${placeBtnHTML(r.place && r.place_state !== "unmatched" ? r.place : "")}</div>
      <label class="field">仓位<select class="input" id="sm-bin">${binOptionsHTML(r.place, r.bin === MAIN_BIN ? MAIN_BIN : "")}</select></label></div>
    <label class="field">数量（${esc(r.unit)}，默认整行移动）<input class="input" id="sm-qty" size="12" value="${esc(r.qty)}"></label>
    <label class="field">备注<textarea class="input" id="sm-note" rows="2" placeholder="选填，例：运往 Area18 出售"></textarea></label>`,
    foot: `<button type="button" class="btn" data-close>取消</button><button type="button" class="btn primary" id="sm-ok">确认移库</button>` });
  bindBinSelect(md, md.q("#sm-bin"));
  md.q("#sm-ok").onclick = () => {
    const to = md.q(".place-pick").dataset.place, bin = md.q("#sm-bin").value;
    if (!to) { toast("先选择目标地点"); return; }
    stockDo(md, "stock_move", { ...rowArgs(r), qty: md.q("#sm-qty").value, to, bin, note: md.q("#sm-note").value },
      `已移至 ${to}${bin && bin !== MAIN_BIN ? " / " + bin : ""}`);
  };
}
function stockQualityDialog(r, anchor) {
  popconfirm(anchor, { title: `改品质 · ${r.item}`, sub: "0–1000，留空表示未知", okText: "保存", body: `
    <input class="input numin" id="sq-q" inputmode="numeric" value="${r.q ?? ""}" aria-label="品质">
    <input class="input" id="sq-note" placeholder="备注">`,
    onOk: (p) => stockPopDo("stock_set_quality", { ...rowArgs(r), quality: p.q("#sq-q").value, note: p.q("#sq-note").value }, "品质已更新", p) });
}
function binDialog({ place = "", name = "", edit = false }) {
  const meta = binMeta(place), b = (meta.bins || []).find((x) => x.name === name) || { name: "", desc: "" };
  const md = openModal({ title: edit ? "仓位设置" : "新建仓位", sub: edit ? `${esc(place)} / ${esc(name)}` : "选择地点并填写仓位名称（例如「待售」「目标材料」「船上」）",
    body: `${edit ? "" : `<div class="field">仓储地点${placeBtnHTML(place || defaultPlace())}</div>`}
      <label class="field">仓位名称<input class="input" id="bn-name" value="${esc(b.name)}" placeholder="例：待售"></label>
      <label class="field">描述<textarea class="input" id="bn-desc" rows="3" placeholder="例：机库中的箱子、个人备注">${esc(b.desc || "")}</textarea></label>
      <label class="agree"><input type="checkbox" id="bn-def" ${edit && meta.default === name ? "checked" : ""}> 设为默认仓位（入库到此地点时默认放入）</label>`,
    foot: `${edit ? `<button type="button" class="btn stop" id="bn-del" style="margin-right:auto">删除仓位</button>` : ""}<button type="button" class="btn" data-close>取消</button><button type="button" class="btn primary" id="bn-ok">保存</button>` });
  md.q("#bn-ok").onclick = async () => {
    const pl = edit ? place : md.q(".place-pick").dataset.place;
    if (!pl) { toast("先选择仓储地点"); return; }
    try {
      const r = await api("stock_bin_save", { place: pl, name: md.q("#bn-name").value, desc: md.q("#bn-desc").value, default: md.q("#bn-def").checked, old: edit ? name : "" });
      state.stockSel = r.bin; stockShow(r); toast(edit ? "仓位已保存" : "仓位已创建"); md.close();
    } catch (e) { toast(e.message); }
  };
  if (edit) md.q("#bn-del").onclick = async () => {
    if (!confirmInline(md.q("#bn-del"), "再次点击确认删除，仓位内物品将移回总仓")) return;
    try { const r = await api("stock_bin_delete", { place, name }); state.stockSel = place; stockShow(r); toast(`仓位已删除${r.moved ? "，物品已移回总仓" : ""}`); md.close(); }
    catch (e) { toast(e.message); }
  };
  setTimeout(() => md.q("#bn-name").focus(), 0);
}
function confirmInline(btn, text) {                            // 危险操作：第一次点变成「再点一次」，3 秒内再点才执行
  if (btn.dataset.armed) return true;
  btn.dataset.armed = "1"; const old = btn.textContent; btn.textContent = text;
  setTimeout(() => { delete btn.dataset.armed; btn.textContent = old; }, 3000);
  return false;
}
async function stockLedgerDialog() {
  const st = { start: "", end: "", type: "", place: "", q: "", page: 1, size: 20 };
  const md = openModal({ title: "仓储流水", drawer: true,
    body: `<div class="row ledger-bar">
        <div class="seg" id="lg-quick"><button type="button" data-d="7">近 7 天</button><button type="button" data-d="30">近 30 天</button><button type="button" data-d="90">近 90 天</button><button type="button" data-d="0" class="on">全部</button></div>
        <label class="field">开始日期<input type="date" class="input" id="lg-start"></label><span class="faint" style="padding-bottom:9px">—</span>
        <label class="field">结束日期<input type="date" class="input" id="lg-end"></label>
        <label class="field">类型<select class="input" id="lg-type"><option value="">全部类型</option></select></label>
        <label class="field">地点<select class="input" id="lg-place"><option value="">全部地点</option></select></label>
        <label class="field" style="flex:1">搜索<input class="input" id="lg-q" placeholder="物品名 / 备注"></label>
        <button type="button" class="btn primary" id="lg-go">查询</button></div>
      <div id="lg-list"><p class="muted">加载中…</p></div>
      <div class="row ledger-pages" id="lg-pages"></div>` });
  const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  let filled = false;
  const load = async () => {
    let r;
    try { r = await api("stock_ledger", st); } catch (e) { md.q("#lg-list").innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
    if (!filled) {
      filled = true;
      md.q("#lg-type").innerHTML += r.types.map((x) => `<option>${esc(x)}</option>`).join("");
      md.q("#lg-place").innerHTML += r.places.map((x) => `<option>${esc(x)}</option>`).join("");
    }
    st.page = r.page;
    md.q("#lg-list").innerHTML = r.rows.length ? `<table class="t"><tr><th>时间</th><th>类型</th><th>内容</th><th></th></tr>${r.rows.map((x) => ledgerEntryHTML(x, true)).join("")}</table>`
      : `<p class="muted" style="margin:0">此时间段内没有符合条件的记录</p>`;
    md.q("#lg-pages").innerHTML = `<span class="faint">共 ${r.total} 条</span>
      <select class="input" id="lg-size">${[10, 20, 50].map((n) => `<option value="${n}" ${n === r.size ? "selected" : ""}>${n} 条/页</option>`).join("")}</select>
      <button type="button" class="btn small" data-pg="${r.page - 1}" ${r.page <= 1 ? "disabled" : ""}>‹</button>
      <b>${r.page} / ${r.pages}</b>
      <button type="button" class="btn small" data-pg="${r.page + 1}" ${r.page >= r.pages ? "disabled" : ""}>›</button>
      <span class="faint">前往</span><input class="input" id="lg-jump" size="3" value="${r.page}"><span class="faint">页</span>`;
  };
  const go = () => { st.start = md.q("#lg-start").value; st.end = md.q("#lg-end").value; st.type = md.q("#lg-type").value;
    st.place = md.q("#lg-place").value; st.q = md.q("#lg-q").value; st.page = 1; load(); };
  md.q("#lg-go").onclick = go;
  md.q("#lg-q").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } };
  md.q("#lg-quick").onclick = (e) => {
    const b = e.target.closest("[data-d]");
    if (!b) return;
    md.q("#lg-quick").querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    const n = +b.dataset.d, today = new Date();
    md.q("#lg-end").value = n ? ymd(today) : "";
    md.q("#lg-start").value = n ? ymd(new Date(today.getFullYear(), today.getMonth(), today.getDate() - (n - 1))) : "";
    go();
  };
  md.q("#lg-pages").onclick = (e) => { const b = e.target.closest("[data-pg]"); if (b && !b.disabled) { st.page = +b.dataset.pg; load(); } };
  md.q("#lg-pages").onchange = (e) => { if (e.target.id === "lg-size") { st.size = +e.target.value; st.page = 1; load(); } };
  md.q("#lg-pages").onkeydown = (e) => { if (e.target.id === "lg-jump" && e.key === "Enter") { e.preventDefault(); st.page = +e.target.value || 1; load(); } };
  md.q("#lg-list").onclick = async (e) => {
    const b = e.target.closest("[data-undo]");
    if (!b) return;
    try { stockShow(await api("stock_undo", { batch: b.dataset.undo })); toast("已撤销"); load(); } catch (err) { toast(err.message); }
  };
  load();
}

PAGES.stock = async () => {
  const f = (state.stockF ||= { q: "", kind: "", qr: "", goal: "", sort: "name", desc: false });
  f.goal ??= "";
  state.stockSel ??= "";
  $("#page").innerHTML = `<div class="row" style="justify-content:space-between;align-items:flex-start;flex-wrap:nowrap">
      <div><h1>库存</h1><p class="lede">按地点和仓位管理物品。入库默认存放在游戏中最后打开库存的地点；品质影响目标门槛和成品属性，建议填写。</p></div>
      <span class="row" style="flex-wrap:nowrap">${segH("st-mode", [["simple", "简易"], ["pro", "经营"]], "pro", "库存模式")}<button type="button" class="btn" id="st-count"></button><button type="button" class="btn" id="st-ledger">仓储流水</button><button type="button" class="btn primary" id="st-in">入库</button></span></div>
    <div id="st-review"></div>
    <div class="stock-bar">
      <input class="input grow" id="sf-q" placeholder="搜索物品名（中文 / 英文）" value="${esc(f.q)}">
      ${segH("sf-kind", [["", "全部"], ["矿物", "矿物"], ["材料", "材料"], ["物品", "物品"]], f.kind, "类别")}
      <select class="input" id="sf-qr"><option value="">全部品质</option><option value="none" ${f.qr === "none" ? "selected" : ""}>未填品质</option>${TIERS.map(([v, l]) => `<option value="${v}" ${f.qr === v ? "selected" : ""}>${l}</option>`).join("")}</select>
      ${segH("sf-goal", [["", "全部"], ["used", "目标占用"], ["free", "空闲"], ["reserved", "保留"]], f.goal, "目标")}
      <button type="button" class="btn" id="sf-reset">重置</button></div>
    <div class="stock-split"><aside class="stock-tree" id="st-tree"></aside><section id="st-main"><div class="panel"><p class="muted" style="margin:0">加载中…</p></div></section></div>
    <div class="row" style="justify-content:space-between;margin-top:28px"><h2 style="margin:0">最近记录</h2><button type="button" class="btn small" id="st-ledger2">查看全部流水</button></div>
    <div class="panel" id="st-hist" style="margin-top:10px"></div>`;
  const redrawMain = () => { if (state.stockData) $("#st-main").innerHTML = stockMainHTML(); };
  $("#sf-q").oninput = () => { f.q = $("#sf-q").value; redrawMain(); };
  $("#sf-kind").onchange = () => { f.kind = $("#sf-kind").value; redrawMain(); };
  $("#sf-qr").onchange = () => { f.qr = $("#sf-qr").value; redrawMain(); };
  $("#sf-goal").onchange = () => { f.goal = $("#sf-goal").value; redrawMain(); };
  $("#sf-reset").onclick = () => { Object.assign(f, { q: "", kind: "", qr: "", goal: "", sort: "name", desc: false }); renderPage(); };
  $("#st-ledger").onclick = $("#st-ledger2").onclick = () => stockLedgerDialog();
  $("#st-mode").onchange = (e) => stockSetMode(e.target.value);
  $("#st-count").onclick = async () => {
    try { const r = await api("count_toggle"); if (r.error) toast(r.error); state.count = { ...(state.count || {}), running: !!r.running }; countDraw(); }
    catch (err) { toast(err.message); }
  };
  api("count_state").then((r) => { state.count = r; countDraw(); }).catch(() => {});
  $("#st-in").onclick = () => {
    const { place, bin } = stockSelParts();
    const g = place ? stockGroups().find((x) => x.label === place) : null;
    stockInDialog(g && g.state !== "unmatched" ? { place, bin: bin || "" } : {});
  };
  $("#st-tree").onclick = (e) => {
    if (e.target.closest("#st-newbin")) { const { place } = stockSelParts(); binDialog({ place: stockGroups().find((x) => x.label === place && x.state !== "unmatched") ? place : "" }); return; }
    const b = e.target.closest("[data-sel]");
    if (!b) return;
    state.stockSel = b.dataset.sel;
    stockDraw();
  };
  $("#st-main").onclick = async (e) => {
    const so = e.target.closest("[data-sort]");
    if (so) {                                                   // 点表头排序：同一列再点换方向
      const k = so.dataset.sort;
      f.desc = f.sort === k ? !f.desc : ["qty", "value", "changed"].includes(k);
      f.sort = k; redrawMain(); return;
    }
    const a = e.target.closest("[data-a]");
    if (a) {
      const r = state.stockData.rows[+a.closest(".acts").dataset.i];
      const keep = async () => {
        try { stockShow(await api("stock_reserve", { ...rowArgs(r), on: !r.reserved })); toast(r.reserved ? "已取消保留" : "已保留：此行不用于目标"); }
        catch (err) { toast(err.message); }
      };
      if (a.dataset.a === "more") {
        menu(a, [["移库", () => stockMoveDialog(r)], ["改品质", () => stockQualityDialog(r, a)], [r.reserved ? "取消保留" : "保留", keep]]);
        return;
      }
      ({ out: stockOutDialog, set: stockSetDialog })[a.dataset.a](r, a);
      return;
    }
    const { place, bin } = stockSelParts();
    if (e.target.closest("#st-in-here")) { stockInDialog({ place, bin: bin || "" }); return; }
    if (e.target.closest("#st-newbin2")) { binDialog({ place }); return; }
    if (e.target.closest("#st-binset")) { binDialog({ place, name: bin, edit: true }); return; }
    const pb = e.target.closest("#st-price");
    if (pb) {
      pb.disabled = true; pb.textContent = "查询中…";
      try { const r = await api("stock_prices"); stockShow(r); toast(r.checked ? `已查询 ${r.checked} 项，${r.found} 项有报价` : "库存中没有已填品质的物品，无法查询"); }
      catch (err) { toast(err.message); pb.disabled = false; pb.textContent = "查询估值"; }
      return;
    }
    if (e.target.closest("#st-reloc")) {
      const from = state.stockSel, to = await pickPlace("");
      if (!to) return;
      try { const r = await api("stock_relocate", { location: from, to }); state.stockSel = to; stockShow(r); toast(`已归入 ${to}（${r.relocated} 行）`); }
      catch (err) { toast(err.message); }
      return;
    }
    if (e.target.closest("#st-keep")) {
      try { stockShow(await api("stock_keep_custom", { location: state.stockSel })); toast("已保留为自定义地点"); } catch (err) { toast(err.message); }
    }
  };
  $("#st-hist").onclick = async (e) => {
    const b = e.target.closest("[data-undo]");
    if (!b) return;
    try { stockShow(await api("stock_undo", { batch: b.dataset.undo })); toast("已撤销"); } catch (err) { toast(err.message); }
  };
  try { stockShow(await api("stock")); } catch (e) { $("#st-main").innerHTML = `<div class="panel"><p class="bad">${esc(e.message)}</p></div>`; return; }
  const pre = state.stockPrefill;                              // 从物品查询 / F8「去库存录入」过来的：直接打开入库
  if (pre) { state.stockPrefill = null; stockInDialog(pre); }
};

// ================================================================ 1.6.62：库存简易模式（普通玩家：盘点、入库、出库、改数量、撤销）
// 老用户（已经有库存记录）直接经营模式；新用户第一次打开问一次（关掉就按简易）。右上角随时切换，切换只改显示，数据一样都不动
const stockPro = PAGES.stock;
PAGES.stock = async () => {
  let mode = state.status?.settings?.stock_mode;
  if (!mode) { $("#page").innerHTML = `<h1>库存</h1>`; mode = await stockAskMode(); }
  return mode === "pro" ? stockPro() : stockSimple();
};
async function stockSetMode(mode, quiet = false) {
  try { state.status.settings = await api("set_settings", { stock_mode: mode }); } catch (e) { toast(e.message); }
  if (!quiet) renderPage();
}
function stockAskMode() {                                      // 同时进来两次（页面重画）只问一次
  return (stockAskMode.p ||= stockAskMode1().finally(() => { stockAskMode.p = null; }));
}
async function stockAskMode1() {
  let d = null;
  try { d = await api("stock"); } catch (e) { return "simple"; }
  if (d.rows.length || d.history.length) { await stockSetMode("pro", true); return "pro"; }
  return await new Promise((done) => {
    let picked = "simple";
    const md = openModal({ title: "库存", body: `<div class="place-grid">
        <button type="button" data-m="simple"><b>简易</b><small>盘点、入库、出库、撤销</small></button>
        <button type="button" data-m="pro"><b>经营</b><small>仓位、流水、估值、目标占用</small></button></div>`,
      onClose: async () => { await stockSetMode(picked, true); done(picked); } });
    md.q(".place-grid").onclick = (e) => { const b = e.target.closest("[data-m]"); if (b) { picked = b.dataset.m; md.close(); } };
  });
}
async function stockSimple() {
  const f = (state.stockS ||= { place: "", q: "", sort: "name", desc: false });
  $("#page").innerHTML = `<div class="row" style="justify-content:space-between;align-items:center;gap:12px">
      <div class="row" style="align-items:baseline;gap:14px"><h1 style="margin:0">库存</h1><span class="faint num" id="ss-count"></span></div>
      <span class="row" style="gap:8px">${segH("st-mode", [["simple", "简易"], ["pro", "经营"]], "simple", "库存模式")}
        <button type="button" class="btn" id="st-count"></button><button type="button" class="btn" id="ss-undo">撤销</button><button type="button" class="btn primary" id="st-in">入库</button></span></div>
    <div id="st-review"></div>
    <div class="stock-bar" style="margin-top:20px"><button type="button" class="btn" id="ss-place" aria-haspopup="listbox" style="min-width:220px;justify-content:space-between"></button>
      <input class="input" id="ss-q" placeholder="搜索物品" value="${esc(f.q)}" style="border-radius:var(--pill);padding:0 18px;flex:1;max-width:340px"></div>
    <div class="panel" id="ss-table"><p class="muted" style="margin:0">加载中…</p></div>
    <div class="row" style="justify-content:space-between;margin-top:28px"><h2 style="margin:0">记录</h2><button type="button" class="btn small" id="st-ledger">全部</button></div>
    <div class="panel" id="st-hist" style="margin-top:10px"></div>`;
  $("#st-mode").onchange = (e) => stockSetMode(e.target.value);
  $("#st-ledger").onclick = () => stockLedgerDialog();
  $("#ss-q").oninput = () => { f.q = $("#ss-q").value; stockSimpleDraw(); };
  $("#st-in").onclick = () => stockInDialog(f.place ? { place: f.place } : {});
  $("#st-count").onclick = async () => {
    try { const r = await api("count_toggle"); if (r.error) toast(r.error); state.count = { ...(state.count || {}), running: !!r.running }; countDraw(); }
    catch (err) { toast(err.message); }
  };
  api("count_state").then((r) => { state.count = r; countDraw(); }).catch(() => {});
  $("#ss-undo").onclick = (e) => {                             // 撤的是全部地点里最近的一笔（不管筛选），先写清楚撤哪笔再确认
    const last = stockLastUndo();
    if (!last) return;
    popconfirm(e.currentTarget, { title: "撤销上一笔", okText: "撤销",
      body: `<div style="font-size:14px">${esc(last.type)}</div>${(last.items || []).slice(0, 3).map((t) => `<div class="muted" style="font-size:13.5px">${esc(t)}</div>`).join("")}${(last.items || []).length > 3 ? `<div class="faint" style="font-size:13px">…另有 ${last.items.length - 3} 行</div>` : ""}`,
      onOk: async (p) => { try { stockShow(await api("stock_undo", { batch: last.batch })); toast("已撤销"); } catch (err) { p.error(err.message); return false; } } });
  };
  $("#ss-place").onclick = (e) => {
    const d = state.stockData;
    if (!d) return;
    const counts = {};
    d.rows.forEach((r) => { counts[r.place] = (counts[r.place] || 0) + 1; });
    const places = [["", "全部地点", d.rows.length], ...Object.keys(counts).sort((a, b) => a.localeCompare(b, "zh-CN")).map((p) => [p, p, counts[p]])];
    const p = popOver(e.currentTarget, `<div style="padding:8px;width:280px"><input class="input" placeholder="搜索地点" aria-label="搜索地点" style="margin-bottom:6px">
      <div role="listbox" style="max-height:264px;overflow-y:auto" class="menu-list"></div></div>`, { cls: "menu", align: "left" });
    if (!p) return;
    const list = p.q("[role=listbox]"), inp = p.q("input");
    const draw = () => {
      const q = placeNorm(inp.value);
      const hit = places.filter(([v, l]) => !q || placeNorm(l).includes(q));
      list.innerHTML = hit.length ? hit.map(([v, l, n]) => `<button type="button" role="option" data-v="${esc(v)}" aria-selected="${v === f.place}" style="display:flex;justify-content:space-between;gap:12px${v === f.place ? ";background:#222227" : ""}"><span>${esc(l)}</span><span class="faint num">${n}</span></button>`).join("")
        : `<p class="faint" style="margin:8px 12px">没有匹配的地点</p>`;
    };
    draw();
    inp.oninput = draw;
    list.onclick = (ev) => { const b = ev.target.closest("[data-v]"); if (!b) return; f.place = b.dataset.v; p.close(); stockSimpleDraw(); };
    setTimeout(() => inp.focus(), 0);
  };
  $("#ss-table").onclick = (e) => {
    const so = e.target.closest("[data-sort]");
    if (so) { const k = so.dataset.sort; f.desc = f.sort === k ? !f.desc : k === "qty"; f.sort = k; stockSimpleDraw(); return; }
    const a = e.target.closest("[data-a]");
    if (!a) return;
    const r = state.stockData.rows[+a.closest(".acts").dataset.i];
    ({ out: stockOutDialog, set: stockSetDialog })[a.dataset.a](r, a);
  };
  $("#st-hist").onclick = async (e) => {
    const b = e.target.closest("[data-undo]");
    if (!b) return;
    try { stockShow(await api("stock_undo", { batch: b.dataset.undo })); toast("已撤销"); } catch (err) { toast(err.message); }
  };
  try { stockShow(await api("stock")); } catch (e) { $("#ss-table").innerHTML = `<p class="bad" style="margin:0">${esc(e.message)}</p>`; return; }
  const pre = state.stockPrefill;
  if (pre) { state.stockPrefill = null; stockInDialog(pre); }
}
// 品质格：制造出来的东西显示各槽平均，鼠标停上去看「框架 858 · 线缆 916 · 功率调节器 959」（1.6.67）
function qCell(r) {
  const t = esc(r.q != null ? r.q : r.qkey === "unknown" ? "未知" : r.quality);
  return r.craft ? `<span class="craftq" data-tip="${esc(r.craft)}">${t}</span>` : t;
}
function stockLastUndo() { return (state.stockData?.history || []).find((x) => !x.undone && x.type !== "撤销"); }
function stockSimpleDraw() {
  const d = state.stockData, f = state.stockS;
  if (!d || !$("#ss-table")) return;
  if (f.place && !d.rows.some((r) => r.place === f.place)) f.place = "";
  const q = f.q.trim().toLowerCase();
  let rows = d.rows.map((r, i) => ({ ...r, _i: i })).filter((r) => (!f.place || r.place === f.place) && (!q || `${r.item} ${r.zh} ${r.en}`.toLowerCase().includes(q)));
  const key = f.sort === "qty" ? (r) => +r.qty : (r) => r.zh || r.en || r.item;
  rows.sort((a, b) => { const x = key(a), y = key(b); const c = typeof x === "number" ? x - y : String(x).localeCompare(String(y), "zh-CN"); return f.desc ? -c : c; });
  const paths = Object.fromEntries(stockGroups().map((g) => [g.label, g.path]));
  const sh = (k, label) => `<button type="button" class="th-sort${f.sort === k ? " on" : ""}" data-sort="${k}">${label}${f.sort === k ? (f.desc ? " ↓" : " ↑") : ""}</button>`;
  $("#ss-count").textContent = `${f.place || q ? rows.length + " / " : ""}${d.rows.length} 条`;
  $("#ss-place").innerHTML = `<span>${esc(f.place || "全部地点")}</span><span class="faint" aria-hidden="true">▾</span>`;
  $("#ss-table").innerHTML = rows.length ? `<div class="tscroll"><table class="t stock-t"><tr><th>${sh("name", "物品")}</th><th>品质</th><th>地点</th><th class="n">${sh("qty", "数量")}</th><th class="n"></th></tr>
    ${rows.map((r) => `<tr><td>${esc(r.item)}</td>
      <td class="${r.qkey === "unknown" ? "bad" : "muted"} num">${qCell(r)}</td>
      <td class="muted"><span data-tip="${esc(paths[r.place] || r.place)}">${esc(r.place)}</span>${r.bin && r.bin !== MAIN_BIN ? ` <span class="faint">/ ${esc(r.bin)}</span>` : ""}</td>
      <td class="n">${esc(qtyText(r.qty, r.unit))}</td>
      <td class="n"><span class="acts" data-i="${r._i}"><button type="button" class="btn small" data-a="out">出库</button><button type="button" class="btn small" data-a="set">改数量</button></span></td></tr>`).join("")}</table></div>`
    : `<div class="empty">${d.rows.length ? `没有匹配的库存 <button type="button" class="btn small" id="ss-clear" style="margin-left:10px">清除筛选</button>` : "库存为空"}</div>`;
  if ($("#ss-clear")) $("#ss-clear").onclick = () => { f.place = ""; f.q = ""; $("#ss-q").value = ""; stockSimpleDraw(); };
  const h = d.history.slice(0, 5);
  $("#st-hist").innerHTML = h.length ? `<table class="t"><tr><th>时间</th><th>类型</th><th>内容</th><th></th></tr>${h.map((x) => ledgerEntryHTML(x)).join("")}</table>` : `<p class="muted" style="margin:0">暂无记录</p>`;
  const last = stockLastUndo(), ub = $("#ss-undo");
  ub.disabled = !last;
  delete ub.dataset.tip;
  countDraw();
}

// ================================================================ 目标：库存 × 维科洛兑换 / 制造 / 交易
async function goalAdd(kind, ref, times = 1) {
  try {
    const r = await api("goal_add", { kind, ref, times: parseInt(times) || 1 });
    state.goals = r;
    toast("已加入目标清单");
  } catch (e) { toast(e.message); }
}

PAGES.goals = async () => {
  $("#page").innerHTML = `<h1>目标清单</h1><p class="lede">在「维科洛兑换」或「制造」中点击「加入目标清单」，此页按库存计算缺少的材料及获取方式。
    多个目标需要同一材料时，排在前面的目标优先使用库存。</p><div id="gout"><p class="muted">计算中…</p></div>`;
  try { state.goals = await api("goals"); } catch (e) { $("#gout").innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
  goalsDraw();
};

function effectHTML(g) {
  const c = g.craft;
  if (!c || !c.slots.some((x) => x.curves.length)) return "";
  const avg = c.slots.filter((x) => x.curves.length && x.q != null);
  return `<details class="eff-box" style="margin-top:12px" ${avg.length ? "open" : ""}><summary style="cursor:pointer"><b>品质影响</b> <span class="faint">现有材料品质对成品属性的影响</span>
      <span class="tagrow" style="display:inline-flex;margin:0 0 0 8px;vertical-align:middle">${c.head.tags.map((t) => `<span class="tag${/^S\d/.test(t) ? " sz" : ""}">${esc(t)}</span>`).join("")}</span></summary>
    <div class="row" style="justify-content:flex-end;gap:6px;margin-top:8px"><span class="faint" style="font-size:12.5px">品质：</span>
      <button class="btn small" data-preset="min">最低</button><button class="btn small" data-preset="stock">按库存</button><button class="btn small" data-preset="shop">商店品质 500</button><button class="btn small" data-preset="max">最佳</button></div>
    <div class="slots gslots" data-key="${esc(g.ref)}" data-id="${g.id}">${c.slots.map((sl) => slotCardHTML(sl, sl.q, sl.q != null ? "默认取分配给此目标的库存平均品质（多箱混合时成品为加权平均）" : "库存中暂无已填品质的材料，按 500 计算")).join("")}</div>
    <div class="eff-out" id="eff-${g.id}" style="margin-top:12px"></div></details>`;
}
async function goalFinishDialog(id) {                          // 目标「做完了」：先看要扣哪些材料，确认后从库存扣掉
  let p;
  try { p = await api("goal_finish_preview", { id }); } catch (e) { toast(e.message); return; }
  if (p.short.length) { toast("材料不足，无法扣除：" + p.short.join("、")); return; }
  const md = openModal({ title: p.times > 1 ? "完成一次" : "完成", sub: esc(p.title),
    body: `<p class="muted" style="margin:0">从库存扣除完成一次所用的材料（记为一笔出库，原因「用于制造」，可在库存页撤销）${p.times > 1 ? `；此目标剩余 ${p.times - 1} 次` : "；完成后此目标将从列表中移除"}：</p>
      <table class="t"><tr><th>材料</th><th>地点</th><th>品质</th><th class="n">扣除</th></tr>
      ${p.takes.map((x) => `<tr><td>${esc(x.name)}</td><td class="muted">${esc(x.place)}</td><td class="muted">${esc(x.quality)}</td><td class="n">${esc(qtyText(x.qty, x.unit))}</td></tr>`).join("")}</table>`,
    foot: `<button type="button" class="btn" data-close>取消</button><button type="button" class="btn primary" id="gf-go">扣除库存</button>` });
  md.q("#gf-go").onclick = async () => {
    try {
      const r = await api("goal_finish", { id });
      state.goals = r; goalsDraw(); md.close();
      toast(`已从库存扣除 ${r.finished.lines} 行材料${r.finished.left ? `，剩余 ${r.finished.left} 次` : "，目标已完成"}（可在库存页撤销）`);
    } catch (e) { toast(e.message); }
  };
}
function goalsDraw() {
  const d = state.goals, box = $("#gout");
  if (!d || !box) return;
  if (!d.goals.length) {
    box.innerHTML = `<div class="panel"><p class="muted" style="margin:0">暂无目标。在 <a href="#wikelo">维科洛兑换</a> 或 <a href="#craft">制造</a> 中点击「加入目标清单」添加。</p></div>`;
    return;
  }
  const qty = (v, u) => `${+(+v).toFixed(3)} ${u === "个" ? "" : esc(u)}`.trim();
  const goalHTML = (g, i) => {
    const pct = Math.round(g.progress * 100);
    const rows = g.rows.map((r) => `<tr>
      <td>${r.slot ? `<span class="faint">${esc(r.slot_zh || r.slot)}：</span>` : ""}${esc(r.zh || r.en)}${r.zh && r.zh !== r.en ? `<div class="faint" style="font-size:12px">${esc(r.en)}</div>` : ""}
        ${r.minq ? `<div class="faint" style="font-size:12px">品质 ≥${r.minq}</div>` : ""}${r.others.length ? `<div class="faint" style="font-size:12px">可替代：${esc(r.others.join("、"))}</div>` : ""}</td>
      <td class="n">${qty(r.need, r.unit)}</td>
      <td class="n">${qty(r.have, r.unit)}${r.from.length ? `<div class="faint" style="font-size:12px">${esc(r.from.join("，"))}</div>` : ""}</td>
      <td class="n">${r.short > 0 ? `<b class="bad">${qty(r.short, r.unit)}</b>` : `<span class="good">已满足</span>`}
        ${r.unknown ? `<div class="faint" style="font-size:12px">另有 ${r.unknown} 品质未知，填写品质后计入</div>` : ""}</td>
      <td class="muted" style="font-size:13px">${r.short > 0 ? esc(r.tip || "") : ""}
        <div><button class="btn small g-in" data-g="${g.id}" data-r="${g.rows.indexOf(r)}" style="margin-top:4px">入库</button></div></td></tr>
      <tr class="g-form" id="gf-${g.id}-${g.rows.indexOf(r)}" hidden><td colspan="5"><div class="row" style="gap:8px;align-items:flex-end">
        <span class="faint" style="padding-bottom:8px">将现有的 ${esc(r.zh || r.en)} 入库：</span>
        <label class="field">数量（${r.unit === "SCU" ? "SCU，可含小数" : "个"}）<input class="input gf-q" size="6"></label>
        <label class="field">品质<input class="input gf-qual" size="5" placeholder="${r.minq ? "例：" + r.minq : "选填"}"></label>
        <div class="field">存放地点${placeBtnHTML(defaultPlace() || d.last_location || "")}</div>
        <button class="btn primary gf-ok" data-en="${esc(r.en)}" data-zh="${esc(r.zh || "")}" data-unit="${esc(r.unit)}">入库</button></div></td></tr>`).join("");
    return `<div class="panel">
      <div class="goal-row"><div><b>${esc(g.title)}</b>${g.missing ? ` <span class="bad">（新数据中已无此兑换或蓝图）</span>` : ""}
        <div class="faint" style="font-size:13px">${g.done ? `<span class="good">材料已齐全</span>` : `完成 ${pct}%`}</div></div>
        <div class="row" style="gap:6px">
          <label class="field" style="flex-direction:row;align-items:center;gap:4px">次数<input class="input g-times" data-id="${g.id}" size="3" value="${g.times}"></label>
          <button class="btn small" data-act="up" data-id="${g.id}" ${i === 0 ? "disabled" : ""} title="提高优先级">↑</button>
          <button class="btn small" data-act="down" data-id="${g.id}" ${i === d.goals.length - 1 ? "disabled" : ""} title="降低优先级">↓</button>
          <button class="btn small" data-act="finish" data-id="${g.id}" ${g.done ? "" : "disabled"} title="${g.done ? "从库存扣除完成一次所用的材料" : "材料齐全后可用"}">${g.times > 1 ? "完成一次" : "完成"}</button>
          <button class="btn small" data-act="del" data-id="${g.id}">删除</button></div>
        <div class="meter ${g.done ? "" : "warn"}"><i style="width:${pct}%"></i></div></div>
      ${rows ? `<table class="t" style="margin-top:10px"><tr><th>材料</th><th class="n">需要</th><th class="n">已有</th><th class="n">缺少</th><th>获取方式</th></tr>${rows}</table>` : ""}
      ${g.slots_q ? effectHTML(g) : ""}</div>`;
  };
  const sf = d.shortfall;
  box.innerHTML = d.goals.map(goalHTML).join("") + `
    <h2>合计缺少</h2>
    <div class="panel">${sf.length ? `<table class="t"><tr><th>材料</th><th class="n">缺少</th><th>获取方式</th><th class="n">玩家市场参考价</th></tr>
      ${sf.map((x, i) => `<tr><td>${esc(x.zh || x.en)}${x.minq ? `<span class="faint">（品质 ≥${x.minq}）</span>` : ""}</td><td class="n">${qty(x.short, x.unit)}</td>
        <td class="muted" style="font-size:13px">${esc(x.tip || "")}</td><td class="n" id="gp-${i}"><span class="faint">—</span></td></tr>`).join("")}</table>
      <div class="row" style="margin-top:10px;gap:10px"><button class="btn" id="gprice">查询玩家市场价格</button><span id="gtotal" class="muted"></span></div>`
      : `<p class="good" style="margin:0">所有目标的材料均已齐全</p>`}</div>`;
  box.querySelectorAll(".gslots").forEach((sb) => {
    const g = d.goals.find((x) => String(x.id) === sb.dataset.id);
    const draw = (qs) => craftStatsDraw($(`#eff-${sb.dataset.id}`), sb.dataset.key, qs);
    bindSlots(sb, g.craft.slots, draw);
    sb.closest(".eff-box").querySelectorAll("[data-preset]").forEach((b) => (b.onclick = () => slotsPreset(sb, g.craft.slots, b.dataset.preset)));
    draw(slotQualities(sb));
  });
  box.onclick = async (e) => {
    if (e.target.closest(".eff-box [data-preset], .slot")) return;
    const inb = e.target.closest(".g-in");
    if (inb) { const f = $(`#gf-${inb.dataset.g}-${inb.dataset.r}`); f.hidden = !f.hidden; if (!f.hidden) f.querySelector(".gf-q").focus(); return; }
    const ok = e.target.closest(".gf-ok");
    if (ok) {
      const f = ok.closest(".g-form");
      try {
        state.goals = await api("goal_stock_add", { en: ok.dataset.en, zh: ok.dataset.zh, unit: ok.dataset.unit,
          qty: f.querySelector(".gf-q").value, quality: f.querySelector(".gf-qual").value, location: f.querySelector(".place-pick").dataset.place });
        goalsDraw(); toast("已入库");
      } catch (err) { toast(err.message); }
      return;
    }
    const b = e.target.closest("[data-act]");
    if (!b) return;
    if (b.dataset.act === "finish") { goalFinishDialog(b.dataset.id); return; }
    const arg = b.dataset.act === "del" ? { remove: true } : { move: b.dataset.act === "up" ? -1 : 1 };
    const go = async () => { try { state.goals = await api("goal_update", { id: b.dataset.id, ...arg }); goalsDraw(); } catch (err) { toast(err.message); } };
    if (b.dataset.act === "del") popconfirm(b, { title: "删除此目标？", okText: "删除", danger: true, onOk: go });
    else go();
  };
  box.querySelectorAll(".g-times").forEach((el) => (el.onchange = async () => {
    try { state.goals = await api("goal_update", { id: el.dataset.id, times: parseInt(el.value) || 1 }); goalsDraw(); } catch (err) { toast(err.message); }
  }));
  if ($("#gprice")) $("#gprice").onclick = async () => {
    $("#gprice").disabled = true; $("#gtotal").textContent = "查询中…";
    try {
      const r = await api("goal_prices");
      sf.forEach((x, i) => {
        const p = r.rows.find((y) => y.en === x.en && y.minq === x.minq);
        const cell = $(`#gp-${i}`);
        if (!cell) return;
        cell.innerHTML = p && p.price != null ? `${money(p.price)} / ${esc(p.price_unit)}<div class="faint" style="font-size:12px">${esc(p.src)}，约 ${money(p.cost)}</div>` : `<span class="faint">无挂牌</span>`;
      });
      $("#gtotal").innerHTML = r.priced ? `有挂牌的 ${r.priced} 项合计约 <b class="money">${money(r.total)}</b> aUEC${r.unpriced ? `（另有 ${r.unpriced} 项无挂牌）` : ""}。挂牌价仅供参考` : "均无玩家挂牌";
    } catch (err) { $("#gtotal").textContent = err.message; }
    $("#gprice").disabled = false;
  };
}

// ================================================================ 设置与更新
PAGES.settings = () => {
  const s = state.status || {};
  const c = s.settings || {};
  const t = state.tasks.update;
  const running = t && t.state === "running";
  $("#page").innerHTML = `<h1>设置与更新</h1><p class="lede">修改后立即生效，升级后设置保留。</p>
    <div class="two">
      <div class="panel">
        <h3>运行</h3>
        <div class="set"><div>以管理员身份运行<p>游戏以管理员身份运行时需开启，否则热键和自动按键无法使用。下次启动 AT 时生效</p></div><button class="switch ${c.admin !== false ? "on" : ""}" id="admin-sw" aria-label="管理员身份"></button></div>
      </div>
      <div class="panel">
        <h3>更新数据</h3>
        <p class="muted" style="margin:0 0 12px">从 AT 服务器下载 AT 发布的数据包（矿价、制造蓝图、维科洛兑换、星图、商店价格、掉落数据），并更新汉化包。数据包无法下载时，改从各数据网站更新，约需 2–3 分钟。</p>
        <button class="btn primary" id="upd" ${running ? "disabled" : ""}>${running ? "更新中…" : "开始更新"}</button>
        <div class="log" id="log-update" style="margin-top:12px">${esc((state.logs.update || []).join("\n")) || "暂无更新记录"}</div>
      </div>
    </div>
    <h2>热键</h2>
    <div class="panel">
      ${HOTKEYS.map(([k, d, label, sub]) => `<div class="set"><div>${esc(label)}<p>${esc(sub)}</p></div><button type="button" class="btn keycap" data-hk="${k}" data-d="${d}">${esc(((c[k] || d) || "未设置").toUpperCase())}</button></div>`).join("")}
      ${(state.status?.hotkey_warn || []).map((w) => `<p class="warn" style="margin:6px 0;color:var(--warn,#d9822b)">⚠️ ${esc(w)}</p>`).join("")}
    </div>
    <h2>升级 AT</h2>
    <div class="panel" id="upg">
      <p style="margin:0 0 10px">当前版本 <b>AT ${esc(s.version || "")}</b>。${s.frozen ? "AT 检查网上的新版本，下载后自动安装并重新打开。" : "AT 检查网上的新版本，并在「下载」「桌面」以及微信、QQ 接收的文件中查找安装包（Dubhe_x.x.x.zip）。"}
        升级不影响设置、路标、配置、目标和库存。</p>
      <div id="upg-found" class="muted">查找中…</div>
      <div class="row" style="margin-top:10px;gap:8px"><button class="btn" id="upg-scan">检查更新</button>
        ${s.frozen ? "" : `<label class="btn" style="cursor:pointer">选择安装包…<input type="file" id="upg-file" accept=".zip" hidden></label>`}</div>
      <div class="set" style="border:0;padding:12px 0 0"><div>启动时检查更新<p>只读取网上的版本信息，下载需点击「下载并升级」</p></div><button class="switch ${c.update_online !== false ? "on" : ""}" id="upd-sw" aria-label="启动时检查更新"></button></div>
      ${s.frozen && !s.vpk ? "" : `<h3 style="margin:16px 0 6px">回滚到旧版本</h3>
      <p class="muted" style="margin:0 0 8px">${s.vpk ? "新版本出现问题时，可从 AT 服务器装回上一个版本，设置和数据不受影响。" : `新版本出现问题时，可回滚到上一个版本，设置和数据不受影响。每次升级前自动备份当前版本
        （「下载」等文件夹中的旧安装包也列在此处）。`}</p>
      <div id="upg-older" class="muted">查找中…</div>`}
      <div id="upg-prog" style="margin-top:12px" hidden><div class="row" style="justify-content:space-between;margin-bottom:6px">
        <span id="upg-prog-t">准备中</span><span class="faint" id="upg-prog-p"></span></div><div class="meter"><i style="width:0%"></i></div></div>
      <div class="log" id="log-upgrade" style="margin-top:12px${(state.logs.upgrade || []).length ? "" : ";display:none"}">${esc((state.logs.upgrade || []).join("\n"))}</div>
    </div>
    <h2>外观</h2>
    <div class="panel"><div class="set" style="border:0;padding:0"><div>主题</div>${segH("ui-theme", [["dark", "深色"], ["light", "浅色"]], c.theme === "light" ? "light" : "dark", "主题")}</div></div>
    <h2>游戏悬浮窗</h2>
    <div class="panel"><div class="set" style="border:0;padding:0"><div>移动悬浮窗
      <p>悬浮窗默认鼠标穿透，不影响游戏操作。开启此开关后可拖动悬浮窗，调整完成后关闭。</p></div>
      <button class="switch ${state.overlayMove ? "on" : ""}" id="ov-move" aria-label="移动悬浮窗"></button></div>
      <div class="set"><div>大小</div>${segH("ov-scale", [["0.5", "50%"], ["0.75", "75%"], ["1", "100%"]], String(Math.min(1, +(c.hud_scale ?? 1))), "悬浮窗大小")}</div>
      <div class="set"><div>底板</div>${segH("ov-plate", [["0.6", "浅"], ["0.72", "标准"], ["0.85", "深"]], String(+(c.hud_plate ?? 0.72)), "底板")}</div>
      <div class="set"><div>配色</div>${segH("ov-theme", [["默认", "默认"], ["蓝金", "蓝金"], ["浅色", "浅色"]], c.hud_theme || "默认", "悬浮窗配色")}</div></div>
    <h2>遇到问题</h2>
    <div class="panel"><div class="set"><div>问题反馈
      <p>矿物、信号或物品识别错误时，在游戏中按 <kbd>${esc(c.report_key || "F10")}</kbd>（或点击「报告问题」），AT 保存当时的截图、识别文字和显示结果，并自动发给作者用于改进识别。截图中可能有游戏聊天框。</p>
      <div id="fb-list" class="muted" style="font-size:12.5px;margin-top:6px">加载中…</div></div>
      <div class="row" style="flex-direction:column;gap:6px;align-items:flex-end"><button class="switch ${c.feedback_upload !== false ? "on" : ""}" id="fb-sw" aria-label="自动发送反馈" title="自动发送反馈"></button><span class="muted" style="font-size:12px">自动发送</span></div>
      <div class="row" style="flex-direction:column;gap:6px"><button class="btn primary" id="fb-export">导出反馈</button><button class="btn small" id="fb-clear">清空</button></div></div>
    <div class="set"><div>帮助改进识别
      <p>F8 识别物品时，将名字那一行文字的小截图和正确名字发给作者（认错的都发，认对的抽一部分），用于改进识别。不含整屏截图。</p></div>
      <button class="switch ${c.train_upload !== false ? "on" : ""}" id="train-sw" aria-label="帮助改进识别"></button></div>
    <div class="set" style="border:0;padding:0"><div>导出日志
      <p>将运行日志、设置和系统信息打包到桌面，发给作者用于排查问题。不含聊天记录、浏览数据等个人信息。识别类问题（扫描、F8、导航）建议附上出现问题时的游戏截图。</p></div>
      <button class="btn" id="export-logs">导出日志</button></div></div>
    <h2>后台运行</h2>
    <div class="panel"><div class="set" style="border:0;padding:0"><div>关闭窗口后，AT 在屏幕右下角的托盘中继续运行
      <p>F8 识别、自动跑、防挂机和悬浮窗正常可用。双击托盘图标重新打开窗口；右键图标可重启或退出。</p></div>
      <button class="btn stop" id="quit-app">退出 AT</button></div></div>
    <h2>游戏辅助</h2>
    <div class="panel">
      <div class="set"><div>防挂机<p>一段时间无操作时按两次 F12（开关聊天框）</p></div><button class="switch ${c.anti_afk ? "on" : ""}" data-set="anti_afk" aria-label="防挂机"></button></div>
      <div class="set"><div>挂机判定时间<p>单位秒，另加 1–30 秒随机；游戏约 5 分钟无操作会断开连接，最大 240</p></div><input class="input" id="afk" value="${c.afk_seconds || 200}" size="5" inputmode="numeric"></div>
      <div class="set"><div>双击 W 自动跑<p>再按 W 或 S 停止；驾驶飞船或载具时不触发</p></div><button class="switch ${c.autorun ? "on" : ""}" data-set="autorun" aria-label="双击 W 自动跑"></button></div>
      <div class="set" style="border:0;padding-bottom:0"><div>自动跑时冲刺<p>同时按住 Shift</p></div><button class="switch ${c.autorun_sprint ? "on" : ""}" data-set="autorun_sprint" aria-label="自动跑时冲刺"></button></div>
    </div>
    <h2>关于 AT</h2>
    <div class="panel about">
      <div><h3>作者</h3><p>游戏 ID：<b>Adm_TT</b></p></div>
      <div><h3>星际公民邀请码</h3><p>注册星际公民时可填写此邀请码：</p>
        <div class="row" style="margin-top:8px"><code class="code">${REFERRAL_CODE}</code>
          <button class="btn small" id="copy-ref">复制邀请码</button>
          <button class="btn small primary" data-referral>打开注册页</button></div></div>
      <div><h3>版权</h3><p>© 2026 Adm_TT　按 AGPL-3.0 开源：可以使用、修改、转发；转发或发布修改版时须让对方能拿到完整源代码，通过网络让他人远程使用修改版时也一样，并保留版权和许可声明，详见免责声明和 LICENSE</p>
        <p class="muted" style="font-size:13px;margin-top:6px">AT 是玩家自制的非官方工具，与 Cloud Imperium 集团旗下公司无关联。星际公民的游戏内容归 Cloud Imperium Rights LLC 和 Cloud Imperium Rights Limited 所有</p></div>
      <div><h3>数据来源</h3><p class="muted" style="font-size:13px">数据权利归原作者所有，部分数据经 AT 服务器、Gitee、GitHub 转发</p><ul class="src" id="about-src"></ul>
        <div class="row" style="margin-top:8px;gap:8px"><button class="btn small" id="show-disclaimer">免责声明</button><button class="btn small" id="show-licenses">开源组件许可</button></div></div>
    </div>`;
  bindSwitches();
  api("about_info").then((r) => {
    const el = $("#about-src");
    if (el) el.innerHTML = r.sources.map((x, i) => `<li><a href="#" data-src="${i}">${esc(x.name)}</a>：${esc(x.what)}</li>`).join("");
  }).catch(() => {});
  $("#about-src").onclick = (e) => {
    const a = e.target.closest("[data-src]");
    if (!a) return;
    e.preventDefault();
    api("open_source_site", { i: +a.dataset.src }).catch((err) => toast(err.message));
  };
  $("#show-disclaimer").onclick = async () => openModal({ title: "免责声明", body: `<div class="legal" style="max-height:60vh">${await disclaimerHTML()}</div>`, wide: true });
  $("#show-licenses").onclick = async () => {
    const r = await api("third_party_licenses").catch((e) => ({ text: "", error: e.message }));
    openModal({ title: "开源组件许可", wide: true,
      body: r.text ? `<pre class="legal" style="max-height:60vh;white-space:pre-wrap;font-size:12px">${esc(r.text)}</pre>` : `<p class="muted">${esc(r.error || "")}</p>` });
  };
  $("#export-logs").onclick = async () => {
    try { const r = await api("export_logs"); toast(`已保存到桌面：${r.path.split("\\").pop()}（${r.kb} KB）`); }
    catch (e) { toast(e.message); }
  };
  const fbList = async () => {
    const rows = await api("feedback_list").catch(() => []);
    const el = $("#fb-list");
    if (el) el.innerHTML = rows.length ? `共 ${rows.length} 条：` + rows.slice(0, 5).map((r) => `${esc(r.at)} ${esc(r.name.split("_").pop())}${r.note ? "「" + esc(r.note) + "」" : ""}${r.sent ? "（已发送）" : ""}`).join("；") + (rows.length > 5 ? " …" : "") : "暂无记录";
  };
  fbList();
  $("#fb-export").onclick = async () => {
    try { const r = await api("feedback_export"); toast(`已保存到桌面：${r.path.split("\\").pop()}（${r.files} 条，${r.kb} KB）`); }
    catch (e) { toast(e.message); }
  };
  $("#fb-clear").onclick = (e) => popconfirm(e.currentTarget, { title: "清空反馈记录？", sub: "已导出的文件不受影响", okText: "清空", danger: true,
    onOk: async () => { try { await api("feedback_clear"); fbList(); toast("已清空"); } catch (err) { toast(err.message); } } });
  $("#ui-theme").onchange = async (e) => {
    applyTheme(e.target.value);
    try { state.status.settings = await api("set_settings", { theme: e.target.value }); } catch (err) { toast(err.message); }
  };
  for (const [id, key] of [["#ov-scale", "hud_scale"], ["#ov-plate", "hud_plate"]]) {
    $(id).onchange = async (e) => {
      try { state.status.settings = await api("set_settings", { [key]: +e.target.value }); toast("已保存"); } catch (err) { toast(err.message); }
    };
  }
  $("#ov-theme").onchange = async (e) => {
    try { state.status.settings = await api("set_settings", { hud_theme: e.target.value }); toast("已保存"); } catch (err) { toast(err.message); }
  };
  $("#ov-move").onclick = async () => {
    state.overlayMove = !state.overlayMove;
    await api("overlay_move", { on: state.overlayMove });
    toast(state.overlayMove ? "可拖动悬浮窗，调整完成后关闭开关" : "悬浮窗已恢复鼠标穿透");
    renderPage();
  };
  const vnum = (v) => String(v || "").split(".").map(Number).reduce((a, x) => a * 1000 + (x || 0), 0);
  const upgList = (r) => {
    const el = $("#upg-found");
    if (!el) return;
    const on = r.online && !r.found.some((f) => vnum(f.version) >= vnum(r.online.version)) ? r.online : null;
    const onRow = on ? `<div style="margin-bottom:8px"><div class="row" style="justify-content:space-between">
        <span><b>AT ${esc(on.version)}</b> <span class="faint">网上｜${esc(on.date || "")}${on.size ? `｜${(on.size / 1048576).toFixed(1)} MB` : ""}</span></span>
        <button class="btn primary" id="upg-online">下载并升级</button></div>
        ${(on.notes || []).length ? `<ul class="muted" style="margin:6px 0 0;padding-left:20px;font-size:13px">${on.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}</div>` : "";
    el.innerHTML = onRow + (r.found.length ? r.found.slice(0, 3).map((f, i) => `<div class="row" style="justify-content:space-between;margin-bottom:6px">
        <span><b>AT ${esc(f.version)}</b> <span class="faint">${esc(f.where)}｜${esc(f.at)}</span></span>
        <button class="btn ${i === 0 && !on ? "primary" : ""} upg-go" data-p="${esc(f.path)}">升级到 ${esc(f.version)}</button></div>`).join("")
      : on ? "" : `<span class="faint">${r.online_error ? "无法连接更新服务器，未找到更新的安装包" : "当前已是最新版本"}</span>`);
    const old = $("#upg-older");
    if (old) old.innerHTML = (r.older || []).length ? r.older.map((f) => `<div class="row" style="justify-content:space-between;margin-bottom:6px">
        <span><b>AT ${esc(f.version)}</b> ${f.stable ? `<span class="tag qt">稳定版</span>` : ""} <span class="faint">${esc(f.where)}｜${esc(f.at)}</span></span>
        <button class="btn upg-back" data-p="${esc(f.path)}" data-v="${esc(f.version)}" data-a="${esc(f.action || "回滚到")}">${esc(f.action || "回滚到")} ${esc(f.version)}</button></div>`).join("")
      : `<span class="faint">${state.status?.vpk ? "点击「检查更新」查看可回滚的版本" : "暂无可回滚的版本（下次升级时自动备份当前版本）"}</span>`;
  };
  const upgStart = () => { $("#log-upgrade").style.display = ""; state.logs.upgrade = []; $("#log-upgrade").textContent = "开始升级…"; upgProgress("开始"); };
  api("upgrade_check").then(upgList).catch(() => {});
  (state.logs.upgrade || []).forEach(upgProgress);          // 切走再回到设置页：进度条接着显示
  if (state.tasks?.upgrade?.state === "error") upgProgress("❌");
  $("#upg-scan").onclick = async (e) => {
    const b = e.currentTarget; b.disabled = true; b.textContent = "检查中…";
    try { upgList(await api("upgrade_check", { online: true })); } catch (err) { toast(err.message); }
    b.disabled = false; b.textContent = "检查更新";
  };
  $("#fb-sw").onclick = async (e) => {
    const on = !e.currentTarget.classList.contains("on");
    e.currentTarget.classList.toggle("on", on);
    try { state.status.settings = await api("set_settings", { feedback_upload: on }); } catch (err) { toast(err.message); }
  };
  $("#train-sw").onclick = async (e) => {
    const on = !e.currentTarget.classList.contains("on");
    e.currentTarget.classList.toggle("on", on);
    try { state.status.settings = await api("set_settings", { train_upload: on }); } catch (err) { toast(err.message); }
  };
  $("#upd-sw").onclick = async (e) => {
    const on = !e.currentTarget.classList.contains("on");
    e.currentTarget.classList.toggle("on", on);
    try { state.status.settings = await api("set_settings", { update_online: on }); } catch (err) { toast(err.message); }
  };
  $("#upg").addEventListener("click", async (e) => {
    const back = e.target.closest(".upg-back");
    if (back) {
      const md = openModal({ title: `${back.dataset.a} AT ${back.dataset.v}`, body: `<p style="margin:0">${back.dataset.p === "vpk:prev" ? "从 AT 服务器下载该版本，安装完成后 AT 自动重启。设置和记录不受影响。" : "先备份当前版本（备份失败则不做任何改动），安装完成后 AT 自动重启。"}</p>`,
        foot: `<button type="button" class="btn" data-close>取消</button><button type="button" class="btn primary" id="rb-ok">${esc(back.dataset.a)}</button>` });
      md.q("#rb-ok").onclick = async () => {
        md.close(); back.disabled = true;
        try { upgStart(); const r = await api("upgrade_rollback", { path: back.dataset.p }); if (r.error) throw new Error(r.error); }
        catch (err) { toast(err.message); back.disabled = false; $("#upg-prog").hidden = true; }
      };
      return;
    }
    const ob = e.target.closest("#upg-online");
    if (ob) {
      ob.disabled = true;
      try { upgStart(); const r = await api("upgrade_online"); if (r.error) throw new Error(r.error); }
      catch (err) { toast(err.message); ob.disabled = false; $("#upg-prog").hidden = true; }
      return;
    }
    const b = e.target.closest(".upg-go");
    if (!b) return;
    b.disabled = true;
    try { upgStart(); const r = await api("upgrade_apply", { path: b.dataset.p }); if (r.error) throw new Error(r.error); }
    catch (err) { toast(err.message); b.disabled = false; $("#upg-prog").hidden = true; }
  });
  if ($("#upg-file")) $("#upg-file").onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    try {
      upgStart();
      const resp = await fetch("/api/upgrade_upload_raw", { method: "POST", headers: { "X-Token": TOKEN, "X-File-Name": encodeURIComponent(f.name) }, body: f });
      const j = await resp.json();
      if (!j.ok) throw new Error(j.error || "上传失败");
      if (j.data && j.data.error) throw new Error(j.data.error);
    } catch (err) { toast(err.message); $("#upg-prog").hidden = true; }
    e.target.value = "";
  };
  $("#admin-sw").onclick = async () => {
    state.status.settings = await api("set_settings", { admin: c.admin === false });
    renderPage();
  };
  $("#afk").onchange = async () => {
    const v = +$("#afk").value;
    if (v >= 60 && v <= 240) { state.status.settings = await api("set_settings", { afk_seconds: v }); toast("已保存"); }
    else toast("需在 60–240 秒之间");
  };
  // 1.6.60：热键不用下拉框选，点一下、按一下要用的键（F1–F12；Esc 取消）。1.6.70：所有热键都能改；默认不设的按 Delete 清掉
  document.querySelectorAll("[data-hk]").forEach((b) => (b.onclick = () => {
    const name = b.dataset.hk, d = b.dataset.d, st0 = state.status.settings || {}, cur = ((st0[name] || d) || "未设置").toUpperCase();
    if (b.classList.contains("wait")) return;
    b.classList.add("wait"); b.textContent = d ? "按下新按键" : "按下新按键，Delete 清除";
    const done = (text) => { b.classList.remove("wait"); b.textContent = text; removeEventListener("keydown", onKey, true); document.removeEventListener("mousedown", onOut, true); };
    const onOut = (e) => { if (e.target !== b) done(cur); };
    const onKey = async (e) => {
      e.preventDefault(); e.stopPropagation();
      let k = e.key.toUpperCase();
      if (k === "ESCAPE") { done(cur); return; }
      if (!d && (k === "DELETE" || k === "BACKSPACE")) k = "";
      else if (!/^F([1-9]|1[0-2])$/.test(k)) { toast("仅支持 F1–F12"); return; }
      const st = state.status.settings || {};
      const used = k && HOTKEYS.find(([n, dd]) => n !== name && ((st[n] || dd) || "").toUpperCase() === k);
      if (used) { toast(`${k} 已用于「${used[2]}」`); return; }
      done(k || "未设置");
      try { state.status.settings = await api("set_settings", { [name]: k }); toast(k ? `已改为 ${k}` : "已清除"); refreshStatus(); }
      catch (err) { toast(err.message); b.textContent = cur; }
    };
    addEventListener("keydown", onKey, true); document.addEventListener("mousedown", onOut, true);
  }));
  $("#upd").onclick = async () => {
    if (state.tasks.update && state.tasks.update.state === "running") { toast("正在更新"); return; }
    state.logs.update = [];
    try { const r = await api("update_data"); if (r && r.running) toast("正在更新"); } catch (err) { toast(err.message); }
  };
  $("#quit-app").onclick = () => api("quit").catch(() => {});
  $("#copy-ref").onclick = async () => {
    try { await navigator.clipboard.writeText(REFERRAL_CODE); toast("已复制邀请码"); }
    catch (e) { toast(`邀请码：${REFERRAL_CODE}`); }
  };
  const lg = $("#log-update"); lg.scrollTop = lg.scrollHeight;
};

// ================================================================ 启动
// 作者的星际公民邀请码：点 [data-referral] 的地方都用系统默认浏览器打开注册页
const REFERRAL_CODE = "STAR-4CNY-K3YT";
document.addEventListener("click", (e) => {
  const a = e.target.closest("[data-referral]");
  if (!a) return;
  e.preventDefault();
  api("open_referral").catch((err) => toast(err.message));
});

// 第一次打开：必须一字不差地输入「本软件是免费软件」才能用
const AGREE_TEXT = "本软件是免费软件";
async function disclaimerHTML() {
  try { return await (await fetch("disclaimer.html")).text(); } catch (e) { return ""; }
}

function agreeGate() {
  return new Promise(async (resolve) => {
    const box = document.createElement("div");
    box.className = "gate";
    box.innerHTML = `<div class="gate-card" role="dialog" aria-modal="true" aria-labelledby="gate-t">
      <img src="icon.svg" alt="" width="44" height="44">
      <h2 id="gate-t">使用前请阅读</h2>
      <p>AT 是免费软件，不收取任何费用；任何收费渠道都与 AT 无关。</p>
      <div class="legal">${await disclaimerHTML()}</div>
      <label class="agree"><input type="checkbox" id="gate-ck"> 我已阅读并同意以上免责声明</label>
      <p>然后在下面自己打字输入（不能复制粘贴）：<b class="nocopy">${AGREE_TEXT}</b></p>
      <input class="input" id="gate-in" autocomplete="off" spellcheck="false" placeholder="在这里打字输入">
      <p class="gate-err" id="gate-err" hidden></p>
      <button class="btn primary" id="gate-ok" disabled>同意并开始使用</button></div>`;
    document.body.appendChild(box);
    const input = $("#gate-in"), ok = $("#gate-ok"), err = $("#gate-err"), ck = $("#gate-ck");
    const check = () => { ok.disabled = !(ck.checked && input.value.trim() === AGREE_TEXT); err.hidden = true; };
    input.addEventListener("input", check);
    // 只能自己打字：拦住粘贴、拖放、右键菜单
    const noPaste = (e) => { e.preventDefault(); err.textContent = "不能复制粘贴，要自己打字输入"; err.hidden = false; };
    input.addEventListener("paste", noPaste);
    input.addEventListener("drop", noPaste);
    input.addEventListener("contextmenu", (e) => e.preventDefault());
    input.addEventListener("beforeinput", (e) => { if (/^insertFrom(Paste|Drop|Yank)/.test(e.inputType || "")) noPaste(e); });
    ck.addEventListener("change", check);
    const go = async () => {
      if (ok.disabled) return;
      try { state.status = await api("agree", { text: input.value }); box.remove(); resolve(); }
      catch (e) { err.textContent = e.message; err.hidden = false; }
    };
    ok.onclick = go;
    input.addEventListener("keydown", (e) => e.key === "Enter" && go());
  });
}

// 侧栏底部的「免责声明」：随时可以再看
async function showDisclaimer() {
  const box = document.createElement("div");
  box.className = "gate";
  box.innerHTML = `<div class="gate-card" role="dialog" aria-modal="true"><div class="legal" style="max-height:60vh">${await disclaimerHTML()}</div>
    <button class="btn" id="gate-close">关闭</button></div>`;
  document.body.appendChild(box);
  const close = () => box.remove();
  $("#gate-close").onclick = close;
  box.addEventListener("click", (e) => { if (e.target === box) close(); });
  document.addEventListener("keydown", function esc(e) { if (e.key === "Escape") { close(); document.removeEventListener("keydown", esc); } });
}

// 安装版（1.0.1）：第一次打开时导入旧版天枢的设置和记录；旧版还开着就提示关掉（热键会冲突）
async function legacyCheck() {
  if (!state.status?.frozen) return;
  let r;
  try { r = await api("legacy_scan"); } catch (e) { return; }
  if (r.ask) await legacyAsk(r.found);
  const run = r.running || [];
  if (run.length) toast(`旧版天枢 ${run[0].version} 正在运行，热键会冲突`, ["关闭旧版", async () => {
    try { const q = await api("legacy_quit", { path: run[0].path }); if (q.error) throw new Error(q.error); toast("已关闭旧版天枢"); }
    catch (e) { toast(e.message); }
  }]);
}

function legacyAsk(rows) {
  return new Promise((resolve) => {
    const box = document.createElement("div");
    box.className = "gate";
    const item = (x, i) => `<label class="agree" style="display:flex;gap:8px;align-items:flex-start;margin:6px 0">
      <input type="radio" name="lg" value="${i}" ${i === 0 ? "checked" : ""}>
      <span><b>天枢 ${esc(x.version || "")}</b>　路标 ${x.waypoints} 个，目标 ${x.goals} 个<br>
      <span class="faint" style="font-size:12px">${esc(x.path)}｜最近使用 ${esc(x.used)}</span></span></label>`;
    box.innerHTML = `<div class="gate-card" role="dialog" aria-modal="true" aria-labelledby="lg-t">
      <h2 id="lg-t">导入旧版设置</h2>
      <p>这台电脑上有旧版天枢。可以把它的设置、配置、热键、路标和目标导入 AT，旧版那边不受影响。导入后 AT 会重新打开。</p>
      ${rows.map(item).join("")}
      <p class="gate-err" id="lg-err" hidden></p>
      <div class="row" style="gap:8px;margin-top:12px"><button class="btn primary" id="lg-ok">导入</button><button class="btn" id="lg-no">不导入</button></div></div>`;
    document.body.appendChild(box);
    $("#lg-no").onclick = async () => { try { await api("legacy_skip"); } catch (e) { /* 下次再问 */ } box.remove(); resolve(); };
    $("#lg-ok").onclick = async (e) => {
      const i = +(box.querySelector("input[name=lg]:checked")?.value || 0);
      e.currentTarget.disabled = true;
      try {
        const r = await api("legacy_import", { path: rows[i].path });
        if (r.error) throw new Error(r.error);
        box.querySelector(".gate-card").innerHTML = `<h2>已导入</h2><p>AT 正在重新打开…</p>`;
      } catch (err) { $("#lg-err").textContent = err.message; $("#lg-err").hidden = false; e.currentTarget.disabled = false; }
    };
  });
}

(async function init() {
  omniInit();
  connect();
  initRuntimeMonitor();
  $("#legal-link").onclick = (e) => { e.preventDefault(); showDisclaimer(); };
  await refreshStatus();
  if (state.status && !state.status.settings.agreed) await agreeGate();
  route();
  legacyCheck();
  setInterval(refreshStatus, 30000);
})();

// 雷达信号「记下」：没认准的信号起个名字，下次认到直接显示（2026-10-27）
document.addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-sig]");
  if (!b) return;
  const v = b.dataset.sig;
  const inp = document.querySelector(`input.sig-name[data-v="${v}"]`);
  const name = (inp?.value || "").trim();
  if (!name) { toast("需填写名字"); return; }
  try { await api("sig_name", { value: Number(v), name }); toast(`已记下：${money(v)} = ${name}`); }
  catch (err) { toast(err.message); }
});
