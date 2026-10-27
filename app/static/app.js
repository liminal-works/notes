"use strict";

const $view = document.getElementById("view");
const $file = document.getElementById("file");
let me = { can_upload: false };

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
  const key = window.prompt("Enter the upload key. It will be saved on this device.");
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

async function upload(file, sheetHint, statusEl, folderId) {
  statusEl.innerHTML = `<div class="busy"><div class="spin"></div>Shrinking photo…</div>`;
  const photo = await shrink(file);
  for (;;) {
    const fd = new FormData();
    fd.append("photo", photo, "photo.jpg");
    if (sheetHint) fd.append("sheet", sheetHint);
    if (folderId) fd.append("folder", folderId);
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
      statusEl.innerHTML = `<div class="notice err">Upload failed. Check the connection and try again. The photo has been kept.
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

async function scanFlow(sheetHint, statusEl, folderId) {
  if (!(await ensureKey())) return null;
  const file = await pickPhoto();
  if (!file) return null;
  return upload(file, sheetHint, statusEl, folderId);
}

// ---------- folders ----------
const jsonOpts = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

async function newFolder() {
  if (!(await ensureKey())) return null;
  const name = window.prompt("Folder name:");
  if (!name || !name.trim()) return null;
  try {
    const { folder } = await api("/api/folders", jsonOpts("POST", { name }));
    toast(`Folder “${folder.name}” created`);
    return folder;
  } catch (e) { toast(e.message); return null; }
}

const FOLDER_ICON = `<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path fill="currentColor" d="M3 6.5A2.5 2.5 0 0 1 5.5 4h3.6c.6 0 1.2.24 1.6.66L12.2 6.2h6.3A2.5 2.5 0 0 1 21 8.7v8.8a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/></svg>`;

// ---------- note browser (home page and folder pages) ----------
function cardHtml(s, { selecting, picked, folderName }) {
  const v = encodeURIComponent(s.uploaded || "");
  const th = (side) => s.sides[side]
    ? `<img loading="lazy" alt="" src="/img/${s.id}/${side}.thumb.jpg?v=${v}">`
    : `<div class="blank"></div>`;
  const where = folderName ? ` · <span class="tag">${esc(folderName)}</span>` : "";
  return `<a class="card${picked.has(s.id) ? " picked" : ""}" href="/s/${s.id}" data-id="${s.id}">
    ${selecting ? `<input class="pick" type="checkbox" ${picked.has(s.id) ? "checked" : ""} tabindex="-1">` : ""}
    <div class="thumbs">${th("A")}${th("B")}</div>
    <div class="info"><div class="t">${esc(s.title) || "Untitled"}</div>
    <div class="m">${when(s.uploaded)}${where}</div></div></a>`;
}

async function browseView(folderId) {
  $view.innerHTML = `<div class="busy"><div class="spin"></div>Loading…</div>`;
  let sheets = [], folders = [];
  try { ({ sheets, folders } = await api("/api/sheets")); }
  catch (e) { $view.innerHTML = `<div class="notice err">${esc(e.message)}</div>`; return; }

  let folder = folderId ? folders.find((f) => f.id === folderId) : null;
  if (folderId && !folder) {
    $view.innerHTML = `<div class="empty">Folder not found. <a href="/">All notes</a></div>`;
    return;
  }

  $view.innerHTML = `
    ${folder ? `
      <a class="crumb" href="/">← All notes</a>
      <div class="row folder-head">
        <input class="title-input" id="fname" value="${esc(folder.name)}" ${me.can_upload ? "" : "disabled"} aria-label="Folder name">
        ${me.can_upload ? `<button class="btn danger" id="fdel">Delete folder</button>` : ""}
      </div>` : ""}
    <div class="toolbar">
      <input type="search" id="q" placeholder="${folder ? "Search this folder" : "Search all notes"}" autocomplete="off">
      <button class="btn" id="selbtn">Select</button>
      ${folder ? "" : `<button class="btn" id="newf">New folder</button>`}
      <button class="btn primary" id="scan">Scan a sheet</button>
    </div>
    <div class="selbar" id="selbar" hidden>
      <span id="selcount" class="sub">0 selected</span><span class="spacer"></span>
      <select class="btn" id="selmove" aria-label="Move selected notes"></select>
      <a class="btn" id="selopen" target="_blank">Open PDF</a>
      <a class="btn primary" id="seldl">Download PDF</a>
    </div>
    <div id="scanstatus"></div>
    <div id="list"></div>`;

  let selecting = false;
  const picked = new Set();
  const nameOf = (fid) => folders.find((f) => f.id === fid)?.name;

  const draw = () => {
    const q = document.getElementById("q").value.trim().toLowerCase();
    const match = (s) => !q || s.id.toLowerCase().includes(q) || (s.title || "").toLowerCase().includes(q)
      || (!folder && (nameOf(s.folder) || "").toLowerCase().includes(q));
    // Home: unfiled notes, plus folder tiles. Searching from home looks everywhere.
    const pool = folder ? sheets.filter((s) => s.folder === folder.id)
      : q ? sheets : sheets.filter((s) => !s.folder || !nameOf(s.folder));
    const shown = pool.filter(match);
    const opts = { selecting, picked };

    let html = "";
    if (!folder && !q && folders.length) {
      html += `<h2 class="section">Folders</h2><div class="folders">${folders.map((f) => {
        const n = sheets.filter((s) => s.folder === f.id).length;
        return `<a class="folder" href="/f/${f.id}">${FOLDER_ICON}<span class="fn">${esc(f.name)}</span><span class="fc">${n}</span></a>`;
      }).join("")}</div>`;
    }
    if (!folder && !q && folders.length) html += `<h2 class="section">Not in a folder</h2>`;

    if (!sheets.length && !folder) {
      html += `<div class="empty">No notes yet.<br>Print sheets, then scan a sheet's QR code to upload it.</div>`;
    } else if (!shown.length) {
      html += `<div class="empty">${q ? `Nothing matches “${esc(q)}”.` : folder ? "This folder is empty. Move notes here with Select on the main page, or scan a sheet from this folder." : "All notes are in folders."}</div>`;
    } else {
      html += `<div class="grid">${shown.map((s) => cardHtml(s, { ...opts, folderName: !folder && q ? nameOf(s.folder) : null })).join("")}</div>`;
    }
    document.getElementById("list").innerHTML = html;
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
    const mv = document.getElementById("selmove");
    mv.disabled = !picked.size;
    mv.innerHTML = `<option value="" disabled selected>Move to…</option>`
      + folders.filter((f) => f.id !== folder?.id).map((f) => `<option value="${f.id}">${esc(f.name)}</option>`).join("")
      + `<option value="__new">New folder…</option>`
      + (folder ? `<option value="__none">Out of this folder</option>` : "");
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
  document.getElementById("selmove").onchange = async (e) => {
    let target = e.target.value;
    if (!(await ensureKey())) { syncSel(); return; }
    if (target === "__new") {
      const f = await newFolder();
      if (!f) { syncSel(); return; }
      folders.push(f);
      target = f.id;
    }
    const fid = target === "__none" ? null : target;
    try {
      const done = await Promise.all([...picked].map((sid) => api(`/api/sheets/${sid}`, jsonOpts("PATCH", { folder: fid }))));
      for (const { sheet } of done) {
        const i = sheets.findIndex((s) => s.id === sheet.id);
        if (i >= 0) sheets[i] = sheet;
      }
      toast(`Moved ${done.length} note${done.length === 1 ? "" : "s"}${fid ? ` to “${nameOf(fid)}”` : " out of the folder"}`);
      picked.clear();
    } catch (err) { toast(err.message); }
    syncSel(); draw();
  };
  document.getElementById("scan").onclick = async () => {
    const res = await scanFlow(null, document.getElementById("scanstatus"), folder?.id);
    if (res) location.href = `/s/${res.sheet.id}`;
  };
  const $newf = document.getElementById("newf");
  if ($newf) $newf.onclick = async () => {
    const f = await newFolder();
    if (f) { folders.push(f); folders.sort((a, b) => a.name.localeCompare(b.name)); syncSel(); draw(); }
  };
  if (folder) {
    const $n = document.getElementById("fname");
    $n.onkeydown = (e) => { if (e.key === "Enter") $n.blur(); };
    $n.onchange = async () => {
      try { folder = (await api(`/api/folders/${folder.id}`, jsonOpts("PATCH", { name: $n.value }))).folder; $n.value = folder.name; toast("Folder renamed"); }
      catch (e) { $n.value = folder.name; toast(e.message); }
    };
    const $d = document.getElementById("fdel");
    if ($d) $d.onclick = async () => {
      const n = sheets.filter((s) => s.folder === folder.id).length;
      if (!confirm(`Delete folder “${folder.name}”?${n ? ` The ${n} note${n === 1 ? "" : "s"} in it will not be deleted and will move to the main page.` : ""}`)) return;
      try { await api(`/api/folders/${folder.id}`, { method: "DELETE" }); location.href = "/"; }
      catch (e) { toast(e.message); }
    };
  }
  syncSel();
  draw();
}

// ---------- one sheet ----------
async function sheetView(page) {
  const m = /^(S[0-9A-F]{4,8})(?:-([AB]))?$/i.exec(page);
  if (!m) { $view.innerHTML = `<div class="empty">Invalid sheet link.</div>`; return; }
  const sid = m[1].toUpperCase(), qrSide = m[2] ? m[2].toUpperCase() : null;
  let sheet = null, folders = [];

  const render = () => {
    const v = encodeURIComponent(sheet?.uploaded || "");
    const pageHtml = (side) => {
      const info = sheet?.sides?.[side];
      if (!info) return `<div class="page missing">Side ${side} not scanned yet</div>`;
      return `<figure class="page" style="margin:0">
        <a href="/img/${sid}/${side}.jpg?v=${v}" target="_blank"><img alt="Side ${side}" src="/img/${sid}/${side}.jpg?v=${v}"></a>
        <div class="bar">Side ${side} · ${when(info.updated)}<span class="spacer"></span>
        <a href="/img/${sid}/${side}.flat.jpg?v=${v}" target="_blank">unfiltered</a></div></figure>`;
    };
    const hasPages = sheet && Object.keys(sheet.sides || {}).length;
    const cur = folders.find((f) => f.id === sheet?.folder);
    $view.innerHTML = `
      <a class="crumb" href="${cur ? `/f/${cur.id}` : "/"}">← ${cur ? esc(cur.name) : "All notes"}</a>
      <input class="title-input" id="title" placeholder="Untitled" value="${esc(sheet?.title)}" ${me.can_upload && sheet ? "" : "disabled"} aria-label="Title">
      <p class="sub">${sid}${sheet ? ` · uploaded ${when(sheet.uploaded)}` : " · nothing scanned yet"}</p>
      <button class="btn primary big" id="scan">${qrSide ? `Scan side ${qrSide}` : "Scan this sheet"}</button>
      <div id="scanstatus"></div>
      ${hasPages ? `<div class="row" style="margin-top:12px">
        <select class="btn" id="folder" aria-label="Folder" ${me.can_upload ? "" : "disabled"}>
          <option value="">No folder</option>
          ${folders.map((f) => `<option value="${f.id}" ${f.id === sheet.folder ? "selected" : ""}>${esc(f.name)}</option>`).join("")}
          <option value="__new">New folder…</option>
        </select>
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
      try { sheet = (await api(`/api/sheets/${sid}`, jsonOpts("PATCH", { title: $t.value }))).sheet; toast("Title saved"); }
      catch (e) { toast(e.message); }
    };
    const $f = document.getElementById("folder");
    if ($f) $f.onchange = async () => {
      let fid = $f.value;
      if (fid === "__new") {
        const f = await newFolder();
        if (!f) { render(); return; }
        folders.push(f); fid = f.id;
      }
      try {
        sheet = (await api(`/api/sheets/${sid}`, jsonOpts("PATCH", { folder: fid || null }))).sheet;
        toast(fid ? `Moved to “${folders.find((x) => x.id === fid).name}”` : "Removed from folder");
      } catch (e) { toast(e.message); }
      render();
    };
    const $del = document.getElementById("del");
    if ($del) $del.onclick = async () => {
      if (!confirm("Delete this note and all of its scans? This cannot be undone.")) return;
      try { await api(`/api/sheets/${sid}`, { method: "DELETE" }); location.href = cur ? `/f/${cur.id}` : "/"; }
      catch (e) { toast(e.message); }
    };
  };

  try {
    const [s, f] = await Promise.all([api(`/api/sheets/${sid}`), api("/api/folders")]);
    sheet = s.sheet; folders = f.folders;
  } catch {}
  render();
}

// ---------- print ----------
function printView() {
  $view.innerHTML = `
    <h1>Print sheets</h1>
    <p class="sub">Each sheet is assigned a unique random ID.</p>
    <div class="form">
      <label for="count">Number of sheets</label>
      <input id="count" type="number" min="1" max="500" value="50">
      <button class="btn primary big" id="go">Generate PDF</button>
    </div>
    <h2 class="section">Printing guidelines</h2>
    <ul class="tips">
      <li>Print at <b>100% (actual size)</b>, landscape, single-sided.</li>
      <li>Load the paper so the template prints on the blank side.</li>
      <li>Fold along the dotted line. Each half is a separate page with its own QR code.</li>
      <li>Sheets with legacy numeric IDs (S0001–S0050) remain supported.</li>
    </ul>`;
  document.getElementById("go").onclick = () => {
    const c = +document.getElementById("count").value;
    if (!(c >= 1 && c <= 500)) { toast("Enter a number from 1 to 500"); return; }
    window.open(`/template.pdf?count=${c}`, "_blank");
  };
}

// ---------- router ----------
(async function main() {
  try { me = await api("/api/me"); } catch {}
  const path = location.pathname;
  const nav = path.startsWith("/print") ? "print" : path === "/" ? "list" : "";
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === nav));
  if (path === "/") return browseView(null);
  if (path.startsWith("/print")) return printView();
  const f = /^\/f\/([^/]+)$/.exec(path);
  if (f) return browseView(decodeURIComponent(f[1]));
  const s = /^\/s\/([^/]+)$/.exec(path);
  if (s) return sheetView(decodeURIComponent(s[1]));
  $view.innerHTML = `<div class="empty">Page not found. <a href="/">All notes</a></div>`;
})();
