"use strict";

const $view = document.getElementById("view");
const $file = document.getElementById("file");
let me = { can_upload: false, next_template_start: 1 };

// ---------- helpers ----------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 2600);
}

function when(iso) {
  if (!iso) return "";
  const d = new Date(iso), now = new Date();
  const mins = Math.round((now - d) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const sameDay = d.toDateString() === now.toDateString();
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (sameDay) return `today ${time}`;
  const yest = new Date(now); yest.setDate(now.getDate() - 1);
  if (d.toDateString() === yest.toDateString()) return `yesterday ${time}`;
  return d.toLocaleDateString([], { month: "short", day: "numeric", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" });
}

async function api(path, opts = {}) {
  const r = await fetch(path, { credentials: "same-origin", ...opts });
  let body = {};
  try { body = await r.json(); } catch {}
  if (!r.ok) throw Object.assign(new Error(body.error || `Request failed (${r.status})`), { status: r.status });
  return body;
}

async function ensureKey() {
  if (me.can_upload) return true;
  const key = window.prompt("Enter your upload key (you only need to do this once on this device):");
  if (!key) return false;
  try {
    await api("/api/key", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key }) });
    me.can_upload = true;
    toast("Key saved on this device");
    return true;
  } catch (e) {
    toast(e.message);
    return false;
  }
}

function pickPhoto() {
  return new Promise((resolve) => {
    $file.value = "";
    $file.onchange = () => resolve($file.files[0] || null);
    $file.click();
  });
}

// Phone photos are 3-6 MB. Shrink to SHRINK_MAX px on the long side before upload
// (~150-400 KB); the corner markers and QR still read fine at this size.
const SHRINK_MAX = 1600;
const SHRINK_QUALITY = 0.8;

async function shrink(file) {
  try {
    const url = URL.createObjectURL(file);
    const img = await new Promise((ok, bad) => {
      const i = new Image();
      i.onload = () => ok(i);
      i.onerror = bad;
      i.src = url;
    });
    URL.revokeObjectURL(url);
    const k = Math.min(1, SHRINK_MAX / Math.max(img.naturalWidth, img.naturalHeight));
    const c = document.createElement("canvas");
    c.width = Math.round(img.naturalWidth * k);
    c.height = Math.round(img.naturalHeight * k);
    c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    const blob = await new Promise((ok) => c.toBlob(ok, "image/jpeg", SHRINK_QUALITY));
    return blob && blob.size < file.size ? blob : file;
  } catch {
    return file; // couldn't decode in the browser (e.g. HEIC on desktop); send as-is
  }
}

const kb = (n) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

async function upload(file, sheetHint, statusEl) {
  statusEl.innerHTML = `<div class="busy"><div class="spin"></div>Shrinking photo…</div>`;
  const photo = await shrink(file);
  for (;;) {
    const fd = new FormData();
    fd.append("photo", photo, "photo.jpg");
    if (sheetHint) fd.append("sheet", sheetHint);
    statusEl.innerHTML = `<div class="busy"><div class="spin"></div>Uploading ${kb(photo.size)} and straightening…</div>`;
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 90000);
    try {
      const res = await api("/api/upload", { method: "POST", body: fd, signal: ctl.signal });
      statusEl.innerHTML = res.warnings.length
        ? res.warnings.map((w) => `<div class="notice">${esc(w)}</div>`).join("")
        : "";
      toast(`Saved side ${res.saved_sides.join(" + ")}`);
      return res;
    } catch (e) {
      if (e.status === 401) me.can_upload = false;
      if (e.status) { // the server answered with an error; retrying won't help
        statusEl.innerHTML = `<div class="notice err">${esc(e.message)}</div>`;
        return null;
      }
      // no answer at all: bad signal or timeout. Keep the photo and offer a retry.
      statusEl.innerHTML = `<div class="notice err">Upload didn't go through (weak signal?). The photo is kept.
        <div class="row" style="margin-top:8px"><button class="btn primary" data-a="retry">Try again</button>
        <button class="btn" data-a="cancel">Cancel</button></div></div>`;
      const again = await new Promise((ok) => {
        statusEl.querySelector('[data-a="retry"]').onclick = () => ok(true);
        statusEl.querySelector('[data-a="cancel"]').onclick = () => ok(false);
      });
      if (!again) { statusEl.innerHTML = ""; return null; }
    } finally {
      clearTimeout(timer);
    }
  }
}

