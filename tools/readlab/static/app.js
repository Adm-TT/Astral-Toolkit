// 读屏开发工作台界面：选样本、画区域（存比例）、点图试识别、批量查。只跟本机服务说话。
const $ = (id) => document.getElementById(id);
const S = {
  features: [], samples: [], regions: { version: 0, regions: {} },
  feature: null, sample: null, key: null, dirty: false,
  shapes: [], drag: null, job: null,
};
const INK = { read: "#40a0ff", exclude: "#ffa000", hit: "#28c85a", miss: "#e63c3c" };
const NAMED = [["16:9", 16 / 9], ["16:10", 16 / 10], ["21:9", 64 / 27]];

async function api(method, path, body) {
  const r = await fetch(path, {
    method, headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `出错了（${r.status}）`);
  return data;
}
const say = (t) => { $("status").textContent = t; };

// ---------------------------------------------------------------- 屏幕比例（和 core/screen_regions.aspect_of 一样）
function gcd(a, b) { return b ? gcd(b, a % b) : a; }
function aspectOf(w, h) {
  for (const [name, r] of NAMED) if (Math.abs(w / h - r) < 0.03) return name;
  const g = gcd(w, h) || 1;
  return `${w / g}:${h / g}`;
}
function ratioOf(a) {
  const n = NAMED.find(([name]) => name === a);
  if (n) return n[1];
  const [w, h] = a.split(":").map(Number);
  return w && h ? w / h : 16 / 9;
}
const curAspect = () => (S.sample ? aspectOf(S.sample.w, S.sample.h) : "16:9");

// 当前截图比例下这个区域用哪一条：同比例的那条；没有就借最接近比例的（借来的只显示虚线，改了才新建）
function entryFor(key) {
  const list = S.regions.regions[key] || [];
  const a = curAspect();
  const own = list.find((e) => e.aspect === a);
  if (own) return { e: own, borrowed: false };
  if (!list.length) return { e: null, borrowed: false };
  const want = Math.log(ratioOf(a));
  const near = [...list].sort((x, y) => Math.abs(Math.log(ratioOf(x.aspect)) - want) - Math.abs(Math.log(ratioOf(y.aspect)) - want))[0];
  return { e: near, borrowed: true };
}
function ownEntry(key) {
  const { e, borrowed } = entryFor(key);
  if (e && !borrowed) return e;
  const made = { aspect: curAspect(), box: e ? [...e.box] : [0.4, 0.4, 0.6, 0.6], kind: e ? e.kind : "read", note: e ? e.note : "" };
  (S.regions.regions[key] ||= []).push(made);
  return made;
}

// ---------------------------------------------------------------- 画
function canvasSize() {
  const img = $("shot"), cv = $("overlay");
  cv.width = img.clientWidth; cv.height = img.clientHeight;
  return [cv.width, cv.height];
}
function draw() {
  const cv = $("overlay"), ctx = cv.getContext("2d");
  const [W, H] = canvasSize();
  ctx.clearRect(0, 0, W, H);
  if (!S.sample || !S.feature) return;
  ctx.font = "13px 'Microsoft YaHei UI', sans-serif";
  for (const key of keysOfFeature()) {
    const { e, borrowed } = entryFor(key);
    if (!e) continue;
    const [l, t, r, b] = e.box;
    ctx.lineWidth = key === S.key ? 3 : 1.5;
    ctx.strokeStyle = INK[e.kind] || INK.read;
    ctx.setLineDash(e.kind === "exclude" || borrowed ? [8, 5] : []);
    ctx.strokeRect(l * W, t * H, (r - l) * W, (b - t) * H);
    ctx.setLineDash([]);
    ctx.fillStyle = ctx.strokeStyle;
    ctx.fillText(key + (borrowed ? `（借用 ${e.aspect}）` : ""), l * W + 4, t * H + 16);
    if (key === S.key) for (const [hx, hy] of corners(e.box, W, H)) ctx.fillRect(hx - 5, hy - 5, 10, 10);
  }
  const k = W / S.sample.w;
  for (const s of S.shapes) {
    const [l, t, r, b] = s.box;
    ctx.lineWidth = 2; ctx.strokeStyle = INK[s.color] || "#fff";
    ctx.strokeRect(l * k, t * k, (r - l) * k, (b - t) * k);
    ctx.fillStyle = ctx.strokeStyle;
    ctx.fillText(s.label, l * k + 4, b * k - 4);
  }
}
const corners = ([l, t, r, b], W, H) => [[l * W, t * H], [r * W, t * H], [l * W, b * H], [r * W, b * H]];
const keysOfFeature = () => {
  const f = S.features.find((x) => x.key === S.feature);
  const extra = Object.keys(S.regions.regions).filter((k) => k.startsWith(S.feature + "."));
  return [...new Set([...(f ? f.regions : []), ...extra])];
};

// ---------------------------------------------------------------- 拖框：新画 / 挪 / 改大小
function pos(ev) {
  const r = $("overlay").getBoundingClientRect();
  return [(ev.clientX - r.left) / r.width, (ev.clientY - r.top) / r.height];
}
$("overlay").addEventListener("mousedown", (ev) => {
  if (!S.sample) return;
  const [x, y] = pos(ev);
  if ($("trymode").checked) return tryAt(x, y);
  if (!S.key) return say("先在右边选一个区域");
  const { e } = entryFor(S.key);
  const [W, H] = canvasSize();
  if (e) {
    const hit = corners(e.box, W, H).findIndex(([hx, hy]) => Math.abs(hx - x * W) < 8 && Math.abs(hy - y * H) < 8);
    if (hit >= 0) { S.drag = { mode: "corner", i: hit }; return; }
    const [l, t, r, b] = e.box;
    if (x > l && x < r && y > t && y < b) { S.drag = { mode: "move", x, y, box: [...e.box] }; return; }
  }
  S.drag = { mode: "new", x, y };
});
window.addEventListener("mousemove", (ev) => {
  if (!S.drag) return;
  const [x, y] = pos(ev).map((v) => Math.min(1, Math.max(0, v)));
  const e = ownEntry(S.key);
  const d = S.drag;
  if (d.mode === "new") e.box = [Math.min(d.x, x), Math.min(d.y, y), Math.max(d.x, x), Math.max(d.y, y)];
  else if (d.mode === "move") {
    const [l, t, r, b] = d.box, dx = Math.min(1 - r, Math.max(-l, x - d.x)), dy = Math.min(1 - b, Math.max(-t, y - d.y));
    e.box = [l + dx, t + dy, r + dx, b + dy];
  } else {
    const box = [...e.box];
    if (d.i === 0 || d.i === 2) box[0] = x; else box[2] = x;
    if (d.i === 0 || d.i === 1) box[1] = y; else box[3] = y;
    e.box = [Math.min(box[0], box[2]), Math.min(box[1], box[3]), Math.max(box[0], box[2]), Math.max(box[1], box[3])];
  }
  markDirty(); draw();
});
window.addEventListener("mouseup", () => {
  if (!S.drag) return;
  S.drag = null;
  const e = entryFor(S.key).e;
  if (e && (e.box[2] - e.box[0] < 0.002 || e.box[3] - e.box[1] < 0.002)) say("框太小了，没画上");
  e && (e.box = e.box.map((v) => Math.round(v * 10000) / 10000));
  renderRegions(); draw();
});
function markDirty() { S.dirty = true; $("save").textContent = "存区域（有改动）"; }

// ---------------------------------------------------------------- 右边：区域列表
function renderRegions() {
  $("aspect").textContent = S.sample ? `这张是 ${curAspect()}` : "";
  const box = $("regions");
  box.innerHTML = "";
  for (const key of keysOfFeature()) {
    const { e, borrowed } = entryFor(key);
    const div = document.createElement("div");
    div.className = "region" + (e && e.kind === "exclude" ? " exclude" : "") + (key === S.key ? " on" : "");
    div.innerHTML = `<b></b><span class="muted"></span>`;
    div.querySelector("b").textContent = key;
    div.querySelector(".muted").textContent = !e ? "还没画" : borrowed ? `这个比例还没画，借用 ${e.aspect}` : e.box.map((v) => v.toFixed(3)).join(", ");
    div.onclick = () => { S.key = key; renderRegions(); draw(); };
    box.appendChild(div);
  }
  const { e } = S.key ? entryFor(S.key) : { e: null };
  $("kind").value = e ? e.kind : "read";
  $("note").value = e ? e.note || "" : "";
  $("version").textContent = `区域文件第 ${S.regions.version} 版`;
}
$("kind").onchange = () => { if (!S.key) return; ownEntry(S.key).kind = $("kind").value; markDirty(); renderRegions(); draw(); };
$("note").onchange = () => { if (!S.key) return; ownEntry(S.key).note = $("note").value; markDirty(); };
$("add").onclick = () => {
  const name = prompt(`新区域叫什么（会存成 ${S.feature}.名字，用英文小写和下划线）`);
  if (!name) return;
  if (!/^[a-z0-9_]+$/.test(name)) return say("名字只能用英文小写、数字、下划线");
  S.key = `${S.feature}.${name}`;
  S.regions.regions[S.key] ||= [];
  renderRegions(); draw(); say("在图上拖一个框");
};
$("del").onclick = () => {
  if (!S.key) return;
  const list = S.regions.regions[S.key] || [];
  const i = list.findIndex((e) => e.aspect === curAspect());
  if (i < 0) return say(`这个区域在 ${curAspect()} 下本来就没画`);
  list.splice(i, 1);
  if (!list.length) delete S.regions.regions[S.key];
  markDirty(); renderRegions(); draw();
};
$("save").onclick = async () => {
  try {
    const r = await api("PUT", "/api/regions", { version: S.regions.version, regions: S.regions.regions });
    S.regions.version = r.version; S.dirty = false;
    $("save").textContent = "存区域"; renderRegions(); say(`存好了，第 ${r.version} 版`);
  } catch (err) { say(err.message); }
};
window.addEventListener("beforeunload", (ev) => { if (S.dirty) ev.preventDefault(); });

// ---------------------------------------------------------------- 试一下
async function tryAt(fx, fy) {
  const point = [Math.round(fx * S.sample.w), Math.round(fy * S.sample.h)];
  if (!point.every(Number.isFinite)) return say("图还没显示出来，等一下再点");
  say("在认……");
  try {
    const r = await api("POST", "/api/try", { feature: S.feature, id: S.sample.id, point });
    S.shapes = r.shapes;
    $("result").textContent = `点在 (${point})｜${r.ms} 毫秒\n` + r.lines.join("\n") + (r.error ? `\n出错：${r.error}` : "");
    say("");
  } catch (err) { say(err.message); }
  draw();
}

// ---------------------------------------------------------------- 批量查
$("batch").onclick = async () => {
  try {
    const ids = visible().map((s) => s.id);
    if (!ids.length) return say("左边列表是空的");
    const { job } = await api("POST", "/api/batch", { feature: S.feature, ids });
    S.job = job; $("cancel").disabled = false; $("batch").disabled = true;
    poll();
  } catch (err) { say(err.message); }
};
$("cancel").onclick = () => S.job && api("DELETE", `/api/batch/${S.job}`).catch((e) => say(e.message));
async function poll() {
  const st = await api("GET", `/api/batch/${S.job}`);
  $("progress").max = st.total || 1; $("progress").value = st.done;
  $("batchinfo").textContent = `${st.done} / ${st.total}，出错 ${st.errors}` + (st.cancelled ? "（取消了）" : "");
  if (!st.finished) return setTimeout(poll, 500);
  $("cancel").disabled = true; $("batch").disabled = false;
  if (st.report) {
    const name = st.report.split(/[\\/]/).pop();
    $("batchinfo").innerHTML = "";
    const a = document.createElement("a");
    a.href = `/reports/${encodeURIComponent(name)}`; a.target = "_blank"; a.textContent = `打开报告 ${name}`;
    $("batchinfo").append(`${st.done} / ${st.total}，出错 ${st.errors}${st.cancelled ? "（取消了）" : ""}　`, a);
  }
}

// ---------------------------------------------------------------- 左边：样本
function visible() {
  const q = $("filter").value.trim().toLowerCase();
  return S.samples.filter((s) => !q || s.rel.toLowerCase().includes(q));
}
function renderSamples() {
  const box = $("samples");
  box.innerHTML = "";
  let root = null;
  for (const s of visible()) {
    if (s.root !== root) {
      root = s.root;
      const g = document.createElement("div");
      g.className = "group"; g.textContent = root; box.appendChild(g);
    }
    const d = document.createElement("div");
    d.className = "sample" + (S.sample && S.sample.id === s.id ? " on" : "");
    d.textContent = `${s.rel}（${s.w}×${s.h}）`;
    d.onclick = () => pick(s);
    box.appendChild(d);
  }
}
function pick(s) {
  S.sample = s; S.shapes = []; $("result").textContent = "";
  $("shot").src = `/api/image?id=${encodeURIComponent(s.id)}`;
  renderSamples(); renderRegions();
}
$("shot").onload = draw;
window.addEventListener("resize", draw);
$("filter").oninput = renderSamples;
$("feature").onchange = () => { S.feature = $("feature").value; S.key = null; S.shapes = []; renderRegions(); draw(); };

(async function init() {
  try {
    [S.features, S.samples, S.regions] = await Promise.all([api("GET", "/api/features"), api("GET", "/api/samples"), api("GET", "/api/regions")]);
  } catch (err) { return say(err.message); }
  for (const f of S.features) $("feature").add(new Option(f.name, f.key));
  S.feature = S.features[0] && S.features[0].key;
  renderSamples(); renderRegions();
  say(`${S.samples.length} 张样本`);
})();
