"use strict";

const view = document.getElementById("view");
const state = { catalog: [], libraries: null };

// ---------- helpers ----------

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));

async function api(method, path, body, raw = false) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) {
    opts.body = body;
  } else if (typeof body === "string") {
    opts.body = body;
    opts.headers["Content-Type"] = "text/plain";
  } else if (body !== undefined) {
    opts.body = JSON.stringify(body);
    opts.headers["Content-Type"] = "application/json";
  }
  const resp = await fetch(`/api${path}`, opts);
  if (raw) return resp;
  const data = resp.headers.get("content-type")?.includes("json") ? await resp.json() : await resp.text();
  if (!resp.ok) {
    let msg = data?.detail ?? data;
    if (Array.isArray(msg)) msg = msg.map((e) => `${(e.loc || []).slice(1).join(".")}: ${e.msg}`).join("; ");
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

function toast(message, error = false) {
  const el = document.createElement("div");
  el.className = `toast${error ? " error" : ""}`;
  el.textContent = message;
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), error ? 8000 : 4000);
}

async function guard(fn) {
  try { return await fn(); } catch (err) { toast(err.message, true); }
}

function when(iso) {
  if (!iso) return "never";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString();
}

const badge = (status) => status ? `<span class="badge ${esc(status)}">${esc(status)}</span>` : "";

async function libraries() {
  if (!state.libraries) state.libraries = await api("GET", "/plex/libraries");
  return state.libraries;
}

async function catalog() {
  if (!state.catalog.length) state.catalog = await api("GET", "/sources");
  return state.catalog;
}

// ---------- router ----------