async function scanFlow(sheetHint, statusEl) {
  if (!(await ensureKey())) return null;
  const file = await pickPhoto();
  if (!file) return null;
  return upload(file, sheetHint, statusEl);
}

// ---------- views ----------
async function listView() {
  $view.innerHTML = `
    <div class="toolbar">
      <input type="search" id="q" placeholder="Search titles or sheet numbers" autocomplete="off">
      <button class="btn" id="selbtn">Select</button>
      <button class="btn primary" id="scan">Scan a sheet</button>
    </div>
    <div class="row" id="selbar" hidden style="margin-bottom:12px">
      <span id="selcount" class="sub" style="margin:0">0 selected</span><span class="spacer"></span>
      <a class="btn" id="selopen" target="_blank">Open PDF</a>
      <a class="btn primary" id="seldl">Download PDF</a>
    </div>
    <div id="scanstatus"></div>
    <div id="list"><div class="busy"><div class="spin"></div>Loading…</div></div>`;

  let sheets = [];
  let selecting = false;
  const picked = new Set();

  const draw = () => {
    const q = document.getElementById("q").value.trim().toLowerCase();
    const shown = sheets.filter((s) => !q || s.id.toLowerCase().includes(q) || (s.title || "").toLowerCase().includes(q));
    const $list = document.getElementById("list");
    if (!sheets.length) {
      $list.innerHTML = `<div class="empty">No notes yet.<br>Print some sheets, write on one, then scan its QR code with your phone camera.</div>`;
      return;
    }
    if (!shown.length) { $list.innerHTML = `<div class="empty">Nothing matches “${esc(q)}”.</div>`; return; }
    $list.innerHTML = `<div class="grid">${shown.map((s) => {
      const v = encodeURIComponent(s.updated || "");
      const th = (side) => s.sides[side]
        ? `<img loading="lazy" alt="" src="/img/${s.id}/${side}.thumb.jpg?v=${v}">`
        : `<div class="blank"></div>`;
      return `<a class="card" href="/s/${s.id}" data-id="${s.id}">
        ${selecting ? `<input class="pick" type="checkbox" ${picked.has(s.id) ? "checked" : ""} tabindex="-1">` : ""}
        <div class="thumbs">${th("A")}${th("B")}</div>
        <div class="info"><div class="t">${esc(s.title) || "Untitled"}</div>
        <div class="m">${s.id} · ${when(s.updated)}</div></div></a>`;
    }).join("")}</div>`;
  };

  const syncSel = () => {
    const ids = [...picked].join(",");
    document.getElementById("selbar").hidden = !selecting;
    document.getElementById("selcount").textContent = `${picked.size} selected`;
    for (const id of ["selopen", "seldl"]) {
      const a = document.getElementById(id);
      a.classList.toggle("disabled", !picked.size);
      a.href = picked.size ? `/pdf?ids=${ids}${id === "seldl" ? "&download=1" : ""}` : "#";
    }
  };

  document.getElementById("q").oninput = draw;
  document.getElementById("selbtn").onclick = (e) => {
    selecting = !selecting;
    picked.clear();
    e.target.textContent = selecting ? "Done" : "Select";
    syncSel(); draw();
  };
  document.getElementById("list").onclick = (e) => {
    if (!selecting) return;
    const card = e.target.closest(".card");
    if (!card) return;
    e.preventDefault();
    const id = card.dataset.id;
    picked.has(id) ? picked.delete(id) : picked.add(id);
    syncSel(); draw();
  };
  document.getElementById("scan").onclick = async () => {
    const res = await scanFlow(null, document.getElementById("scanstatus"));
    if (res) location.href = `/s/${res.sheet.id}`;
  };

  try {
    sheets = (await api("/api/sheets")).sheets;
    draw();
  } catch (e) {
    document.getElementById("list").innerHTML = `<div class="notice err">${esc(e.message)}</div>`;
  }
}

async function sheetView(page) {
  const m = /^(S\d{4,6})(?:-([AB]))?$/.exec(page);
  if (!m) { $view.innerHTML = `<div class="empty">That isn't a sheet link.</div>`; return; }
  const sid = m[1], qrSide = m[2] || null;
  let sheet = null;

  const render = () => {
    const v = encodeURIComponent(sheet?.updated || "");
    const pageHtml = (side) => {
      const info = sheet?.sides?.[side];
      if (!info) return `<div class="page missing">Side ${side} not scanned yet</div>`;
      return `<figure class="page" style="margin:0">
        <a href="/img/${sid}/${side}.jpg?v=${v}" target="_blank"><img alt="Side ${side}" src="/img/${sid}/${side}.jpg?v=${v}"></a>
        <div class="bar">Side ${side} · ${when(info.updated)}<span class="spacer"></span>
        <a href="/img/${sid}/${side}.flat.jpg?v=${v}" target="_blank">unfiltered</a></div></figure>`;
    };
    const hasPages = sheet && Object.keys(sheet.sides || {}).length;
    $view.innerHTML = `
      <input class="title-input" id="title" placeholder="Untitled" value="${esc(sheet?.title)}" ${me.can_upload && sheet ? "" : "disabled"} aria-label="Title">
      <p class="sub">${sid}${sheet ? ` · updated ${when(sheet.updated)}` : " · nothing scanned yet"}</p>
      <button class="btn primary big" id="scan">${qrSide ? `Scan side ${qrSide}` : "Scan this sheet"}</button>
      <div id="scanstatus"></div>
      ${hasPages ? `<div class="row" style="margin-top:12px">
        <a class="btn" href="/pdf/${sid}.pdf?v=${v}" target="_blank">Open PDF</a>
        <a class="btn" href="/pdf/${sid}.pdf?download=1&v=${v}">Download PDF</a>
        <span class="spacer"></span>
        ${me.can_upload ? `<button class="btn danger" id="del">Delete</button>` : ""}
      </div>` : ""}
      <div class="pages">${pageHtml("A")}${pageHtml("B")}</div>`;

    document.getElementById("scan").onclick = async () => {
      const res = await scanFlow(page, document.getElementById("scanstatus"));
      if (!res) return;
      if (res.sheet.id !== sid) { location.href = `/s/${res.sheet.id}`; return; }
      const keep = document.getElementById("scanstatus").innerHTML;
      sheet = res.sheet; render();
      document.getElementById("scanstatus").innerHTML = keep;
    };
    const $t = document.getElementById("title");
    $t.onkeydown = (e) => { if (e.key === "Enter") $t.blur(); };
    $t.onchange = async () => {
      try { sheet = (await api(`/api/sheets/${sid}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: $t.value }) })).sheet; toast("Title saved"); }
      catch (e) { toast(e.message); }
    };
    const $del = document.getElementById("del");
    if ($del) $del.onclick = async () => {
      if (!confirm(`Delete ${sid} and its scans? This can't be undone.`)) return;
      try { await api(`/api/sheets/${sid}`, { method: "DELETE" }); location.href = "/"; }
      catch (e) { toast(e.message); }
    };
  };

  try { sheet = (await api(`/api/sheets/${sid}`)).sheet; } catch {}
  render();
}

function printView() {
  $view.innerHTML = `
    <h1>Print sheets</h1>
    <p class="sub">Each page is one sheet with a unique number. Print onto the blank back of your scrap paper.</p>
    <div class="form">
      <label for="start">First sheet number</label>
      <input id="start" type="number" min="1" value="${me.next_template_start}">
      <label for="count">How many sheets</label>
      <input id="count" type="number" min="1" max="500" value="50">
      <button class="btn primary big" id="go">Make PDF</button>
    </div>
    <ul class="tips">
      <li>Print at <b>Actual size / 100%</b>, landscape, one-sided. “Fit to page” shrinks the markers a little; it still works, but actual size is best.</li>
      <li>Do a test page first to see which way up the scrap paper has to go in the tray so the template lands on the blank side.</li>
      <li>Fold on the dotted line. Each half is its own page with its own QR code.</li>
      <li>The next number is suggested automatically so you don't print duplicate sheet numbers.</li>
    </ul>`;
  document.getElementById("go").onclick = () => {
    const s = +document.getElementById("start").value, c = +document.getElementById("count").value;
    if (!(s >= 1 && c >= 1 && c <= 500)) { toast("Check the numbers"); return; }
    window.open(`/template.pdf?start=${s}&count=${c}`, "_blank");
    me.next_template_start = s + c;
    document.getElementById("start").value = s + c;
  };
}

// ---------- router ----------
(async function main() {
  try { me = await api("/api/me"); } catch {}
  const path = location.pathname;
  const nav = path.startsWith("/print") ? "print" : path === "/" ? "list" : "";
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === nav));
  if (path === "/") return listView();
  if (path.startsWith("/print")) return printView();
  const s = /^\/s\/([^/]+)$/.exec(path);
  if (s) return sheetView(decodeURIComponent(s[1]));
  $view.innerHTML = `<div class="empty">Page not found. <a href="/">All notes</a></div>`;
})();