const routes = [
  [/^#\/collections\/new(?:\?(.*))?$/, (m) => editor(null, new URLSearchParams(m[1] || ""))],
  [/^#\/collections\/(\d+)$/, (m) => editor(Number(m[1]))],
  [/^#\/collections\/(\d+)\/items$/, (m) => collectionItems({ id: Number(m[1]) })],
  [/^#\/plex\/(\d+)(?:\?(.*))?$/, (m) => collectionItems({ ratingKey: m[1], params: new URLSearchParams(m[2] || "") })],
  [/^#\/history$/, history],
  [/^#\/logs$/, logsPage],
  [/^#\/settings$/, settings],
  [/^#\/import$/, importExport],
  [/^#\/movies$/, () => collections("movie")],
  [/^#\/tv$/, () => collections("show")],
  [/^#\/holidays$/, holidaysPage],
  [/^.*$/, () => location.replace("#/movies")],   // old #/collections links land here
];

let refreshTimer = null;

async function route() {
  clearInterval(refreshTimer);
  const hash = location.hash || "#/movies";
  document.querySelectorAll("[data-nav]").forEach((a) =>
    a.classList.toggle("active", hash.startsWith(`#/${a.dataset.nav}`)));
  // A parent link (Settings) is marked while one of its sub-pages is open.
  document.querySelectorAll("[data-group]").forEach((g) =>
    g.classList.toggle("parent-active", [...document.querySelectorAll(`[data-parent="${g.dataset.group}"]`)]
      .some((a) => a.classList.contains("active"))));
  document.getElementById("sidebar").classList.remove("open");
  for (const [re, fn] of routes) {
    const m = hash.match(re);
    if (m) {
      view.innerHTML = `<p class="muted">Loading…</p>`;
      try { await fn(m); } catch (err) {
        view.innerHTML = `<div class="card"><h2>Something went wrong</h2><p class="muted">${esc(err.message)}</p></div>`;
      }
      return;
    }
  }
}

window.addEventListener("hashchange", route);
document.getElementById("menuBtn").onclick = () => document.getElementById("sidebar").classList.toggle("open");

async function loadStatus() {
  const el = document.getElementById("serverStatus");
  try {
    const s = await api("GET", "/status");
    document.getElementById("version").textContent = `v${s.version}`;
    el.innerHTML = s.plex
      ? `<span class="dot" style="background:var(--ok)"></span>${esc(s.plex.name)} · Plex ${esc(s.plex.version)}`
      : `<span class="dot" style="background:var(--err)"></span>${esc(s.plex_error || "Plex not connected")}`;
  } catch (err) {
    el.textContent = err.message;
  }
}

// ---------- collections list ----------

function sourceSummary(cfg) {
  const labels = Object.fromEntries(state.catalog.map((c) => [c.type, c.label]));
  return cfg.sources.map((s) => labels[s.type] || s.type).join(", ");
}

// ---------- home screen calendar (mirrors CollectionConfig.promotion_active) ----------

function localToday() {
  const d = new Date();
  return [d.getFullYear(), d.getMonth() + 1, d.getDate()];
}

function promotionActive(cfg, today = localToday()) {
  if (!cfg.promote_window) return true;
  if (!cfg.promote_start || !cfg.promote_end) return false;
  const [sy, sm, sd] = cfg.promote_start.split("-").map(Number);
  const [ey, em, ed] = cfg.promote_end.split("-").map(Number);
  const [ty, tm, td] = today;
  if (!cfg.promote_yearly) {
    const t = ty * 10000 + tm * 100 + td;
    return sy * 10000 + sm * 100 + sd <= t && t <= ey * 10000 + em * 100 + ed;
  }
  const day = tm * 100 + td, first = sm * 100 + sd, last = em * 100 + ed;
  return first <= last ? first <= day && day <= last : day >= first || day <= last;
}

function windowText(cfg) {
  const fmt = (iso) => {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString(undefined,
      cfg.promote_yearly ? { month: "short", day: "numeric" } : { year: "numeric", month: "short", day: "numeric" });
  };
  if (!cfg.promote_start || !cfg.promote_end) return "dates not set";
  return `${fmt(cfg.promote_start)} – ${fmt(cfg.promote_end)}${cfg.promote_yearly ? ", every year" : ""}`;
}

const KINDS = {
  movie: { title: "Movie collections", hash: "#/movies", noun: "movie" },
  show: { title: "TV show collections", hash: "#/tv", noun: "TV" },
};

// "movie" or "show" for a Curatarr collection, from its Plex library.
function collectionKind(cfg, libs) {
  const lib = libs.find((l) => l.id === String(cfg.section_id)) || libs.find((l) => l.title === cfg.library);
  return lib?.type || null;
}

async function collections(kind) {
  await catalog();
  const [allRows, libs] = await Promise.all([
    api("GET", "/collections"),
    libraries().catch(() => null),
  ]);
  // Without Plex the library types are unknown, so show everything rather than hide collections.
  // Holiday collections live on the Holidays page.
  const regular = allRows.filter((r) => !r.config.holiday);
  const rows = libs ? regular.filter((r) => collectionKind(r.config, libs) === kind) : regular;
  const meta = KINDS[kind];
  const cards = rows.map((r) => {
    const cfg = r.config;
    const poster = cfg.poster_file
      ? `<img class="poster" src="/api/collections/${r.id}/image/poster?v=${encodeURIComponent(r.poster_applied || cfg.poster_file)}" alt="">`
      : (cfg.poster_url ? `<img class="poster" src="${esc(cfg.poster_url)}" alt="" referrerpolicy="no-referrer">` : `<div class="poster">▦</div>`);
    return `
      <div class="coll${cfg.enabled ? "" : " disabled"}">
        ${poster}
        <div class="coll-body">
          <a class="coll-title" href="#/collections/${r.id}/items" title="View ${esc(cfg.name)}">${esc(cfg.name)}</a>
          <div class="small muted">${esc(cfg.library || "?")} · ${esc(sourceSummary(cfg))}</div>
          <div class="small">${r.running ? badge("running") : badge(r.last_status)} <span class="muted">${esc(when(r.last_run))}</span></div>
          ${r.last_message ? `<div class="small muted" title="${esc(r.last_message)}" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(r.last_message)}</div>` : ""}
          <div class="small muted">Next: ${cfg.enabled ? esc(when(r.next_run)) : "disabled"}</div>
          ${cfg.promote_window ? `<div class="small muted">Home screen: ${esc(windowText(cfg))}
            ${promotionActive(cfg) ? `<span class="badge success">showing</span>` : `<span class="badge">hidden</span>`}</div>` : ""}
          <div class="coll-actions">
            <button class="small primary" data-run="${r.id}" ${r.running ? "disabled" : ""}>Sync now</button>
            <a class="btn small" href="#/collections/${r.id}/items" style="padding:4px 10px;font-size:.8rem">View</a>
            <a class="btn small" href="#/collections/${r.id}" style="padding:4px 10px;font-size:.8rem">Edit</a>
            <button class="small danger" data-del="${r.id}" data-name="${esc(cfg.name)}">Delete</button>
          </div>
        </div>
      </div>`;
  }).join("");

  view.innerHTML = `
    <div class="page-head">
      <h1>${meta.title}</h1>
      <div class="actions">
        ${rows.length ? `<button id="runAll">Sync all</button>` : ""}
        <a class="btn primary" href="#/collections/new?type=${kind}">+ New collection</a>
      </div>
    </div>
    ${libs ? "" : `<p class="hint">Plex isn't reachable, so collections from every library are shown.</p>`}
    ${rows.length ? `<div class="collections">${cards}</div>` : `
      <div class="card empty">
        <p>No ${meta.noun} collections yet.</p>
        <p class="small">Create one from a TMDB, Trakt, MDBList or IMDb list, or use <strong>Sync with a list</strong> on one of your existing Plex collections below.
          Plex must be connected in <a href="#/settings">Settings</a> first.</p>
        <a class="btn primary" href="#/collections/new?type=${kind}">Create a ${meta.noun} collection</a>
      </div>`}
    <section id="plexExisting" style="margin-top:32px"></section>`;

  existingPlexCollections(view.querySelector("#plexExisting"), kind);

  view.querySelector("#runAll")?.addEventListener("click", () => guard(async () => {
    const enabled = rows.filter((r) => r.config.enabled && !r.running);
    if (!enabled.length) return toast("No enabled collections to sync", true);
    for (const r of enabled) await api("POST", `/collections/${r.id}/run`);
    toast(`Syncing ${enabled.length} collection(s)`);
    setTimeout(route, 1500);
  }));
  view.querySelectorAll("[data-run]").forEach((b) => b.onclick = () => guard(async () => {
    b.disabled = true;
    await api("POST", `/collections/${b.dataset.run}/run`);
    toast("Sync started");
    setTimeout(route, 1500);
  }));
  view.querySelectorAll("[data-del]").forEach((b) => b.onclick = () => guard(async () => {
    if (!confirm(`Delete "${b.dataset.name}" from Curatarr?`)) return;
    const fromPlex = confirm("Also delete the collection from Plex?\n\nOK = delete it in Plex too, Cancel = keep it in Plex.");
    const r = await api("DELETE", `/collections/${b.dataset.del}?remove_from_plex=${fromPlex}`);
    toast(r.message || "Collection deleted", !!r.message);
    route();
  }));
  if (rows.some((r) => r.running)) refreshTimer = setInterval(route, 4000);
}

// Collections that exist in Plex but aren't managed by Curatarr yet. Cached
// briefly so the auto-refresh while a sync runs doesn't hammer Plex.
async function existingPlexCollections(el, kind) {
  const fresh = state.plexColls && Date.now() - state.plexColls.at < 60000;
  let items;
  try {
    items = fresh ? state.plexColls.items : await api("GET", "/plex/collections");
    state.plexColls = { at: fresh ? state.plexColls.at : Date.now(), items };
  } catch (err) {
    el.innerHTML = `<h2>Existing Plex collections</h2><p class="muted small">Could not load collections from Plex: ${esc(err.message)}</p>`;
    return;
  }
  const unmanaged = items.filter((c) => !c.managed_id && c.section_type === kind);
  if (!unmanaged.length) { el.innerHTML = ""; return; }
  const byLibrary = {};
  unmanaged.forEach((c) => (byLibrary[c.section_title] ||= []).push(c));
  // The whole section starts collapsed (it can be long); each library inside starts open.
  el.innerHTML = `
    <details class="fold" data-fold="${kind}.existing" ${foldOpen(`${kind}.existing`, false) ? "open" : ""}>
    <summary class="fold-head"><h2>Existing Plex collections</h2><span class="muted small">${unmanaged.length}</span></summary>
    <p class="hint" style="margin-top:0">Collections already in Plex. Link one to a list and Curatarr keeps it in sync from then on.</p>
    ${Object.entries(byLibrary).map(([lib, colls]) => `
      <details class="fold" data-fold="${kind}.lib.${esc(lib)}" ${foldOpen(`${kind}.lib.${lib}`, true) ? "open" : ""}>
      <summary class="fold-head lib-head"><h3>${esc(lib)}</h3><span class="muted small">${colls.length}</span></summary>
      <div class="collections">${colls.map((c) => `
        <div class="coll existing">
          ${c.thumb ? `<img class="poster" loading="lazy" src="/api/plex/image?path=${encodeURIComponent(c.thumb)}" alt="">` : `<div class="poster">▦</div>`}
          <div class="coll-body">
            <a class="coll-title" href="${plexView(c, kind)}" title="View ${esc(c.title)}">${esc(c.title)}</a>
            <div class="small muted">${esc(lib)} · ${c.childCount} item${c.childCount === 1 ? "" : "s"}</div>
            ${c.smart ? `<div class="small"><span class="badge">smart</span> <span class="muted">Plex keeps this one updated itself</span></div>` : ""}
            <div class="coll-actions">
              <a class="btn small" style="padding:4px 10px;font-size:.8rem" href="${plexView(c, kind)}">View</a>
              ${c.smart ? "" : `<a class="btn small" style="padding:4px 10px;font-size:.8rem"
                href="#/collections/new?${new URLSearchParams({ link: c.ratingKey, section: c.section_id, title: c.title, items: c.childCount })}">Sync with a list</a>`}
            </div>
          </div>
        </div>`).join("")}
      </div></details>`).join("")}
    </details>`;
  bindFolds(el);
}

const plexView = (c, kind) => `#/plex/${c.ratingKey}?${esc(new URLSearchParams({
  title: c.title, library: c.section_title, section: c.section_id, kind, smart: c.smart ? "1" : "0" }))}`;

// Open/closed state of collapsible sections, remembered in this browser only.
function foldOpen(key, fallback) {
  try {
    const value = localStorage.getItem(`curatarr.fold.${key}`);
    return value === null ? fallback : value === "open";
  } catch {
    return fallback;
  }
}

function bindFolds(root) {
  root.querySelectorAll("details[data-fold]").forEach((d) => d.addEventListener("toggle", (e) => {
    e.stopPropagation();
    try { localStorage.setItem(`curatarr.fold.${d.dataset.fold}`, d.open ? "open" : "closed"); } catch { /* storage off */ }
  }));
}

// ---------- collection contents ----------

// What's in a collection, shown from Plex: a Curatarr collection (id) or any
// Plex collection (ratingKey plus title/library from the link).
async function collectionItems({ id = null, ratingKey = null, params = new URLSearchParams() }) {
  let row = null, title, library, back, inPlex = true, items;
  if (id) {
    const [r, contents, libs] = await Promise.all([
      api("GET", `/collections/${id}`),
      api("GET", `/collections/${id}/items`),
      libraries().catch(() => null),
    ]);
    row = r;
    ({ in_plex: inPlex, items } = contents);
    title = row.config.name;
    library = row.config.library;
    back = row.config.holiday ? "#/holidays" : (KINDS[libs && collectionKind(row.config, libs)] || KINDS.movie).hash;
  } else {
    items = await api("GET", `/plex/collections/${ratingKey}/items`);
    title = params.get("title") || "Plex collection";
    library = params.get("library") || "";
    back = (KINDS[params.get("kind")] || KINDS.movie).hash;
  }
  // Keep the page the collection came from highlighted in the menu.
  document.querySelector(`[data-nav="${back.slice(2)}"]`)?.classList.add("active");

  const watched = items.filter((i) => i.watched).length;
  const tile = (i) => `
    <div class="item" data-search="${esc(`${i.title} ${i.year || ""}`.toLowerCase())}">
      <div class="item-poster">
        ${i.thumb ? `<img loading="lazy" src="/api/plex/image?path=${encodeURIComponent(i.thumb)}" alt="">` : "▦"}
        ${i.watched ? `<span class="item-watched" title="Watched">✔</span>` : ""}
      </div>
      <div class="item-title" title="${esc(i.title)}">${esc(i.title)}</div>
      <div class="small muted">${esc(i.year || "")}${i.episodes ? ` · ${i.episodes} episode${i.episodes === 1 ? "" : "s"}` : ""}</div>
    </div>`;

  view.innerHTML = `
    <p class="small" style="margin:0 0 8px"><a href="${back}">← Back</a></p>
    <div class="page-head">
      <h1>${esc(title)}</h1>
      <span class="muted">${esc(library)}</span>
      <div class="actions">
        ${row ? `<button id="showMissing">Show missing titles</button>
          <button class="primary" id="runNow" ${row.running ? "disabled" : ""}>Sync now</button>
          <a class="btn" href="#/collections/${row.id}">Edit</a>` : ""}
        ${!row && params.get("smart") !== "1" ? `<a class="btn primary"
          href="#/collections/new?${new URLSearchParams({ link: ratingKey, section: params.get("section") || "", title, items: items.length })}">Sync with a list</a>` : ""}
      </div>
    </div>
    ${row?.last_message ? `<p class="small muted" style="margin-top:-8px">${badge(row.last_status)} ${esc(row.last_message)}</p>` : ""}
    <div id="missingOut"></div>
    ${inPlex ? `
      <div class="row" style="margin-bottom:16px">
        <div class="grow"><input type="text" id="itemFilter" placeholder="Filter ${items.length} title${items.length === 1 ? "" : "s"}…"></div>
        <span class="small muted" id="itemCount">${items.length} in Plex · ${watched} watched</span>
      </div>
      ${items.length ? `<div class="items">${items.map(tile).join("")}</div>` : `<div class="card empty">This collection is empty in Plex.</div>`}`
    : `<div class="card empty">
        <p>This collection isn't in Plex right now.</p>
        <p class="small">${row?.config.seasonal_only ? "It's only in Plex during its dates." : "It's created in Plex on its next sync."}</p>
      </div>`}`;

  const filter = view.querySelector("#itemFilter");
  if (filter) filter.oninput = () => {
    const q = filter.value.trim().toLowerCase();
    let shown = 0;
    view.querySelectorAll(".item").forEach((el) => {
      el.hidden = q && !el.dataset.search.includes(q);
      if (!el.hidden) shown++;
    });
    view.querySelector("#itemCount").textContent = q ? `${shown} of ${items.length} shown` : `${items.length} in Plex · ${watched} watched`;
  };
  if (!row) return;
  view.querySelector("#runNow").onclick = (e) => guard(async () => {
    e.target.disabled = true;
    await api("POST", `/collections/${row.id}/run`);
    toast("Sync started");
  });
  // Titles from the lists that aren't in the Plex library (fetched on demand: lists can be slow).
  view.querySelector("#showMissing").onclick = (e) => guard(async () => {
    const out = view.querySelector("#missingOut");
    e.target.disabled = true;
    out.innerHTML = `<p class="muted">Fetching lists and matching against Plex…</p>`;
    try {
      const cfg = row.config;
      const r = await api("POST", "/preview", { section_id: cfg.section_id, library: cfg.library, sources: cfg.sources, item_limit: cfg.item_limit });
      const missing = r.items.filter((i) => !i.in_plex);
      out.innerHTML = `
        <details class="card" open>
          <summary><strong>${missing.length}</strong> of ${r.total} list titles aren't in ${esc(r.library.title)}</summary>
          ${r.errors.map((err) => `<p class="no small">${esc(err)}</p>`).join("")}
          ${missing.length ? `<div class="table-wrap" style="max-height:320px;overflow:auto;margin-top:10px"><table>
            <thead><tr><th>Title</th><th>Year</th><th>IDs</th></tr></thead>
            <tbody>${missing.map((i) => `<tr><td>${esc(i.title || "—")}</td><td>${esc(i.year || "")}</td>
              <td class="small muted">${[i.imdb, i.tmdb && `tmdb:${i.tmdb}`, i.tvdb && `tvdb:${i.tvdb}`].filter(Boolean).map(esc).join(" · ")}</td></tr>`).join("")}
            </tbody></table></div>` : ""}
        </details>`;
    } catch (err) {
      out.innerHTML = `<p class="no">${esc(err.message)}</p>`;
    } finally {
      e.target.disabled = false;
    }
  });
}

// ---------- collection editor ----------

const DEFAULTS = {
  name: "", library: "", section_id: "", sources: [{ type: "tmdb_list", value: "", limit: null }],
  sync_mode: "sync", order: "custom", summary: "", sort_title: "", labels: [], collection_mode: "default",
  poster_url: "", art_url: "", poster_file: "", art_file: "", item_limit: 0, min_items: 1,
  delete_below_min: false, promote_home: false, promote_shared: false, promote_recommended: false,
  promote_window: false, promote_start: "", promote_end: "", promote_yearly: true, seasonal_only: false,
  schedule: "", request_missing: false, enabled: true,
};

function sourceRow(src, idx) {
  const options = state.catalog.map((c) =>
    `<option value="${c.type}" ${c.type === src.type ? "selected" : ""}>${esc(c.provider)} · ${esc(c.label)}</option>`).join("");
  const meta = state.catalog.find((c) => c.type === src.type) || {};
  const input = meta.options
    ? `<select data-field="value">${Object.entries(meta.options).map(([k, v]) =>
        `<option value="${esc(k)}" ${k === src.value ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>`
    : src.type === "static"
      ? `<textarea data-field="value" rows="3" placeholder="${esc(meta.placeholder || "")}">${esc(src.value)}</textarea>`
      : `<input type="text" data-field="value" value="${esc(src.value)}" placeholder="${esc(meta.placeholder || "")}">`;
  return `
    <div class="source" data-idx="${idx}">
      <select data-field="type">${options}</select>
      ${input}
      <input type="number" data-field="limit" min="1" placeholder="Limit" value="${src.limit ?? ""}" title="Max items from this source">
      <button type="button" class="small danger" data-remove="${idx}" title="Remove source">✕</button>
    </div>`;
}

async function editor(id, params = new URLSearchParams()) {
  await catalog();
  const [row, libs] = await Promise.all([
    id ? api("GET", `/collections/${id}`) : null,
    libraries().catch((err) => { toast(`Plex: ${err.message}`, true); return []; }),
  ]);
  const cfg = { ...DEFAULTS, ...(row?.config || {}) };
  cfg.sources = cfg.sources.map((s) => ({ ...s }));
  // Linking an existing Plex collection: keep its name and library, and default
  // to append so the titles already in it are not removed.
  const link = !id && params.get("link");
  if (link) {
    Object.assign(cfg, { name: params.get("title") || "", section_id: params.get("section") || "",
                         sync_mode: "append" });
  }
  // "+ New collection" on the Movies / TV page starts on a library of that type.
  if (!id && !link && params.get("type")) {
    cfg.section_id = libs.find((l) => l.type === params.get("type"))?.id || "";
  }
  const kind = collectionKind(cfg, libs) || params.get("type") || "movie";
  const backHash = () => {
    if (cfg.holiday) return "#/holidays";
    const opt = view.querySelector("#f-lib")?.selectedOptions[0];
    return KINDS[opt?.dataset.type || kind].hash;
  };
  document.querySelectorAll("[data-nav]").forEach((a) =>
    a.classList.toggle("active", a.getAttribute("href") === (cfg.holiday ? "#/holidays" : KINDS[kind].hash)));
  const settings = await api("GET", "/settings").catch(() => ({ values: {} }));
  const defaultSchedule = settings.values.default_schedule || "";
  // Image files picked in the form; uploaded (or removed) when the collection is saved.
  const images = { poster: { file: null, remove: false }, art: { file: null, remove: false } };

  const libOptions = libs.map((l) =>
    `<option value="${esc(l.id)}" data-title="${esc(l.title)}" data-type="${esc(l.type)}" ${l.id === cfg.section_id || (!cfg.section_id && l.title === cfg.library) ? "selected" : ""}>${esc(l.title)} (${l.type === "show" ? "TV" : "Movies"})</option>`).join("");

  view.innerHTML = `
    <div class="page-head">
      <h1>${id ? esc(cfg.name) : link ? `Sync “${esc(cfg.name)}”` : "New collection"}</h1>
      <div class="actions">
        ${id ? `<button id="dryRun">Dry run</button>` : ""}
        <button id="save">Save</button>
        <button id="saveRun" class="primary">Save &amp; sync</button>
      </div>
    </div>

    ${link ? `<div class="notice">
      Linking to the existing Plex collection <strong>${esc(cfg.name)}</strong> (${esc(params.get("items") || "0")} items).
      Add the lists it should follow below. <strong>Append</strong> mode is selected so the titles already in it stay;
      switch to <strong>Sync</strong> only if you want Curatarr to remove anything that isn't on your lists.
    </div>` : ""}

    ${row && row.plex_owned === 0 ? `<div class="notice">
      A Plex collection named <strong>${esc(cfg.name)}</strong> already existed, so Curatarr is using it but only
      <strong>adds</strong> titles — it never removes titles from it or deletes it.
      <div style="margin-top:8px"><button type="button" class="small" id="ownIt">Let Curatarr remove titles too</button></div>
    </div>` : ""}

    <div class="card">
      <h2>Basics</h2>
      <div class="grid">
        <div><label for="f-name">Collection name</label><input type="text" id="f-name" value="${esc(cfg.name)}" placeholder="IMDb Top 250" ${link ? "readonly" : ""}></div>
        <div><label for="f-lib">Plex library</label>
          <select id="f-lib" ${link ? "disabled" : ""}>${libOptions || `<option value="${esc(cfg.section_id)}" data-title="${esc(cfg.library)}">${esc(cfg.library || "Connect Plex first")}</option>`}</select></div>
        <div><label class="check"><input type="checkbox" id="f-enabled" ${cfg.enabled ? "checked" : ""}> Enabled (sync on schedule)</label></div>
      </div>
    </div>

    <div class="card">
      <h2>Lists</h2>
      <p class="hint" style="margin-top:-6px">Titles from every source are merged in order. Duplicates and titles of the wrong type for the library are skipped.</p>
      <div id="sources"></div>
      <div class="row" style="margin-top:8px">
        <button type="button" id="addSource">+ Add source</button>
        <button type="button" id="preview">Preview matches</button>
      </div>
      <div id="previewOut"></div>
    </div>

    <div class="card">
      <h2>Sync behaviour</h2>
      <div class="grid">
        <div><label for="f-mode">Mode</label>
          <select id="f-mode">
            <option value="sync" ${cfg.sync_mode === "sync" ? "selected" : ""}>Sync: add new and remove titles no longer listed</option>
            <option value="append" ${cfg.sync_mode === "append" ? "selected" : ""}>Append: only add titles</option>
          </select></div>
        <div><label for="f-order">Order in Plex</label>
          <select id="f-order">
            <option value="custom" ${cfg.order === "custom" ? "selected" : ""}>List order</option>
            <option value="release" ${cfg.order === "release" ? "selected" : ""}>Release date</option>
            <option value="alpha" ${cfg.order === "alpha" ? "selected" : ""}>Alphabetical</option>
          </select></div>
        <div><label for="f-limit">Max items (0 = no limit)</label><input type="number" id="f-limit" min="0" value="${cfg.item_limit}"></div>
        <div><label for="f-min">Minimum matched items</label><input type="number" id="f-min" min="0" value="${cfg.min_items}">
          <label class="check"><input type="checkbox" id="f-delmin" ${cfg.delete_below_min ? "checked" : ""}> Delete the Plex collection when below minimum</label></div>
        <div><label for="f-schedule">Schedule (cron)</label><input type="text" id="f-schedule" value="${esc(cfg.schedule)}" placeholder="${esc(defaultSchedule)} (default)">
          <div class="hint">Five-field cron, e.g. <code>0 */6 * * *</code> for every 6 hours.</div></div>
        <div><label class="check"><input type="checkbox" id="f-request" ${cfg.request_missing ? "checked" : ""}> Send missing titles to Radarr / Sonarr</label></div>
      </div>
    </div>

    <div class="card">
      <h2>Appearance in Plex</h2>
      <div class="grid">
        <div class="full"><label for="f-summary">Summary</label><textarea id="f-summary">${esc(cfg.summary)}</textarea></div>
        <div><label for="f-sort">Sort title</label><input type="text" id="f-sort" value="${esc(cfg.sort_title)}" placeholder="!01 Top 250"></div>
        <div><label for="f-labels">Labels (comma separated)</label><input type="text" id="f-labels" value="${esc(cfg.labels.join(", "))}"></div>
        <div><label for="f-cmode">Collection visibility in library</label>
          <select id="f-cmode">
            <option value="default" ${cfg.collection_mode === "default" ? "selected" : ""}>Library default</option>
            <option value="hide" ${cfg.collection_mode === "hide" ? "selected" : ""}>Hide collection</option>
            <option value="hideItems" ${cfg.collection_mode === "hideItems" ? "selected" : ""}>Hide items, show collection</option>
            <option value="showItems" ${cfg.collection_mode === "showItems" ? "selected" : ""}>Show collection and items</option>
          </select></div>
        <div><label>Home screen</label>
          <label class="check"><input type="checkbox" id="f-rec" ${cfg.promote_recommended ? "checked" : ""}> Library recommended</label>
          <label class="check"><input type="checkbox" id="f-home" ${cfg.promote_home ? "checked" : ""}> My home</label>
          <label class="check"><input type="checkbox" id="f-shared" ${cfg.promote_shared ? "checked" : ""}> Friends' home</label></div>
        <div class="full calendar">
          <label class="check"><input type="checkbox" id="f-window" ${cfg.promote_window ? "checked" : ""}> Only show on the home screen between these dates</label>
          <div class="row" id="window-fields">
            <div><label for="f-wstart">From</label><input type="date" id="f-wstart" value="${esc(cfg.promote_start)}"></div>
            <div><label for="f-wend">Until (inclusive)</label><input type="date" id="f-wend" value="${esc(cfg.promote_end)}"></div>
            <div><label class="check"><input type="checkbox" id="f-wyearly" ${cfg.promote_yearly ? "checked" : ""}> Repeat every year</label></div>
          </div>
          <label class="check"><input type="checkbox" id="f-seasonal" ${cfg.seasonal_only ? "checked" : ""}> Only keep the collection in Plex during these dates (deleted after, re-created when they come round)</label>
          <div class="hint" id="window-status"></div>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>Artwork</h2>
      <div class="images">
        ${imageSlot(id, cfg, "poster", "Poster (2:3)")}
        ${imageSlot(id, cfg, "art", "Background (16:9)")}
      </div>
      <p class="hint">Chosen files are uploaded when you save. An image file takes priority over a URL. Collections built from a TMDB collection use the TMDB poster when nothing else is set.</p>
    </div>`;

  const sourcesEl = view.querySelector("#sources");
  const renderSources = () => {
    sourcesEl.innerHTML = cfg.sources.map(sourceRow).join("");
    sourcesEl.querySelectorAll(".source").forEach((el) => {
      const src = cfg.sources[Number(el.dataset.idx)];
      el.querySelector("[data-field=type]").onchange = (e) => {
        src.type = e.target.value;
        const meta = state.catalog.find((c) => c.type === src.type);
        src.value = meta.options ? Object.keys(meta.options)[0] : "";
        renderSources();
      };
      el.querySelector("[data-field=value]").oninput = (e) => { src.value = e.target.value; };
      el.querySelector("[data-field=value]").onchange = (e) => { src.value = e.target.value; };
      el.querySelector("[data-field=limit]").oninput = (e) => { src.limit = e.target.value ? Number(e.target.value) : null; };
      el.querySelector("[data-remove]").onclick = () => {
        if (cfg.sources.length > 1) { cfg.sources.splice(Number(el.dataset.idx), 1); renderSources(); }
      };
    });
  };
  renderSources();
  // Home screen calendar: date fields only matter when the box is ticked; ticking it
  // with no home screen spots chosen selects all three.
  const spots = ["#f-rec", "#f-home", "#f-shared"].map((s) => view.querySelector(s));
  const updateWindow = () => {
    const on = view.querySelector("#f-window").checked;
    view.querySelectorAll("#window-fields input, #f-seasonal").forEach((el) => { el.disabled = !on; });
    const status = view.querySelector("#window-status");
    if (!on) { status.textContent = ""; return; }
    const w = {
      promote_window: true,
      promote_start: view.querySelector("#f-wstart").value,
      promote_end: view.querySelector("#f-wend").value,
      promote_yearly: view.querySelector("#f-wyearly").checked,
    };
    const where = spots.filter((s) => s.checked).map((s) => s.parentElement.textContent.trim()).join(", ") || "no spots selected";
    status.textContent = !w.promote_start || !w.promote_end
      ? "Pick both dates."
      : `${windowText(w)} on ${where}. ${promotionActive(w) ? "Showing now." : "Hidden right now."} It switches automatically just after midnight.`
        + (view.querySelector("#f-seasonal").checked
          ? ` Outside these dates the collection is deleted from Plex${promotionActive(w) ? "" : " (it's out of season now, so it'll be removed at the next sync)"}.`
          : "");
  };
  view.querySelector("#f-window").addEventListener("change", (e) => {
    if (e.target.checked && !spots.some((s) => s.checked)) spots.forEach((s) => { s.checked = true; });
    updateWindow();
  });
  ["#f-wstart", "#f-wend", "#f-wyearly", "#f-seasonal", ...["#f-rec", "#f-home", "#f-shared"]].forEach((sel) =>
    view.querySelector(sel).addEventListener("change", updateWindow));
  updateWindow();

  view.querySelector("#ownIt")?.addEventListener("click", () => guard(async () => {
    if (!confirm(`Let Curatarr fully manage "${cfg.name}"?\n\nIn Sync mode, titles that aren't on your lists will be removed from this Plex collection.`)) return;
    await api("POST", `/collections/${id}/own`);
    toast("Curatarr now fully manages this collection");
    route();
  }));

  view.querySelector("#addSource").onclick = () => { cfg.sources.push({ type: "tmdb_list", value: "", limit: null }); renderSources(); };

  const collect = () => {
    const lib = view.querySelector("#f-lib");
    const opt = lib.selectedOptions[0];
    return {
      ...cfg,
      name: view.querySelector("#f-name").value,
      section_id: lib.value,
      library: opt?.dataset.title || "",
      enabled: view.querySelector("#f-enabled").checked,
      sync_mode: view.querySelector("#f-mode").value,
      order: view.querySelector("#f-order").value,
      item_limit: Number(view.querySelector("#f-limit").value || 0),
      min_items: Number(view.querySelector("#f-min").value || 0),
      delete_below_min: view.querySelector("#f-delmin").checked,
      schedule: view.querySelector("#f-schedule").value,
      request_missing: view.querySelector("#f-request").checked,
      summary: view.querySelector("#f-summary").value,
      sort_title: view.querySelector("#f-sort").value,
      labels: view.querySelector("#f-labels").value.split(",").map((s) => s.trim()).filter(Boolean),
      collection_mode: view.querySelector("#f-cmode").value,
      promote_recommended: view.querySelector("#f-rec").checked,
      promote_home: view.querySelector("#f-home").checked,
      promote_shared: view.querySelector("#f-shared").checked,
      promote_window: view.querySelector("#f-window").checked,
      promote_start: view.querySelector("#f-wstart").value,
      promote_end: view.querySelector("#f-wend").value,
      promote_yearly: view.querySelector("#f-wyearly").checked,
      seasonal_only: view.querySelector("#f-seasonal").checked,
      poster_url: view.querySelector("#poster-url").value,
      art_url: view.querySelector("#art-url").value,
      sources: cfg.sources.filter((s) => s.value),
    };
  };

  const save = async () => {
    const body = collect();
    const saved = id
      ? await api("PUT", `/collections/${id}`, body)
      : await api("POST", `/collections${link ? `?plex_rating_key=${encodeURIComponent(link)}` : ""}`, body);
    await applyImages(saved.id, images);   // before any sync, so the first sync uses them
    state.plexColls = null;
    toast("Saved");
    return saved;
  };

  view.querySelector("#save").onclick = () => guard(async () => {
    const saved = await save();
    if (!id) location.hash = `#/collections/${saved.id}`;
  });
  view.querySelector("#saveRun").onclick = () => guard(async () => {
    const saved = await save();
    await api("POST", `/collections/${saved.id}/run`);
    toast("Sync started");
    location.hash = backHash();
  });
  view.querySelector("#dryRun")?.addEventListener("click", () => guard(async () => {
    await save();
    toast("Dry run in progress…");
    const r = await api("POST", `/collections/${id}/run?dry_run=true`);
    toast(`${r.status}: ${r.message || ""}`, r.status === "error");
  }));

  view.querySelector("#preview").onclick = () => guard(async () => {
    const out = view.querySelector("#previewOut");
    out.innerHTML = `<p class="muted">Fetching lists and matching against Plex…</p>`;
    const body = collect();
    try {
      const r = await api("POST", "/preview", { section_id: body.section_id, library: body.library, sources: body.sources, item_limit: body.item_limit });
      out.innerHTML = `
        <p><strong>${r.matched}</strong> of <strong>${r.total}</strong> titles are in <em>${esc(r.library.title)}</em>.</p>
        ${r.errors.map((e) => `<p class="no small">${esc(e)}</p>`).join("")}
        <div class="table-wrap" style="max-height:420px;overflow:auto"><table>
          <thead><tr><th>#</th><th>Title</th><th>Year</th><th>IDs</th><th>In Plex</th></tr></thead>
          <tbody>${r.items.map((i, n) => `
            <tr><td>${n + 1}</td><td>${esc(i.plex_title || i.title || "—")}</td><td>${esc(i.year || "")}</td>
            <td class="small muted">${[i.imdb, i.tmdb && `tmdb:${i.tmdb}`, i.tvdb && `tvdb:${i.tvdb}`].filter(Boolean).map(esc).join(" · ")}</td>
            <td>${i.in_plex ? `<span class="yes">✔</span>` : `<span class="no">✖</span>`}</td></tr>`).join("")}
          </tbody></table></div>`;
    } catch (err) {
      out.innerHTML = `<p class="no">${esc(err.message)}</p>`;
    }
  });

  for (const kind of ["poster", "art"]) {
    const input = view.querySelector(`#${kind}-file`);
    const del = view.querySelector(`#${kind}-del`);
    const urlInput = view.querySelector(`#${kind}-url`);
    input.onchange = () => {
      const file = input.files[0];
      if (!file) return;
      if (!IMAGE_TYPES.includes(file.type)) { input.value = ""; return toast("Choose a JPEG, PNG or WebP image", true); }
      if (file.size > MAX_IMAGE_BYTES) { input.value = ""; return toast("Images must be 10 MB or smaller", true); }
      images[kind] = { file, remove: false };
      showImage(kind, URL.createObjectURL(file));
      del.hidden = false;
    };
    del.onclick = () => {
      input.value = "";
      images[kind] = { file: null, remove: Boolean(cfg[`${kind}_file`]) };
      showImage(kind, urlInput.value.trim());
      del.hidden = true;
    };
    urlInput.oninput = () => {
      if (!images[kind].file && (images[kind].remove || !cfg[`${kind}_file`])) showImage(kind, urlInput.value.trim());
    };
  }

  function showImage(kind, src) {
    const box = view.querySelector(`#${kind}-preview`);
    box.innerHTML = src ? `<img src="${esc(src)}" alt="" referrerpolicy="no-referrer">` : "▦";
  }
}

const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

// Upload or remove images chosen in the editor; runs after the collection is saved.
async function applyImages(collectionId, images) {
  for (const kind of ["poster", "art"]) {
    const { file, remove } = images[kind];
    if (file) {
      const form = new FormData();
      form.append("file", file);
      await api("POST", `/collections/${collectionId}/image/${kind}`, form);
    } else if (remove) {
      await api("DELETE", `/collections/${collectionId}/image/${kind}`);
    }
    images[kind] = { file: null, remove: false };
  }
}

function imageSlot(id, cfg, kind, title) {
  const file = cfg[`${kind}_file`];
  const url = cfg[`${kind}_url`];
  const cls = kind === "poster" ? "poster-img" : "art-img";
  const src = file ? `/api/collections/${id}/image/${kind}?v=${Date.now()}` : url;
  return `
    <div class="image-slot">
      <label>${title}</label>
      <div id="${kind}-preview" class="${cls} image-box">${src ? `<img src="${esc(src)}" alt="" referrerpolicy="no-referrer">` : "▦"}</div>
      <input type="file" id="${kind}-file" accept="image/jpeg,image/png,image/webp">
      <button type="button" class="small danger" id="${kind}-del" ${file ? "" : "hidden"}>Remove image file</button>
      <input type="url" id="${kind}-url" value="${esc(url)}" placeholder="…or image URL">
    </div>`;
}

// ---------- history ----------

async function history() {
  const runs = await api("GET", "/runs?limit=200");
  view.innerHTML = `
    <div class="page-head"><h1>History</h1></div>
    ${runs.length ? `<div class="card table-wrap"><table>
      <thead><tr><th>When</th><th>Collection</th><th>Status</th><th>Matched</th><th>+ / −</th><th>Missing</th><th>Details</th></tr></thead>
      <tbody>${runs.map((r) => `
        <tr>
          <td class="small">${esc(when(r.finished || r.started))}<div class="muted">${esc(r.trigger)}</div></td>
          <td>${esc(r.collection_name)}</td>
          <td>${badge(r.status)}</td>
          <td>${r.matched}/${r.source_count}</td>
          <td>+${r.added} / −${r.removed}${r.requested ? `<div class="small muted">${r.requested} requested</div>` : ""}</td>
          <td>${r.missing.length ? `<details><summary>${r.missing.length}</summary><ul class="small">${r.missing.map((m) =>
            `<li>${esc(m.title || m.imdb || (m.tmdb && "tmdb:" + m.tmdb) || (m.tvdb && "tvdb:" + m.tvdb))}${m.year ? ` (${m.year})` : ""}</li>`).join("")}</ul></details>` : "0"}</td>
          <td class="small muted">${esc(r.message)}</td>
        </tr>`).join("")}
      </tbody></table></div>` : `<div class="card empty">No syncs have run yet.</div>`}`;
}

// ---------- holidays ----------

async function holidaysPage() {
  const [list, allLibs] = await Promise.all([
    api("GET", "/holidays"),
    libraries().catch(() => []),
  ]);
  // Holiday lists are movie keywords, so only movie libraries are offered.
  const libs = allLibs.filter((l) => l.type === "movie");
  const arrReady = list[0]?.arr_ready || {};
  state.holidayArr ||= {};
  state.holidaySeasonal ||= {};
  let sectionId = state.holidayLibrary && libs.some((l) => l.id === state.holidayLibrary)
    ? state.holidayLibrary
    : (libs.find((l) => l.type === "movie") || libs[0])?.id || "";

  const render = () => {
    state.holidayLibrary = sectionId;
    const cards = list.map((h) => {
      const coll = h.collections.find((c) => String(c.config.section_id) === sectionId);
      const others = h.collections.filter((c) => c !== coll).map((c) => c.config.library);
      const cfg = coll?.config || {
        promote_window: true, promote_yearly: true,
        promote_start: `2000-${h.start}`, promote_end: `2000-${h.end}`,
      };
      const poster = h.poster
        ? `<img class="poster" src="${esc(h.poster)}" alt="">`
        : `<div class="poster">▦</div>`;
      return `
        <div class="coll holiday${coll ? "" : " off"}">
          ${poster}
          <div class="coll-body">
            <label class="check holiday-toggle">
              <input type="checkbox" data-holiday="${esc(h.key)}" ${coll ? "checked" : ""} ${h.available || coll ? "" : "disabled"}>
              <span class="coll-title">${esc(h.name)}</span>
            </label>
            <div class="small muted">${esc(windowText(cfg))}${h.link ? ` · <a href="${esc(h.link)}" target="_blank" rel="noopener">TMDB list</a>` : ""}</div>
            ${h.available || coll ? `<label class="check small" title="${arrReady.radarr ? "" : "Set up Radarr in Settings first"}">
              <input type="checkbox" data-arr="${esc(h.key)}" ${(coll ? coll.config.request_missing : state.holidayArr[h.key]) ? "checked" : ""} ${arrReady.radarr ? "" : "disabled"}>
              Add missing movies to Radarr${arrReady.radarr ? "" : ` <a href="#/settings">(set up Radarr)</a>`}</label>` : ""}
            ${h.available || coll ? `<label class="check small">
              <input type="checkbox" data-seasonal="${esc(h.key)}" ${(coll ? coll.config.seasonal_only : state.holidaySeasonal[h.key]) ? "checked" : ""}>
              Only in Plex during its dates (deleted after)</label>` : ""}
            ${coll ? `
              <div class="small">${promotionActive(cfg)
                ? `<span class="badge success">on home screen now</span>`
                : cfg.seasonal_only ? `<span class="badge">not in Plex until ${esc(windowText(cfg).split(" – ")[0])}</span>` : `<span class="badge">off season</span>`}
                ${coll.running ? badge("running") : badge(coll.last_status)}</div>
              ${coll.last_message ? `<div class="small muted" title="${esc(coll.last_message)}" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(coll.last_message)}</div>` : ""}
              <div class="coll-actions">
                <button class="small primary" data-run="${coll.id}" ${coll.running ? "disabled" : ""}>Sync now</button>
                <a class="btn small" href="#/collections/${coll.id}/items" style="padding:4px 10px;font-size:.8rem">View</a>
                <a class="btn small" href="#/collections/${coll.id}" style="padding:4px 10px;font-size:.8rem">Edit dates &amp; settings</a>
              </div>`
            : `<div class="small muted">${h.available ? "Tick to create it in this library." : "Lists not added yet."}</div>`}
            ${others.length ? `<div class="small muted">Also on in: ${others.map(esc).join(", ")}</div>` : ""}
          </div>
        </div>`;
    }).join("");

    view.innerHTML = `
      <div class="page-head"><h1>Holiday collections</h1></div>
      <p class="hint" style="margin-top:-8px">Tick a holiday to create its collection. It shows on Library recommended,
        My home and Friends' home during its dates every year and is hidden the rest of the year.
        Use <strong>Edit dates &amp; settings</strong> to change the dates or where it appears.</p>
      <div class="row" style="margin-bottom:16px">
        <div><label for="holidayLib">Library</label>
          <select id="holidayLib">${libs.map((l) => `<option value="${esc(l.id)}" ${l.id === sectionId ? "selected" : ""}>${esc(l.title)} (${l.type === "show" ? "TV" : "Movies"})</option>`).join("")
            || `<option value="">Connect Plex first</option>`}</select></div>
      </div>
      <div class="collections">${cards}</div>`;

    view.querySelector("#holidayLib").onchange = (e) => { sectionId = e.target.value; render(); };
    view.querySelectorAll("[data-run]").forEach((b) => b.onclick = () => guard(async () => {
      b.disabled = true;
      await api("POST", `/collections/${b.dataset.run}/run`);
      toast("Sync started");
      setTimeout(route, 1500);
    }));
    // Radarr choice: remembered for a holiday that's off, saved straight away for one that's on.
    view.querySelectorAll("[data-arr]").forEach((box) => box.onchange = () => guard(async () => {
      const h = list.find((x) => x.key === box.dataset.arr);
      const coll = h.collections.find((c) => String(c.config.section_id) === sectionId);
      if (!coll) { state.holidayArr[h.key] = box.checked; return; }
      if (box.checked && !confirm(`Add ${h.name}'s missing movies to Radarr from now on?\n\nUp to 100 movies could be added and searched for on the next sync.`)) {
        box.checked = false; return;
      }
      await api("PUT", `/collections/${coll.id}`, { ...coll.config, request_missing: box.checked });
      coll.config.request_missing = box.checked;
      toast(box.checked ? "Missing movies will be added to Radarr on the next sync" : "Radarr requests turned off");
    }));
    // Seasonal choice works the same way as the Radarr one.
    view.querySelectorAll("[data-seasonal]").forEach((box) => box.onchange = () => guard(async () => {
      const h = list.find((x) => x.key === box.dataset.seasonal);
      const coll = h.collections.find((c) => String(c.config.section_id) === sectionId);
      if (!coll) { state.holidaySeasonal[h.key] = box.checked; return; }
      const outOfSeason = !promotionActive(coll.config);
      if (box.checked && outOfSeason && !confirm(`${h.name} is out of season, so its Plex collection will be deleted at the next sync and re-created when its dates come round. Continue?`)) {
        box.checked = false; return;
      }
      await api("PUT", `/collections/${coll.id}`, { ...coll.config, seasonal_only: box.checked });
      coll.config.seasonal_only = box.checked;
      if (outOfSeason) await api("POST", `/collections/${coll.id}/run`);   // apply now (remove or re-create)
      toast(box.checked ? `${h.name} will only be in Plex during its dates` : `${h.name} stays in Plex all year`);
      setTimeout(route, 1500);
    }));
    view.querySelectorAll("[data-holiday]").forEach((box) => box.onchange = () => guard(async () => {
      const h = list.find((x) => x.key === box.dataset.holiday);
      const coll = h.collections.find((c) => String(c.config.section_id) === sectionId);
      box.disabled = true;
      try {
        if (box.checked) {
          if (!sectionId) throw new Error("Connect Plex and pick a library first");
          const requestMissing = Boolean(state.holidayArr[h.key]);
          if (requestMissing && !confirm(`Turn on ${h.name} and add its missing movies to Radarr?\n\nUp to 100 movies could be added and searched for.`)) {
            box.checked = false; return;
          }
          const seasonalOnly = Boolean(state.holidaySeasonal[h.key]);
          await api("POST", `/holidays/${h.key}/enable`,
            { section_id: sectionId, request_missing: requestMissing, seasonal_only: seasonalOnly });
          toast(seasonalOnly && !promotionActive({ promote_window: true, promote_yearly: true,
                promote_start: `2000-${h.start}`, promote_end: `2000-${h.end}` })
            ? `${h.name} turned on; it'll appear in Plex when its dates start`
            : `${h.name} collection created; first sync started`);
        } else if (coll) {
          if (!confirm(`Turn off ${h.name}? Its collection is removed from Curatarr.`)) { box.checked = true; return; }
          const fromPlex = confirm("Also delete the collection from Plex?\n\nOK = delete it in Plex too, Cancel = keep it in Plex.");
          await api("DELETE", `/collections/${coll.id}?remove_from_plex=${fromPlex}`);
          toast(`${h.name} turned off`);
        }
      } catch (err) {
        box.checked = !box.checked;
        throw err;
      } finally {
        box.disabled = false;
      }
      route();
    }));
    if (list.some((h) => h.collections.some((c) => c.running))) refreshTimer = setInterval(route, 4000);
  };
  render();
}

// ---------- logs ----------

async function logsPage() {
  view.innerHTML = `
    <div class="page-head">
      <h1>Logs</h1>
      <div class="actions">
        <a class="btn primary" href="/api/logs/download" download>Download logs</a>
      </div>
    </div>
    <div class="card">
      <div class="row" style="margin-bottom:12px">
        <div><label for="logLevel">Level</label>
          <select id="logLevel">
            <option value="">All</option>
            <option value="INFO">Info and above</option>
            <option value="WARNING" selected>Warnings and errors</option>
            <option value="ERROR">Errors only</option>
          </select></div>
        <div class="grow"><label for="logSearch">Search</label><input type="text" id="logSearch" placeholder="Collection name, error text…"></div>
        <button type="button" id="logRefresh">Refresh</button>
      </div>
      <p class="hint" style="margin-top:0">Downloads include all log files and a summary of your setup. Tokens and API keys are removed.</p>
      <div id="logOut" class="log-view"></div>
    </div>`;

  const load = () => guard(async () => {
    const params = new URLSearchParams({
      lines: "1000",
      level: view.querySelector("#logLevel").value,
      search: view.querySelector("#logSearch").value,
    });
    const entries = await api("GET", `/logs?${params}`);
    const out = view.querySelector("#logOut");
    out.innerHTML = entries.length
      ? entries.slice().reverse().map((e) => `
          <div class="log-line lvl-${esc(e.level)}">
            <span class="log-time">${esc(e.time)}</span>
            <span class="log-level">${esc(e.level)}</span>
            <span class="log-msg"><span class="muted">${esc(e.logger)}:</span> ${esc(e.message)}</span>
          </div>`).join("")
      : `<p class="muted">No log entries match.</p>`;
  });

  view.querySelector("#logLevel").onchange = load;
  view.querySelector("#logRefresh").onclick = load;
  let timer;
  view.querySelector("#logSearch").oninput = () => { clearTimeout(timer); timer = setTimeout(load, 300); };
  await load();
}

// ---------- settings ----------

const SETTING_GROUPS = [
  { title: "TMDB", test: "tmdb", fields: [
    ["tmdb_api_key", "API key (v3) or Read Access Token (v4)", "password", ""],
  ], hint: `Free at <a href="https://www.themoviedb.org/settings/api" target="_blank" rel="noopener">themoviedb.org/settings/api</a>. Needed for TMDB sources.` },
  { title: "Trakt", test: "trakt", fields: [
    ["trakt_client_id", "Client ID", "password", ""],
  ], hint: `Create an API app at <a href="https://trakt.tv/oauth/applications" target="_blank" rel="noopener">trakt.tv/oauth/applications</a>.` },
  { title: "MDBList", test: "mdblist", fields: [
    ["mdblist_api_key", "API key", "password", ""],
  ], hint: `From your <a href="https://mdblist.com/preferences/" target="_blank" rel="noopener">MDBList preferences</a>.` },
  { title: "Radarr (missing movies)", test: "radarr", arr: "radarr", fields: [
    ["radarr_url", "URL", "url", "http://radarr:7878"],
    ["radarr_api_key", "API key", "password", ""],
    ["radarr_root_folder", "Root folder", "text", "/movies"],
    ["radarr_quality_profile", "Quality profile id", "text", "1"],
    ["radarr_search", "Search when added", "bool"],
  ] },
  { title: "Sonarr (missing shows)", test: "sonarr", arr: "sonarr", fields: [
    ["sonarr_url", "URL", "url", "http://sonarr:8989"],
    ["sonarr_api_key", "API key", "password", ""],
    ["sonarr_root_folder", "Root folder", "text", "/tv"],
    ["sonarr_quality_profile", "Quality profile id", "text", "1"],
    ["sonarr_search", "Search when added", "bool"],
  ] },
  { title: "General", fields: [
    ["default_schedule", "Default schedule (cron)", "text", "0 */6 * * *"],
    ["arr_max_requests", "Most titles sent to Radarr/Sonarr per collection sync (0 = no limit)", "text", "25"],
    ["managed_label", "Label added to managed collections", "text", "Curatarr"],
  ] },
];

function settingField([key, label, type, extra], values, fromEnv) {
  const env = fromEnv.includes(key) ? ` <span class="badge">env</span>` : "";
  if (type === "bool") {
    return `<div><label class="check"><input type="checkbox" data-key="${key}" ${values[key] !== "false" ? "checked" : ""}> ${label}</label></div>`;
  }
  if (type === "select") {
    return `<div><label>${label}</label><select data-key="${key}">${Object.entries(extra).map(([k, v]) =>
      `<option value="${k}" ${values[key] === k ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></div>`;
  }
  return `<div><label>${label}${env}</label><input type="${type === "password" ? "password" : "text"}" data-key="${key}" value="${esc(values[key])}" placeholder="${esc(extra || "")}" autocomplete="off"></div>`;
}

async function settings() {
  const { values, from_env: fromEnv } = await api("GET", "/settings");
  view.innerHTML = `
    <div class="page-head"><h1>Settings</h1><div class="actions"><button class="primary" id="saveSettings">Save</button></div></div>
    <div class="card" id="plexCard"></div>
    ${SETTING_GROUPS.map((g) => `
      <div class="card">
        <h2>${g.title}</h2>
        ${g.hint ? `<p class="hint" style="margin-top:-6px">${g.hint}</p>` : ""}
        <div class="grid">${g.fields.map((f) => settingField(f, values, fromEnv)).join("")}</div>
        <div class="row" style="margin-top:12px">
          ${g.test ? `<button type="button" data-test="${g.test}">Test</button>` : ""}
          ${g.arr ? `<button type="button" data-arr="${g.arr}">Load folders &amp; profiles</button>` : ""}
          ${g.extra || ""}
        </div>
        ${g.arr ? `<div id="${g.arr}-options" class="small muted" style="margin-top:8px"></div>` : ""}
      </div>`).join("")}
    <p class="hint">Values marked <span class="badge">env</span> come from container environment variables; saving a value here overrides them.</p>`;

  const gather = () => {
    const out = {};
    view.querySelectorAll("[data-key]").forEach((el) => {
      out[el.dataset.key] = el.type === "checkbox" ? String(el.checked) : el.value;
    });
    return out;
  };
  const saveAll = async () => {
    await api("PUT", "/settings", gather());
    state.libraries = null;
  };

  view.querySelector("#saveSettings").onclick = () => guard(async () => {
    await saveAll();
    toast("Settings saved");
    loadStatus();
  });
  view.querySelectorAll("[data-test]").forEach((b) => b.onclick = () => guard(async () => {
    await saveAll();
    b.disabled = true;
    try {
      const r = await api("POST", `/settings/test/${b.dataset.test}`);
      toast(r.message, !r.ok);
      if (b.dataset.test === "plex") loadStatus();
    } finally { b.disabled = false; }
  }));
  view.querySelectorAll("[data-arr]").forEach((b) => b.onclick = () => guard(async () => {
    await saveAll();
    const kind = b.dataset.arr;
    const r = await api("GET", `/arr/${kind}/options`);
    const out = view.querySelector(`#${kind}-options`);
    out.innerHTML = `Root folders: ${r.root_folders.map((f) => `<a href="#" data-fill="${kind}_root_folder" data-val="${esc(f)}">${esc(f)}</a>`).join(", ") || "none"}<br>
      Quality profiles: ${r.quality_profiles.map((p) => `<a href="#" data-fill="${kind}_quality_profile" data-val="${p.id}">${esc(p.name)} (${p.id})</a>`).join(", ")}`;
    out.querySelectorAll("[data-fill]").forEach((a) => a.onclick = (e) => {
      e.preventDefault();
      view.querySelector(`[data-key="${a.dataset.fill}"]`).value = a.dataset.val;
    });
  }));

  await plexCard(view.querySelector("#plexCard"), values);
}

// The Plex card is kept apart from the other settings: once connected it is a
// read-only summary, and changes go through "Change server" or "Disconnect".
async function plexCard(card, values, editing = false) {
  const connected = Boolean(values.plex_url && values.plex_token);
  if (connected && !editing) {
    card.innerHTML = `<h2>Plex</h2><p class="muted">Checking connection…</p>`;
    const status = await api("GET", "/status").catch((err) => ({ plex_error: err.message }));
    const ok = Boolean(status.plex);
    card.innerHTML = `
      <div class="row" style="align-items:center;margin-bottom:12px">
        <h2 style="margin:0">Plex</h2>
        <span class="badge ${ok ? "success" : "error"}">${ok ? "Connected" : "Not reachable"}</span>
      </div>
      <dl class="facts">
        ${ok ? `<dt>Server</dt><dd>${esc(status.plex.name)} <span class="muted">· Plex ${esc(status.plex.version)}</span></dd>` : ""}
        <dt>Address</dt><dd class="mono">${esc(values.plex_url)}</dd>
        <dt>Token</dt><dd class="muted">Saved</dd>
        ${ok ? "" : `<dt>Error</dt><dd class="no">${esc(status.plex_error || "Unknown error")}</dd>`}
      </dl>
      <div class="row" style="margin-top:14px">
        <button type="button" id="plexTest">Test connection</button>
        <button type="button" id="plexChange">Change server</button>
        <button type="button" class="danger" id="plexDisconnect">Disconnect</button>
      </div>`;
    card.querySelector("#plexTest").onclick = () => guard(async () => {
      const r = await api("POST", "/settings/test/plex");
      toast(r.message, !r.ok);
      loadStatus();
    });
    card.querySelector("#plexChange").onclick = () => plexCard(card, values, true);
    card.querySelector("#plexDisconnect").onclick = () => guard(async () => {
      if (!confirm("Disconnect Curatarr from Plex? Collections will stop syncing until you connect again.")) return;
      await api("PUT", "/settings", { plex_url: "", plex_token: "" });
      Object.assign(values, { plex_url: "", plex_token: "" });
      state.libraries = null;
      loadStatus();
      plexCard(card, values);
    });
    return;
  }

  card.innerHTML = `
    <h2>Plex</h2>
    <p class="hint" style="margin-top:-6px">Sign in with your Plex account, then choose the server address Curatarr should use.</p>
    <div class="row">
      <button type="button" class="primary" id="plexSignIn">Sign in with Plex</button>
      ${connected ? `<button type="button" id="plexCancel">Cancel</button>` : ""}
    </div>
    <div id="plexServers" class="servers"></div>
    <details style="margin-top:14px">
      <summary>Enter the address and token manually</summary>
      <div class="grid" style="margin-top:10px">
        <div><label>Server URL</label><input type="text" data-plex="plex_url" placeholder="http://192.168.1.10:32400" autocomplete="off"></div>
        <div><label>Token</label><input type="password" data-plex="plex_token" placeholder="X-Plex-Token" autocomplete="off"></div>
        <div><label class="check"><input type="checkbox" data-plex="plex_verify_ssl" ${values.plex_verify_ssl !== "false" ? "checked" : ""}> Verify SSL certificates</label></div>
      </div>
      <button type="button" id="plexManual" style="margin-top:10px">Save &amp; connect</button>
    </details>`;

  const connect = async (url, token, verify) => {
    const update = { plex_url: url, plex_token: token };
    if (verify !== undefined) update.plex_verify_ssl = String(verify);
    await api("PUT", "/settings", update);
    const r = await api("POST", "/settings/test/plex");
    if (!r.ok) {
      toast(`Saved, but Plex could not be reached at that address: ${r.message}`, true);
    } else {
      toast(r.message);
    }
    Object.assign(values, { plex_url: url, plex_token: token });
    state.libraries = null;
    loadStatus();
    plexCard(card, values);
  };

  card.querySelector("#plexCancel")?.addEventListener("click", () => plexCard(card, values));
  card.querySelector("#plexManual").onclick = () => guard(async () => {
    const url = card.querySelector('[data-plex="plex_url"]').value.trim();
    const token = card.querySelector('[data-plex="plex_token"]').value.trim();
    if (!url || !token) return toast("Enter both the server URL and the token", true);
    await connect(url, token, card.querySelector('[data-plex="plex_verify_ssl"]').checked);
  });

  card.querySelector("#plexSignIn").onclick = () => guard(async () => {
    const pin = await api("POST", "/plex/auth/pin");
    const popup = window.open(pin.auth_url, "plexauth", "width=600,height=750");
    toast("Complete the sign-in in the Plex window…");
    const started = Date.now();
    const poll = async () => {
      if (Date.now() - started > 5 * 60 * 1000) return toast("Plex sign-in timed out", true);
      const r = await api("GET", `/plex/auth/pin/${pin.id}`);
      if (!r.authorized) return setTimeout(poll, 2000);
      popup?.close();
      showServers(r.servers, r.token);
    };
    setTimeout(poll, 2000);
  });

  function showServers(servers, token) {
    const el = card.querySelector("#plexServers");
    if (!servers.length) {
      card.querySelector('[data-plex="plex_token"]').value = token;
      card.querySelector("details").open = true;
      el.innerHTML = `<span class="muted">Signed in, but no servers were found. Enter the server address below.</span>`;
      return;
    }
    el.innerHTML = `<span class="muted small">Signed in. Choose the address Curatarr should use (local addresses are fastest):</span>` +
      servers.map((s, i) => `
        <div class="server-pick">
          <strong>${esc(s.name)}</strong>
          ${s.connections.map((c, j) => `
            <button type="button" class="small" data-srv="${i}" data-conn="${j}">
              <span class="mono">${esc(c.uri)}</span>${c.local ? ` <span class="badge success">local</span>` : ` <span class="badge">remote</span>`}
            </button>`).join("")}
        </div>`).join("");
    el.querySelectorAll("[data-srv]").forEach((b) => b.onclick = () => guard(async () => {
      el.querySelectorAll("button").forEach((x) => { x.disabled = true; });
      const s = servers[Number(b.dataset.srv)];
      await connect(s.connections[Number(b.dataset.conn)].uri, s.token);
    }));
  }
}

// ---------- import / export ----------

const SAMPLE_YAML = `collections:
  - name: IMDb Top 250
    library: Movies
    sources:
      - type: imdb_chart
        value: top
    sort_title: "!01 IMDb Top 250"
    promote_home: true
  - name: Marvel Cinematic Universe
    library: Movies
    sources:
      - type: tmdb_list
        value: https://www.themoviedb.org/list/8136
    order: release
  - name: Trending Shows
    library: TV Shows
    sources:
      - type: trakt_chart
        value: shows/trending
        limit: 30
    schedule: "0 */12 * * *"`;

async function importExport() {
  view.innerHTML = `
    <div class="page-head"><h1>Import / Export</h1></div>
    <div class="card">
      <h2>Export</h2>
      <p class="muted">Download every collection as YAML to back it up or move it to another server.</p>
      <a class="btn" href="/api/export" download>Download collections.yml</a>
    </div>
    <div class="card">
      <h2>Import</h2>
      <p class="muted small">Collections are matched by name and library: existing ones are updated, new ones are created.
        A <code>collections.yml</code> placed in the config folder is also imported (new names only) when the container starts.</p>
      <textarea id="yaml" style="min-height:280px;font-family:ui-monospace,monospace" spellcheck="false" placeholder="${esc(SAMPLE_YAML)}"></textarea>
      <div class="row" style="margin-top:10px">
        <input type="file" id="yamlFile" accept=".yml,.yaml,text/yaml" style="max-width:280px">
        <label class="check"><input type="checkbox" id="overwrite" checked> Update existing collections</label>
        <button class="primary" id="doImport">Import</button>
      </div>
      <details style="margin-top:14px"><summary>Example</summary><pre>${esc(SAMPLE_YAML)}</pre></details>
    </div>`;
  view.querySelector("#yamlFile").onchange = async (e) => {
    const f = e.target.files[0];
    if (f) view.querySelector("#yaml").value = await f.text();
  };
  view.querySelector("#doImport").onclick = () => guard(async () => {
    const text = view.querySelector("#yaml").value;
    if (!text.trim()) return toast("Paste or choose a YAML file first", true);
    const r = await api("POST", `/import?overwrite=${view.querySelector("#overwrite").checked}`, text);
    toast(`Created ${r.created}, updated ${r.updated}${r.errors.length ? `, ${r.errors.length} error(s)` : ""}`, r.errors.length > 0);
    r.errors.forEach((e) => toast(e, true));
  });
}

// ---------- boot ----------

loadStatus();
route();
