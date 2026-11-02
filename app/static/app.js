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
  // Saving or starting something may start background work: check on it soon.
  if (method !== "GET" && !path.startsWith("/overlays/progress")) watchActivity();
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

// ---------- background activity ----------
// Poster overlays are drawn in the background after syncs. The top bar shows
// their progress, and the page refreshes when they finish so new posters appear.

const activity = { running: false, overlays: false, timer: null };

async function pollActivity() {
  clearTimeout(activity.timer);
  let p = null;
  try { p = await api("GET", "/overlays/progress"); } catch { /* try again later */ }
  const el = document.getElementById("activity");
  const overlaysRunning = Boolean(p && (p.running || p.queued));
  const syncing = p?.syncing || [];
  const napalm = p?.napalm?.running ? p.napalm : null;
  const running = overlaysRunning || syncing.length > 0 || Boolean(napalm);
  el.hidden = !running;
  const stop = document.getElementById("napalmStop");
  if (stop) stop.hidden = !napalm;
  if (napalm) {
    el.innerHTML = `<span class="spinner"></span>${napalm.stopping ? "Stopping the poster refresh" : "Refreshing posters"}`
      + `${napalm.total ? ` · ${napalm.done} / ${napalm.total}` : "…"}`;
    el.title = `${napalm.changed} changed, ${napalm.unchanged} already fresh, ${napalm.errors} failed`;
  } else if (overlaysRunning) {
    el.innerHTML = `<span class="spinner"></span>${esc(p.phase || "Poster overlays")}${p.total ? ` · ${p.done} / ${p.total}` : "…"}`;
    el.title = p.drawn ? `${p.drawn} poster(s) drawn so far` : "";
  } else if (syncing.length) {
    el.innerHTML = `<span class="spinner"></span>Syncing ${esc(syncing.length === 1 ? syncing[0] : `${syncing.length} collections`)}…`;
    el.title = syncing.join(", ");
  }
  // A refresh we started (even one too quick to be seen running) reports when it's done.
  if ((activity.napalm || activity.napalmStarted) && !napalm && p?.napalm?.finished
      && Date.parse(p.napalm.finished) >= (activity.napalmStarted || 0) - 5000) {
    activity.napalmStarted = 0;
    const n = p.napalm;
    toast(`Poster refresh done: ${n.changed} changed, ${n.unchanged} already fresh, ${n.no_poster} without a source poster`
      + (n.kept ? `, ${n.kept} kept (Keep Poster label)` : "")
      + (n.errors ? `, ${n.errors} failed (see Logs)` : "")
      + (n.overlays_off?.length ? `. Poster overlays turned off on: ${n.overlays_off.map((c) => c.name).join(", ")}` : ""),
      Boolean(n.errors));
    napalmLastRun(document.getElementById("napalmLast"));
  }
  activity.napalm = Boolean(napalm);
  if (activity.overlays && !overlaysRunning && p) {
    toast(p.errors ? `Poster overlays finished with ${p.errors} problem(s); see Logs` : "Poster overlays are up to date",
      Boolean(p.errors));
    if (/^#\/(collections\/\d+\/items|dashboard)/.test(location.hash)) route();
  }
  activity.running = running;
  activity.overlays = overlaysRunning;
  activity.timer = setTimeout(pollActivity, running ? 2000 : 15000);
}

function watchActivity() {
  clearTimeout(activity.timer);
  activity.timer = setTimeout(pollActivity, 1500);
}

// ---------- router ----------

const routes = [
  [/^#\/collections\/new(?:\?(.*))?$/, (m) => editor(null, new URLSearchParams(m[1] || ""))],
  [/^#\/collections\/(\d+)$/, (m) => editor(Number(m[1]))],
  [/^#\/collections\/(\d+)\/items$/, (m) => collectionItems({ id: Number(m[1]) })],
  [/^#\/plex\/(\d+)(?:\?(.*))?$/, (m) => collectionItems({ ratingKey: m[1], params: new URLSearchParams(m[2] || "") })],
  [/^#\/plex-playlist\/(\d+)(?:\?(.*))?$/, (m) => collectionItems({ ratingKey: m[1], playlist: true, params: new URLSearchParams(m[2] || "") })],
  [/^#\/playlists$/, playlistsPage],
  [/^#\/history$/, history],
  [/^#\/logs$/, logsPage],
  [/^#\/settings$/, settings],
  [/^#\/import$/, importExport],
  [/^#\/movies$/, () => collections("movie")],
  [/^#\/tv$/, () => collections("show")],
  [/^#\/holidays$/, holidaysPage],
  [/^#\/packs\/(movie|show)$/, (m) => packsPage(m[1])],
  [/^#\/dashboard$/, dashboardPage],
  [/^#\/unmatched$/, () => unmatchedPage()],
  [/^#\/prerolls$/, prerollsPage],
  [/^#\/overlays$/, overlaysPage],
  [/^#\/napalm$/, napalmPage],
  [/^#\/collections$/, () => location.replace("#/movies")],   // the old single Collections page
  [/^.*$/, () => location.replace("#/dashboard")],
];

let refreshTimer = null;

async function route() {
  clearInterval(refreshTimer);
  const hash = location.hash || "#/dashboard";
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
    state.machineId = s.plex?.machine_id || "";
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

// A Curatarr collection or playlist card, with Sync now / View / Edit / Delete.
function collectionCard(r) {
  const cfg = r.config;
  const poster = cfg.poster_file
    ? `<img class="poster" src="/api/collections/${r.id}/image/poster?v=${encodeURIComponent(r.poster_applied || cfg.poster_file)}" alt="">`
    : (cfg.poster_url ? `<img class="poster" src="${esc(cfg.poster_url)}" alt="" referrerpolicy="no-referrer">` : `<div class="poster">▦</div>`);
  const where = cfg.kind === "playlist" && cfg.libraries?.length ? cfg.libraries.join(" + ") : cfg.library;
  return `
    <div class="coll${cfg.enabled ? "" : " disabled"}">
      ${poster}
      <div class="coll-body">
        <a class="coll-title" href="#/collections/${r.id}/items" title="View ${esc(cfg.name)}">${esc(cfg.name)}</a>
        <div class="small muted">${esc(where || "?")} · ${esc(sourceSummary(cfg))}</div>
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
}

async function collections(kind) {
  await catalog();
  const [allRows, libs] = await Promise.all([
    api("GET", "/collections"),
    libraries().catch(() => null),
  ]);
  // Without Plex the library types are unknown, so show everything rather than hide collections.
  // Holiday collections live on the Holidays page, playlists on the Playlists page.
  const regular = allRows.filter((r) => !r.config.holiday && r.config.kind !== "playlist");
  const rows = libs ? regular.filter((r) => collectionKind(r.config, libs) === kind) : regular;
  const meta = KINDS[kind];
  const cards = rows.map(collectionCard).join("");

  view.innerHTML = `
    <div class="page-head">
      <h1>${meta.title}</h1>
      <div class="actions">
        ${rows.length ? `<button id="runAll">Sync all</button>` : ""}
        <a class="btn" href="#/packs/${kind}">Starter packs</a>
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
  bindCardActions("collection");
  if (rows.some((r) => r.running)) refreshTimer = setInterval(route, 4000);
}

function bindCardActions(noun) {
  view.querySelectorAll("[data-run]").forEach((b) => b.onclick = () => guard(async () => {
    b.disabled = true;
    await api("POST", `/collections/${b.dataset.run}/run`);
    toast("Sync started");
    setTimeout(route, 1500);
  }));
  view.querySelectorAll("[data-del]").forEach((b) => b.onclick = () => guard(async () => {
    if (!confirm(`Delete "${b.dataset.name}" from Curatarr?`)) return;
    const fromPlex = confirm(`Also delete the ${noun} from Plex?\n\nOK = delete it in Plex too, Cancel = keep it in Plex.`);
    const r = await api("DELETE", `/collections/${b.dataset.del}?remove_from_plex=${fromPlex}`);
    toast(r.message || `${noun[0].toUpperCase()}${noun.slice(1)} deleted`, !!r.message);
    route();
  }));
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

// ---------- playlists ----------

async function playlistsPage() {
  await catalog();
  const rows = (await api("GET", "/collections")).filter((r) => r.config.kind === "playlist");
  view.innerHTML = `
    <div class="page-head">
      <h1>Playlists</h1>
      <div class="actions">
        ${rows.length ? `<button id="runAll">Sync all</button>` : ""}
        <a class="btn primary" href="#/collections/new?kind=playlist">+ New playlist</a>
      </div>
    </div>
    <p class="hint" style="margin-top:-8px">Playlists play in list order, which suits watch orders such as the MCU.
      They can mix movies and TV shows, and a show brings all of its episodes. Playlists belong to the Plex account Curatarr signed in with.</p>
    ${rows.length ? `<div class="collections">${rows.map(collectionCard).join("")}</div>` : `
      <div class="card empty">
        <p>No playlists yet.</p>
        <p class="small">Create one from a TMDB, Trakt, MDBList or IMDb list, or use <strong>Sync with a list</strong> on one of your existing Plex playlists below.</p>
        <a class="btn primary" href="#/collections/new?kind=playlist">Create a playlist</a>
      </div>`}
    <section id="plexExisting" style="margin-top:32px"></section>`;
  bindCardActions("playlist");
  view.querySelector("#runAll")?.addEventListener("click", () => guard(async () => {
    const enabled = rows.filter((r) => r.config.enabled && !r.running);
    for (const r of enabled) await api("POST", `/collections/${r.id}/run`);
    toast(`Syncing ${enabled.length} playlist(s)`);
    setTimeout(route, 1500);
  }));
  if (rows.some((r) => r.running)) refreshTimer = setInterval(route, 4000);

  const el = view.querySelector("#plexExisting");
  let playlists;
  try {
    playlists = (await api("GET", "/plex/playlists")).filter((p) => !p.managed_id);
  } catch (err) {
    el.innerHTML = `<h2>Existing Plex playlists</h2><p class="muted small">Could not load playlists from Plex: ${esc(err.message)}</p>`;
    return;
  }
  if (!playlists.length) return;
  const viewLink = (p) => `#/plex-playlist/${p.ratingKey}?${esc(new URLSearchParams({ title: p.title, smart: p.smart ? "1" : "0" }))}`;
  el.innerHTML = `
    <details class="fold" data-fold="playlists.existing" ${foldOpen("playlists.existing", false) ? "open" : ""}>
    <summary class="fold-head"><h2>Existing Plex playlists</h2><span class="muted small">${playlists.length}</span></summary>
    <div class="collections" style="margin-top:10px">${playlists.map((p) => `
      <div class="coll existing">
        ${p.thumb ? `<img class="poster" loading="lazy" src="/api/plex/image?path=${encodeURIComponent(p.thumb)}" alt="">` : `<div class="poster">▦</div>`}
        <div class="coll-body">
          <a class="coll-title" href="${viewLink(p)}" title="View ${esc(p.title)}">${esc(p.title)}</a>
          <div class="small muted">${p.childCount} item${p.childCount === 1 ? "" : "s"}</div>
          ${p.smart ? `<div class="small"><span class="badge">smart</span> <span class="muted">Plex keeps this one updated itself</span></div>` : ""}
          <div class="coll-actions">
            <a class="btn small" style="padding:4px 10px;font-size:.8rem" href="${viewLink(p)}">View</a>
            ${p.smart ? "" : `<a class="btn small" style="padding:4px 10px;font-size:.8rem"
              href="#/collections/new?${esc(new URLSearchParams({ kind: "playlist", link: p.ratingKey, title: p.title, items: p.childCount }))}">Sync with a list</a>`}
          </div>
        </div>
      </div>`).join("")}
    </div></details>`;
  bindFolds(el);
}

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
async function collectionItems({ id = null, ratingKey = null, playlist = false, params = new URLSearchParams() }) {
  let row = null, title, library, back, inPlex = true, items, change = null;
  if (id) {
    const [r, contents, libs, last] = await Promise.all([
      api("GET", `/collections/${id}`),
      api("GET", `/collections/${id}/items`),
      libraries().catch(() => null),
      api("GET", `/collections/${id}/last-change`).catch(() => null),
    ]);
    row = r;
    change = last;
    ({ in_plex: inPlex, items } = contents);
    title = row.config.name;
    playlist = row.config.kind === "playlist";
    library = playlist && row.config.libraries?.length ? row.config.libraries.join(" + ") : row.config.library;
    back = row.config.holiday ? "#/holidays" : playlist ? "#/playlists"
      : (KINDS[libs && collectionKind(row.config, libs)] || KINDS.movie).hash;
  } else {
    items = await api("GET", `/plex/${playlist ? "playlists" : "collections"}/${ratingKey}/items`);
    title = params.get("title") || (playlist ? "Plex playlist" : "Plex collection");
    library = params.get("library") || "";
    back = playlist ? "#/playlists" : (KINDS[params.get("kind")] || KINDS.movie).hash;
  }
  // Keep the page the collection came from highlighted in the menu.
  document.querySelector(`[data-nav="${back.slice(2)}"]`)?.classList.add("active");

  const watched = items.filter((i) => i.watched).length;
  // Poster overlays on this collection: how many posters have them so far.
  const wantsOverlay = row && (row.config.ribbon?.enabled || row.config.badges?.quality || row.config.badges?.rating
    || row.config.badges?.content_rating || row.config.fresh_poster);
  const overlaid = items.filter((i) => i.overlay).length;
  const overlayLine = wantsOverlay && inPlex && items.length ? `<p class="small muted" style="margin-top:-8px">
    <span class="overlay-dot"></span>Poster overlays on <strong>${overlaid}</strong> of ${items.length} posters${overlaid < items.length
      ? " (the rest are drawn at the next sync; titles with nothing to show, such as no rating, are left alone)" : ""}.
    The posters below are the ones in Plex.</p>` : "";
  // Arranging by hand works for playlists and collections in list order.
  const canArrange = row && items.length > 1 && (playlist || row.config.order === "custom");
  const tile = (i) => `
    <div class="item" data-rk="${esc(i.ratingKey)}" data-search="${esc(`${i.title} ${i.year || ""}`.toLowerCase())}">
      <div class="item-poster">
        ${i.thumb ? `<img loading="lazy" src="/api/plex/image?path=${encodeURIComponent(i.thumb)}" alt="">` : "▦"}
        ${i.watched ? `<span class="item-watched" title="Watched">✔</span>` : ""}
        ${row ? `<button type="button" class="item-exclude" data-exclude="${esc(i.ratingKey)}" data-title="${esc(i.title)}"
          title="Remove and keep out of this collection">✕</button>` : ""}
      </div>
      <div class="item-title" title="${esc(i.title)}">${i.overlay ? `<span class="overlay-dot" title="Has a Curatarr poster overlay"></span>` : ""}${esc(i.title)}</div>
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
          href="#/collections/new?${esc(new URLSearchParams(playlist ? { kind: "playlist", link: ratingKey, title, items: items.length }
            : { link: ratingKey, section: params.get("section") || "", title, items: items.length }))}">Sync with a list</a>` : ""}
      </div>
    </div>
    ${row?.last_message ? `<p class="small muted" style="margin-top:-8px">${badge(row.last_status)} ${esc(row.last_message)}</p>` : ""}
    ${row && !row.config.enabled ? `<div class="notice">Syncing is paused for this collection.
      <button type="button" class="small" id="resume" style="margin-left:8px">Resume syncing</button></div>` : ""}
    ${change ? `<div class="notice small">
      Last change ${esc(when(change.finished || change.started))}${change.trigger === "undo" ? " (an undo)" : ""}:
      <strong>+${change.added_items.length}</strong> / <strong>−${change.removed_items.length}</strong>
      <a href="#/history">details</a>
      <button type="button" class="small" id="undo" style="margin-left:8px">${change.trigger === "undo" ? "Redo" : "Undo"} this change</button>
    </div>` : ""}
    ${overlayLine}
    <div id="missingOut"></div>
    ${inPlex ? `
      <div class="row" style="margin-bottom:16px">
        <div class="grow"><input type="text" id="itemFilter" placeholder="Filter ${items.length} title${items.length === 1 ? "" : "s"}…"></div>
        <span class="small muted" id="itemCount">${items.length} in Plex · ${watched} watched</span>
        ${canArrange ? `<button type="button" id="arrange">Arrange order</button>
          <span class="arrange-tools" hidden>
            <button type="button" class="primary" id="saveOrder">Save order</button>
            <button type="button" id="cancelOrder">Cancel</button>
          </span>
          ${row.config.manual_order?.length ? `<button type="button" class="small" id="resetOrder" title="Go back to the order of the lists">Reset to list order</button>` : ""}` : ""}
      </div>
      <p class="hint arrange-tools" hidden style="margin-top:-8px">Drag titles into the order you want, then click <strong>Save order</strong>.
        New titles from your lists are added at the end.</p>
      ${items.length ? `<div class="items">${items.map(tile).join("")}</div>` : `<div class="card empty">This ${playlist ? "playlist" : "collection"} is empty in Plex.</div>`}`
    : `<div class="notice">
        This ${playlist ? "playlist" : "collection"} isn't in Plex right now.
        ${row?.config.seasonal_only ? "It's only in Plex during its dates." : "It's created in Plex on its next sync."}
        Below are the titles from your library it will have.
      </div>
      <div id="planned"><p class="muted">Fetching lists and matching against Plex…</p></div>`}`;
  if (!inPlex && row) loadPlanned(row, tile);

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
  view.querySelector("#resume")?.addEventListener("click", () => guard(async () => {
    await api("PUT", `/collections/${row.id}`, { ...row.config, enabled: true });
    toast("Syncing resumed");
    route();
  }));
  view.querySelector("#undo")?.addEventListener("click", () => guard(async () => {
    const verb = change.trigger === "undo" ? "Redo" : "Undo";
    if (!confirm(`${verb} the last change to "${title}"?\n\nTakes out ${change.added_items.length} title(s) and puts back `
      + `${change.removed_items.length}. Syncing is paused afterwards so the next scheduled sync doesn't redo it.`)) return;
    const r = await api("POST", `/collections/${row.id}/undo`);
    toast(r.message);
    route();
  }));
  bindArrange(row);
  view.querySelectorAll("[data-exclude]").forEach((b) => b.onclick = () => guard(async () => {
    if (!confirm(`Remove "${b.dataset.title}" from this collection and keep it out?\n\nYou can allow it again in the collection's settings.`)) return;
    await api("POST", `/collections/${row.id}/exclude`, { id: `plex:${b.dataset.exclude}`, title: b.dataset.title });
    b.closest(".item").remove();
    toast(`Excluded "${b.dataset.title}"`);
  }));
  // Titles from the lists that aren't in the Plex library (fetched on demand: lists can be slow).
  view.querySelector("#showMissing").onclick = (e) => guard(async () => {
    const out = view.querySelector("#missingOut");
    e.target.disabled = true;
    out.innerHTML = `<p class="muted">Fetching lists and matching against Plex…</p>`;
    try {
      const cfg = row.config;
      const r = await api("POST", "/preview", { section_id: cfg.section_id, library: cfg.library, section_ids: cfg.section_ids || [], sources: cfg.sources, item_limit: cfg.item_limit });
      const missing = r.items.filter((i) => !i.in_plex);
      const service = (i) => ((r.library.type || i.media_type) === "show" ? "Sonarr" : "Radarr");
      out.innerHTML = `
        <details class="card" open>
          <summary><strong>${missing.length}</strong> of ${r.total} list titles aren't in ${esc(r.library.title)}</summary>
          ${r.errors.map((err) => `<p class="no small">${esc(err)}</p>`).join("")}
          ${missing.length ? `<div class="table-wrap" style="max-height:320px;overflow:auto;margin-top:10px"><table>
            <thead><tr><th>Title</th><th>Year</th><th>IDs</th><th></th></tr></thead>
            <tbody>${missing.map((i, n) => `<tr><td>${esc(i.title || "—")}</td><td>${esc(i.year || "")}</td>
              <td class="small muted">${[i.imdb, i.tmdb && `tmdb:${i.tmdb}`, i.tvdb && `tvdb:${i.tvdb}`].filter(Boolean).map(esc).join(" · ")}</td>
              <td><button type="button" class="small" data-request="${n}">Add to ${service(i)}</button></td></tr>`).join("")}
            </tbody></table></div>` : ""}
        </details>`;
      // Mark titles Radarr/Sonarr already has (one library check per service).
      if (missing.length) {
        api("POST", "/arr/have", { items: missing.map((i) => ({ ...i, media_type: r.library.type || i.media_type })) })
          .then(({ have }) => have.forEach((yes, n) => {
            if (!yes) return;
            const b = out.querySelector(`[data-request="${n}"]`);
            if (b) b.outerHTML = `<span class="badge success" title="Waiting for ${service(missing[n])} to download it">In ${service(missing[n])}</span>`;
          }))
          .catch(() => {});        // the buttons still work without the status
      }
      out.querySelectorAll("[data-request]").forEach((b) => b.onclick = () => guard(async () => {
        b.disabled = true;
        try {
          const item = missing[Number(b.dataset.request)];
          const res = await api("POST", `/collections/${row.id}/request`, { ...item, media_type: r.library.type || item.media_type });
          b.textContent = res.status === "added" ? "Added ✓" : `Already in ${service(item)}`;
        } catch (err) {
          b.disabled = false;
          throw err;
        }
      }));
    } catch (err) {
      out.innerHTML = `<p class="no">${esc(err.message)}</p>`;
    } finally {
      e.target.disabled = false;
    }
  });
}

// The titles an off-season (or not yet created) collection will have.
async function loadPlanned(row, tile) {
  const el = view.querySelector("#planned");
  try {
    const p = await api("GET", `/collections/${row.id}/planned`);
    el.innerHTML = `
      ${p.errors.map((e) => `<p class="no small">${esc(e)}</p>`).join("")}
      <p class="small muted">${p.items.length} title${p.items.length === 1 ? "" : "s"} from your library${p.missing
        ? `, plus ${p.missing} not in your library (see <strong>Show missing titles</strong>)` : ""}.</p>
      ${p.items.length ? `<div class="items">${p.items.map(tile).join("")}</div>` : `<div class="card empty">None of its titles are in your library yet.</div>`}`;
    el.querySelectorAll("[data-exclude]").forEach((b) => b.onclick = () => guard(async () => {
      if (!confirm(`Keep "${b.dataset.title}" out of this collection?

You can allow it again in the collection's settings.`)) return;
      await api("POST", `/collections/${row.id}/exclude`, { id: `plex:${b.dataset.exclude}`, title: b.dataset.title });
      b.closest(".item").remove();
      toast(`Excluded "${b.dataset.title}"`);
    }));
  } catch (err) {
    el.innerHTML = `<p class="no">${esc(err.message)}</p>`;
  }
}

// Drag-and-drop ordering on the View page.
function bindArrange(row) {
  const grid = view.querySelector(".items");
  const start = view.querySelector("#arrange");
  if (!grid || !start) return;
  let dragged = null;
  const setMode = (on) => {
    grid.classList.toggle("arranging", on);
    grid.querySelectorAll(".item").forEach((el) => { el.draggable = on; el.hidden = false; });
    view.querySelectorAll(".arrange-tools").forEach((el) => { el.hidden = !on; });
    start.hidden = on;
    const filter = view.querySelector("#itemFilter");
    filter.disabled = on;
    if (on) filter.value = "";
  };
  start.onclick = () => setMode(true);
  view.querySelector("#cancelOrder").onclick = () => route();
  grid.addEventListener("dragstart", (e) => {
    dragged = e.target.closest(".item");
    dragged?.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
  });
  grid.addEventListener("dragend", () => { dragged?.classList.remove("dragging"); dragged = null; });
  grid.addEventListener("dragover", (e) => {
    if (!dragged) return;
    e.preventDefault();
    const over = e.target.closest(".item");
    if (!over || over === dragged) return;
    const box = over.getBoundingClientRect();
    over.parentNode.insertBefore(dragged, e.clientX > box.left + box.width / 2 ? over.nextSibling : over);
  });
  view.querySelector("#saveOrder").onclick = () => guard(async () => {
    const order = [...grid.querySelectorAll(".item")].map((el) => el.dataset.rk);
    await api("POST", `/collections/${row.id}/order`, { order });
    toast("Order saved");
    route();
  });
  view.querySelector("#resetOrder")?.addEventListener("click", () => guard(async () => {
    if (!confirm("Go back to the order of the lists? A sync starts to put it right.")) return;
    await api("POST", `/collections/${row.id}/order`, { order: [] });
    toast("Back to list order; syncing");
    route();
  }));
}

// ---------- dashboard ----------

async function dashboardPage() {
  const d = await api("GET", "/dashboard");
  const c = d.counts;
  const link = (x) => x.kind === "holidays" ? "#/holidays" : `#/collections/${x.id}/items`;
  const day = (iso) => {
    const [y, m, dd] = iso.split("-").map(Number);
    return new Date(y, m - 1, dd).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  };
  const stat = (value, label, id = "") => `<div class="stat"${id ? ` id="${id}"` : ""}><div class="stat-value">${value}</div><div class="stat-label">${label}</div></div>`;
  view.innerHTML = `
    <div class="page-head"><h1>Dashboard</h1></div>
    <div class="stats">
      ${stat(c.collections, "Collections")}
      ${stat(c.playlists, "Playlists")}
      ${stat(c.holidays, "Holiday collections")}
      ${stat(c.titles.toLocaleString(), "Titles in Plex")}
      ${stat(c.missing.toLocaleString(), "Missing from Plex")}
      ${stat("…", "Watched", "watchedStat")}
    </div>
    <div class="dash">
      <div class="card"><h2>Needs attention</h2>
        ${d.attention.length ? `<ul class="dash-list">${d.attention.map((a) => `
          <li><a href="${link(a)}">${esc(a.name)}</a> ${badge(a.status)}
            <div class="small muted" title="${esc(a.message)}">${esc(a.message || (a.status === "paused" ? "Syncing is paused" : ""))}</div></li>`).join("")}</ul>`
          : `<p class="muted small">Everything synced fine.</p>`}</div>
      <div class="card"><h2>Coming up</h2>
        ${d.coming.length ? `<ul class="dash-list">${d.coming.map((x) => `
          <li><strong>${esc(windowText({ promote_start: x.start, promote_end: x.end, promote_yearly: false }).replace(/, \d{4}/g, ""))}</strong>
            · <a href="${link(x)}">${esc(x.name)}</a>${x.library ? ` <span class="small muted">(${esc(x.library)})</span>` : ""}
            <div class="small muted">${x.appears
              ? `Starts ${esc(day(x.date))}: ${x.seasonal ? "added to Plex and shown on the home screen" : "shown on the home screen"}`
              : `Showing now until ${esc(day(x.date))}${x.seasonal ? ", then removed from Plex" : ""}`}</div></li>`).join("")}</ul>`
          : `<p class="muted small">No calendar changes coming up.</p>`}</div>
      <div class="card"><h2>Most missing</h2>
        ${d.most_missing.length ? `<ul class="dash-list">${d.most_missing.map((m) => `
          <li><a href="${link(m)}">${esc(m.name)}</a>
            <div class="small muted">${m.missing} missing · ${m.matched} in Plex</div></li>`).join("")}</ul>`
          : `<p class="muted small">Nothing is missing.</p>`}</div>
      <div class="card"><h2>Recent syncs</h2>
        ${d.recent.length ? `<ul class="dash-list">${d.recent.map((r) => `
          <li><a href="#/collections/${r.collection_id}/items">${esc(r.collection_name)}</a> ${badge(r.status)}
            <div class="small muted">${esc(when(r.finished || r.started))} · +${r.added} / −${r.removed}${r.missing ? ` · ${r.missing} missing` : ""}</div></li>`).join("")}</ul>
          <p class="small"><a href="#/history">All history</a></p>`
          : `<p class="muted small">No syncs yet.</p>`}</div>
    </div>`;
  try {
    const w = await api("GET", "/dashboard/watched");
    const el = view.querySelector("#watchedStat .stat-value");
    if (el) el.textContent = w.total ? `${Math.round((w.watched / w.total) * 100)}%` : "—";
    view.querySelector("#watchedStat")?.setAttribute("title", `${w.watched} of ${w.total} titles`);
  } catch {
    const el = view.querySelector("#watchedStat .stat-value");
    if (el) el.textContent = "—";
  }
}

// ---------- unmatched titles ----------
// Titles not tied to IMDb, TMDB or TVDB (fan edits and the like), to check and protect.

const UNMATCHED_KINDS = {
  unmatched: ["Not matched", "Plex has no metadata match for it. Its poster is the one you uploaded or that's in its folder."],
  no_ids: ["No IMDb/TMDB IDs", "Matched in Plex, but not to an IMDb, TMDB or TVDB entry. If it's a fan edit matched to the wrong title, fix the match in Plex or keep its poster."],
  fan_edit: ["Fan edit", "Labelled Fan Edit in Plex."],
};

async function unmatchedPage(refresh = false) {
  view.innerHTML = `<div class="page-head"><h1>Unmatched and Fan Edits</h1></div><p class="muted">Scanning your libraries…</p>`;
  const r = await api("GET", `/unmatched${refresh ? "?refresh=true" : ""}`);
  const f = state.unmatchedFilter ||= { library: "", kind: "", keep: "", q: "" };
  const plexLink = (t) => state.machineId
    ? `https://app.plex.tv/desktop/#!/server/${encodeURIComponent(state.machineId)}/details?key=${encodeURIComponent(`/library/metadata/${t.ratingKey}`)}`
    : "";
  const shown = () => r.titles.filter((t) => (!f.library || t.section_id === f.library)
    && (!f.kind || (f.kind === "fan_edit" ? t.fan_edit : t.kind === f.kind))
    && (!f.keep || String(t.keep) === f.keep)
    && (!f.q || `${t.title} ${t.year || ""} ${t.file}`.toLowerCase().includes(f.q.toLowerCase())));
  const tile = (t) => `
    <div class="item" data-rk="${esc(t.ratingKey)}">
      <div class="item-poster">
        ${t.thumb ? `<img loading="lazy" src="/api/plex/image?path=${encodeURIComponent(t.thumb)}" alt="">` : "▦"}
        ${t.keep ? `<span class="keep-flag" title="Curatarr Keep Poster: napalm and fresh posters leave it alone">🔒</span>` : ""}
      </div>
      <div class="item-title" title="${esc(t.title)}">${esc(t.title)}</div>
      <div class="small muted">${esc(t.year || "")}${t.year ? " · " : ""}${esc(t.library)}</div>
      <div class="small">${UNMATCHED_KINDS[t.kind] ? `<span class="badge ${t.kind === "unmatched" ? "warning" : ""}" title="${esc(UNMATCHED_KINDS[t.kind][1])}">${esc(UNMATCHED_KINDS[t.kind][0])}</span>` : ""}
        ${t.fan_edit ? `<span class="badge running" title="${esc(UNMATCHED_KINDS.fan_edit[1])}">Fan edit</span>` : ""}</div>
      ${t.file ? `<div class="small muted unmatched-file" title="${esc(t.file)}">${esc(t.file)}</div>` : ""}
      <div class="coll-actions">
        <button type="button" class="small" data-upload="${esc(t.ratingKey)}">Upload poster</button>
        <button type="button" class="small" data-keep="${esc(t.ratingKey)}">${t.keep ? "Unlock poster" : "Keep poster"}</button>
        ${plexLink(t) ? `<a class="btn small" href="${esc(plexLink(t))}" target="_blank" rel="noopener" style="padding:4px 10px;font-size:.8rem">Open in Plex</a>` : ""}
      </div>
    </div>`;
  const render = () => {
    const list = shown();
    const counts = (kind) => r.titles.filter((t) => (kind === "fan_edit" ? t.fan_edit : t.kind === kind)).length;
    view.innerHTML = `
      <div class="page-head"><h1>Unmatched and Fan Edits</h1>
        <div class="actions"><button id="umRescan">Scan again</button></div></div>
      <p class="hint" style="margin-top:-8px">Movies and shows not tied to IMDb, TMDB or TVDB, plus titles labelled
        <strong>Fan Edit</strong> (or FanEdit) in Plex.
        <strong>Keep poster</strong> adds the Plex label <span class="mono">Curatarr Keep Poster</span>: napalm and the fresh-poster
        option never change that title's poster (ribbons and badges are still drawn on it).
        <strong>Open in Plex</strong> is where you fix a wrong match. Scanned ${esc(when(r.scanned))}.</p>
      <div class="stats" style="margin-bottom:12px">
        <div class="stat"><div class="stat-value">${counts("unmatched")}</div><div class="stat-label">Not matched</div></div>
        <div class="stat"><div class="stat-value">${counts("no_ids")}</div><div class="stat-label">No IMDb/TMDB IDs</div></div>
        <div class="stat"><div class="stat-value">${counts("fan_edit")}</div><div class="stat-label">Fan edits</div></div>
        <div class="stat"><div class="stat-value">${r.titles.filter((t) => t.keep).length}</div><div class="stat-label">Posters kept</div></div>
      </div>
      <div class="row" style="margin-bottom:14px">
        <div><label for="umLib">Library</label><select id="umLib"><option value="">All libraries</option>${r.libraries.map((l) =>
          `<option value="${esc(l.id)}" ${f.library === l.id ? "selected" : ""}>${esc(l.title)} (${l.found} of ${l.total.toLocaleString()})</option>`).join("")}</select></div>
        <div><label for="umKind">Kind</label><select id="umKind"><option value="">All</option>${Object.entries(UNMATCHED_KINDS).map(([k, [label]]) =>
          `<option value="${k}" ${f.kind === k ? "selected" : ""}>${label}</option>`).join("")}</select></div>
        <div><label for="umKeep">Poster</label><select id="umKeep"><option value="">Any</option>
          <option value="false" ${f.keep === "false" ? "selected" : ""}>Not kept</option>
          <option value="true" ${f.keep === "true" ? "selected" : ""}>Kept</option></select></div>
        <div class="grow"><label for="umQ">Search</label><input type="text" id="umQ" value="${esc(f.q)}" placeholder="Title, year or file name"></div>
        <button type="button" id="umKeepAll" ${list.some((t) => !t.keep) ? "" : "disabled"}>Keep posters for all ${list.filter((t) => !t.keep).length} shown</button>
      </div>
      <div id="umUpload" class="card upload-panel" hidden></div>
      ${list.length ? `<div class="items">${list.map(tile).join("")}</div>`
        : `<div class="card empty">${r.titles.length ? "Nothing matches these filters." : "Every title is tied to IMDb, TMDB or TVDB."}</div>`}`;
    const bindFilter = (sel, key, ev = "onchange") => { view.querySelector(sel)[ev] = (e) => { f[key] = e.target.value; render(); }; };
    bindFilter("#umLib", "library");
    bindFilter("#umKind", "kind");
    bindFilter("#umKeep", "keep");
    const q = view.querySelector("#umQ");
    q.onchange = (e) => { f.q = e.target.value; render(); };
    q.onkeydown = (e) => { if (e.key === "Enter") { f.q = e.target.value; render(); } };
    view.querySelector("#umRescan").onclick = () => unmatchedPage(true);
    const setKeep = async (titles, keep) => {
      await api("POST", "/unmatched/keep", { keep, items: titles.map((t) => ({ ratingKey: t.ratingKey, section_id: t.section_id, type: t.type })) });
      titles.forEach((t) => { t.keep = keep; });
      toast(keep ? `Poster kept for ${titles.length} title(s)` : `Poster unlocked for ${titles.length} title(s)`);
      render();
    };
    view.querySelectorAll("[data-keep]").forEach((b) => b.onclick = () => guard(async () => {
      const t = r.titles.find((x) => x.ratingKey === b.dataset.keep);
      b.disabled = true;
      await setKeep([t], !t.keep);
    }));
    view.querySelectorAll("[data-upload]").forEach((b) => b.onclick = () =>
      posterUploadPanel(view.querySelector("#umUpload"), r.titles.find((x) => x.ratingKey === b.dataset.upload), render));
    view.querySelector("#umKeepAll").onclick = () => guard(async () => {
      const todo = list.filter((t) => !t.keep);
      if (!confirm(`Keep the posters of all ${todo.length} title(s) shown?\n\nNapalm and the fresh-poster option will never change them.`)) return;
      view.querySelector("#umKeepAll").disabled = true;
      await setKeep(todo, true);
    });
  };
  render();
}

// Upload a new poster (file or URL) for one title; kept by default so napalm won't replace it.
function posterUploadPanel(box, t, done) {
  box.hidden = false;
  box.innerHTML = `
    <div class="upload-grid">
      <div class="image-box poster-img" id="upPreview">${t.thumb ? `<img src="/api/plex/image?path=${encodeURIComponent(t.thumb)}" alt="">` : "▦"}</div>
      <div>
        <h2 style="margin-bottom:4px">New poster for ${esc(t.title)}${t.year ? ` <span class="muted">(${esc(t.year)})</span>` : ""}</h2>
        <p class="hint" style="margin-top:0">A tall image works best (2:3, e.g. 1000 × 1500). JPEG, PNG or WebP, up to 10 MB.</p>
        <label for="upFile">Image file</label><input type="file" id="upFile" accept="image/jpeg,image/png,image/webp">
        <label for="upUrl" style="margin-top:10px">…or image URL</label><input type="url" id="upUrl" placeholder="https://…">
        <label class="check" style="margin-top:10px"><input type="checkbox" id="upKeep" checked>
          Keep this poster (napalm and fresh posters won't replace it)</label>
        <div class="row" style="margin-top:10px">
          <button type="button" class="primary" id="upGo">Upload to Plex</button>
          <button type="button" id="upCancel">Cancel</button>
        </div>
      </div>
    </div>`;
  box.scrollIntoView({ behavior: "smooth", block: "start" });
  const preview = (src) => { box.querySelector("#upPreview").innerHTML = src ? `<img src="${esc(src)}" alt="" referrerpolicy="no-referrer">` : "▦"; };
  const file = box.querySelector("#upFile");
  const url = box.querySelector("#upUrl");
  file.onchange = () => {
    const f = file.files[0];
    if (!f) return;
    if (!IMAGE_TYPES.includes(f.type)) { file.value = ""; return toast("Choose a JPEG, PNG or WebP image", true); }
    if (f.size > MAX_IMAGE_BYTES) { file.value = ""; return toast("Images must be 10 MB or smaller", true); }
    url.value = "";
    preview(URL.createObjectURL(f));
  };
  url.oninput = () => { if (url.value.trim()) { file.value = ""; preview(url.value.trim()); } };
  box.querySelector("#upCancel").onclick = () => { box.hidden = true; };
  box.querySelector("#upGo").onclick = (e) => guard(async () => {
    if (!file.files[0] && !url.value.trim()) return toast("Choose an image file or enter an image URL", true);
    const form = new FormData();
    if (file.files[0]) form.append("file", file.files[0]);
    form.append("url", url.value.trim());
    form.append("keep", box.querySelector("#upKeep").checked ? "true" : "false");
    form.append("section_id", t.section_id);
    form.append("type", t.type);
    e.target.disabled = true;
    try {
      const res = await api("POST", `/titles/${encodeURIComponent(t.ratingKey)}/poster`, form);
      if (res.thumb) t.thumb = res.thumb;
      if (res.keep) t.keep = true;
      toast(`New poster uploaded for ${t.title}${res.keep ? " and kept" : ""}`);
      box.hidden = true;
      done();
    } finally {
      e.target.disabled = false;
    }
  });
}

// ---------- prerolls ----------
// Plex's preroll list (CinemaTrailersPrerollID), built from clips picked in a Plex library.

async function prerollsPage() {
  let data = await api("GET", "/prerolls");
  const cfg = JSON.parse(JSON.stringify(data.settings));
  let tab = "default";
  const fmtTime = (s) => (s >= 60 ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}` : `0:${String(s).padStart(2, "0")}`);
  const md = (v) => {
    if (!v) return "";
    const [m, d] = v.split("-").map(Number);
    return new Date(2000, m - 1, d).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  };
  const clipName = (rk) => data.clips.find((c) => c.ratingKey === rk)?.title || rk;
  const items = () => (tab === "default" ? cfg.default : cfg.sets.find((s) => s.id === tab)?.items || []);
  const setItems = (list) => {
    if (tab === "default") cfg.default = list;
    else cfg.sets.find((s) => s.id === tab).items = list;
  };

  const render = () => {
    const cur = data.current;
    const set = cfg.sets.find((s) => s.id === tab);
    const chosen = new Set(items());
    view.innerHTML = `
      <div class="page-head"><h1>Prerolls</h1>
        <div class="actions">
          ${cfg.backup !== null && cfg.backup !== undefined ? `<button id="prRestore" class="danger">Restore Plex's original list</button>` : ""}
          <button class="primary" id="prSave">Save${cfg.enabled ? " &amp; apply" : ""}</button>
        </div></div>
      <p class="hint" style="margin-top:-8px">Pick preroll clips from a Plex library instead of typing paths into Plex's settings.
        A default set plays most of the year; seasonal sets take over on their dates and switch automatically just after midnight.
        Plex plays prerolls before <strong>movies only</strong>, on apps with Cinema Trailers turned on, and needs Plex Pass.</p>

      <div class="card">
        <h2>Plex's preroll list right now</h2>
        ${cur.value ? `<p>${cur.matched.length + cur.unmatched.length} clip(s), ${cur.mode === "sequence" ? "all played in order" : "one played at random"}:
            ${cur.matched.map((rk) => `<span class="chip">${esc(clipName(rk))}</span>`).join("")}</p>
          ${cur.unmatched.length ? `<div class="notice small">Not in the preroll library (kept only in Plex's list):
            ${cur.unmatched.map((p) => `<div class="mono">${esc(p)}</div>`).join("")}</div>` : ""}`
          : `<p class="muted">Plex has no prerolls set.</p>`}
        <div class="small muted">${cfg.enabled
          ? `Managed by Curatarr. Today: <strong>${esc(data.active.name)}</strong> (${data.active.count} clip(s))${data.next_change
            ? ` · switches to <strong>${esc(data.next_change.set)}</strong> on ${esc(new Date(data.next_change.date + "T00:00").toLocaleDateString())}` : ""}.`
          : "Not managed by Curatarr yet: tick the clips below, turn on managing and save."}</div>
      </div>

      <div class="card"><div class="grid">
        <div><label for="prLib">Preroll library</label><select id="prLib">
          <option value="">Choose a library</option>${data.libraries.map((l) =>
            `<option value="${esc(l.id)}" ${cfg.section_id === l.id ? "selected" : ""}>${esc(l.title)}</option>`).join("")}</select></div>
        <div><label for="prMode">Play mode</label><select id="prMode">
          <option value="random" ${cfg.mode === "random" ? "selected" : ""}>One at random before each movie</option>
          <option value="sequence" ${cfg.mode === "sequence" ? "selected" : ""}>All of them, in order</option>
          <option value="daily" ${cfg.mode === "daily" ? "selected" : ""}>A new random pick each day, played in order</option></select></div>
        <div ${cfg.mode === "daily" ? "" : "hidden"}><label for="prCount">Clips per day</label>
          <input type="number" id="prCount" min="1" max="50" value="${esc(cfg.daily_count)}"></div>
        <div><label class="check" style="margin-top:22px"><input type="checkbox" id="prOn" ${cfg.enabled ? "checked" : ""}>
          Let Curatarr manage Plex's preroll list</label></div>
      </div></div>

      <div class="card">
        <div class="tabs">
          <button type="button" class="tab ${tab === "default" ? "active" : ""}" data-tab="default">Default <span class="muted">${cfg.default.length}</span></button>
          ${cfg.sets.map((s) => `<button type="button" class="tab ${tab === s.id ? "active" : ""}" data-tab="${esc(s.id)}">${esc(s.name)}
            <span class="muted">${s.items.length}</span></button>`).join("")}
          <button type="button" class="tab" id="prAddSet">+ Seasonal set</button>
        </div>
        ${set ? `<div class="row" style="margin:12px 0">
            <div><label>Name</label><input type="text" id="prSetName" value="${esc(set.name)}"></div>
            <div><label>From</label><input type="date" id="prSetStart" value="2000-${esc(set.start)}"></div>
            <div><label>Until (inclusive)</label><input type="date" id="prSetEnd" value="2000-${esc(set.end)}"></div>
            <button type="button" class="small danger" id="prDelSet">Delete set</button>
          </div>
          <p class="hint" style="margin-top:0">Plays ${esc(md(set.start))} – ${esc(md(set.end))} every year, instead of the default set.</p>`
          : `<p class="hint">Plays whenever no seasonal set is in its dates.
              ${cur.matched.length ? `<button type="button" class="small" id="prImport">Use Plex's current list</button>` : ""}</p>`}
        <div class="row" style="margin-bottom:10px">
          <button type="button" class="small" id="prAll">Select all</button>
          <button type="button" class="small" id="prNone">Select none</button>
          <span class="small muted">${chosen.size} of ${data.clips.length} clips</span>
        </div>
        ${data.clips.length ? `<div class="preroll-list">${data.clips.map((c) => `
          <label class="preroll ${chosen.has(c.ratingKey) ? "on" : ""}">
            <input type="checkbox" data-clip="${esc(c.ratingKey)}" ${chosen.has(c.ratingKey) ? "checked" : ""}>
            <div class="preroll-thumb">${c.thumb ? `<img loading="lazy" src="/api/plex/image?path=${encodeURIComponent(c.thumb)}" alt="">` : "▶"}</div>
            <div class="preroll-info"><div class="item-title" title="${esc(c.title)}">${esc(c.title)}</div>
              <div class="small muted">${fmtTime(c.duration)}${cur.matched.includes(c.ratingKey) ? " · in Plex's list now" : ""}</div>
              <div class="unmatched-file muted" title="${esc(c.file)}">${esc(c.file)}</div></div>
          </label>`).join("")}</div>`
          : `<div class="card empty">${cfg.section_id ? "No clips in that library." : "Choose your preroll library above."}</div>`}
      </div>`;

    const q = (s) => view.querySelector(s);
    q("#prLib").onchange = (e) => guard(async () => {
      cfg.section_id = e.target.value;
      const wasOn = cfg.enabled;
      data = await api("PUT", "/prerolls", { ...cfg, enabled: false });       // load that library's clips
      Object.assign(cfg, { enabled: false });
      if (wasOn) toast("Managing paused while you switch libraries: tick clips from this one, then turn it back on and save.");
      render();
    });
    q("#prMode").onchange = (e) => { cfg.mode = e.target.value; render(); };
    q("#prCount") && (q("#prCount").onchange = (e) => { cfg.daily_count = Number(e.target.value) || 3; });
    q("#prOn").onchange = (e) => { cfg.enabled = e.target.checked; render(); };
    view.querySelectorAll("[data-tab]").forEach((b) => b.onclick = () => { tab = b.dataset.tab; render(); });
    q("#prAddSet").onclick = () => {
      const id = `set${Date.now()}`;
      cfg.sets.push({ id, name: "Halloween", start: "10-01", end: "10-31", items: [] });
      tab = id;
      render();
    };
    if (set) {
      q("#prSetName").onchange = (e) => { set.name = e.target.value; render(); };
      q("#prSetStart").onchange = (e) => { set.start = e.target.value.slice(5); render(); };
      q("#prSetEnd").onchange = (e) => { set.end = e.target.value.slice(5); render(); };
      q("#prDelSet").onclick = () => {
        if (!confirm(`Delete the set "${set.name}"?`)) return;
        cfg.sets = cfg.sets.filter((s) => s !== set);
        tab = "default";
        render();
      };
    }
    q("#prImport")?.addEventListener("click", () => { cfg.default = [...cur.matched]; render(); });
    q("#prAll").onclick = () => { setItems(data.clips.map((c) => c.ratingKey)); render(); };
    q("#prNone").onclick = () => { setItems([]); render(); };
    view.querySelectorAll("[data-clip]").forEach((box) => box.onchange = () => {
      const list = items().filter((k) => k !== box.dataset.clip);
      if (box.checked) list.push(box.dataset.clip);
      setItems(data.clips.map((c) => c.ratingKey).filter((k) => list.includes(k)));     // library order
      render();
    });
    q("#prSave").onclick = () => guard(async () => {
      if (cfg.enabled && !cfg.default.length && !cfg.sets.some((s) => s.items.length)
          && !confirm("No clips are ticked, so Plex's preroll list will be emptied. Continue?")) return;
      if (cfg.enabled && cfg.backup == null && data.current.value
          && !confirm("Curatarr will now manage Plex's preroll list. Your current list is saved first, so you can restore it. Continue?")) return;
      data = await api("PUT", "/prerolls", cfg);
      Object.assign(cfg, JSON.parse(JSON.stringify(data.settings)));
      toast(cfg.enabled ? `Saved. Plex now plays the "${data.active.name}" set (${data.active.count} clip(s)).` : "Saved. Curatarr isn't managing Plex's prerolls.");
      render();
    });
    q("#prRestore")?.addEventListener("click", () => guard(async () => {
      if (!confirm("Put back the preroll list Plex had before Curatarr changed it, and stop managing it?")) return;
      data = await api("POST", "/prerolls/restore");
      Object.assign(cfg, JSON.parse(JSON.stringify(data.settings)));
      toast("Plex's original preroll list is back");
      render();
    }));
  };
  render();
}

// ---------- starter packs ----------

async function packsPage(kind) {
  const meta = KINDS[kind];
  document.querySelector(`[data-nav="${meta.hash.slice(2)}"]`)?.classList.add("active");
  const [packs, allLibs] = await Promise.all([api("GET", `/packs?media=${kind}`), libraries().catch(() => [])]);
  const libs = allLibs.filter((l) => l.type === kind);
  let sectionId = libs[0]?.id || "";
  const picked = new Set();

  const render = () => {
    view.innerHTML = `
      <p class="small" style="margin:0 0 8px"><a href="${meta.hash}">← Back</a></p>
      <div class="page-head"><h1>Starter packs</h1>
        <div class="actions"><button class="primary" id="createPacks" disabled>Create collections</button></div></div>
      <p class="hint" style="margin-top:-8px">Ready-made ${meta.noun} collections from TMDB. Tick the ones you want;
        each becomes a normal collection you can edit afterwards. A TMDB API key is needed (Settings).</p>
      <div class="card"><div class="grid">
        <div><label for="packLib">Library</label><select id="packLib">${libs.map((l) =>
          `<option value="${esc(l.id)}" ${l.id === sectionId ? "selected" : ""}>${esc(l.title)}</option>`).join("")
          || `<option value="">Connect Plex first</option>`}</select></div>
        <div><label for="packMode">Mode</label><select id="packMode">
          <option value="sync">Sync: add new and remove titles no longer listed</option>
          <option value="append">Append: only add titles</option></select></div>
        <div><label class="check"><input type="checkbox" id="packArr"> Send missing titles to ${kind === "show" ? "Sonarr" : "Radarr"}</label>
          <label class="check"><input type="checkbox" id="packSync" checked> Sync them right away</label></div>
      </div></div>
      ${packs.map((p) => `
        <details class="fold card" data-fold="packs.${esc(p.key)}" ${foldOpen(`packs.${p.key}`, true) ? "open" : ""}>
          <summary class="fold-head"><h2>${esc(p.name)}</h2><span class="muted small">${esc(p.about)}</span></summary>
          <div class="pack-items">${p.items.map((i) => {
            const have = i.in_libraries.includes(sectionId);
            return `<label class="check${have ? " muted" : ""}" title="${esc(i.about)}">
              <input type="checkbox" data-pack="${esc(i.key)}" ${have ? "disabled" : picked.has(i.key) ? "checked" : ""}>
              ${esc(i.name)}${have ? ` <span class="badge">added</span>` : ""}</label>`;
          }).join("")}</div>
        </details>`).join("")}`;
    bindFolds(view);
    const button = view.querySelector("#createPacks");
    const count = () => {
      button.disabled = !picked.size || !sectionId;
      button.textContent = picked.size ? `Create ${picked.size} collection${picked.size === 1 ? "" : "s"}` : "Create collections";
    };
    count();
    view.querySelector("#packLib").onchange = (e) => { sectionId = e.target.value; picked.clear(); render(); };
    view.querySelectorAll("[data-pack]").forEach((box) => box.onchange = () => {
      box.checked ? picked.add(box.dataset.pack) : picked.delete(box.dataset.pack);
      count();
    });
    button.onclick = () => guard(async () => {
      button.disabled = true;
      const r = await api("POST", "/packs", {
        section_id: sectionId, keys: [...picked], sync_mode: view.querySelector("#packMode").value,
        request_missing: view.querySelector("#packArr").checked, sync_now: view.querySelector("#packSync").checked,
      });
      toast(`Created ${r.created} collection(s)${r.skipped.length ? `; ${r.skipped.length} already existed` : ""}`);
      location.hash = meta.hash;
    });
  };
  render();
}

// ---------- collection editor ----------

const DEFAULTS = {
  name: "", library: "", section_id: "", sources: [{ type: "tmdb_list", value: "", limit: null }],
  sync_mode: "sync", order: "custom", summary: "", sort_title: "", labels: [], collection_mode: "default",
  poster_url: "", art_url: "", poster_file: "", art_file: "", item_limit: 0, min_items: 1,
  delete_below_min: false, promote_home: false, promote_shared: false, promote_recommended: false,
  promote_window: false, promote_start: "", promote_end: "", promote_yearly: true, seasonal_only: false, pin_top: false,
  schedule: "", request_missing: false, enabled: true, exclude: [], max_rating: "", drop_unrated: false,
};

// Content-rating caps, youngest audience first (mirrors models.RATING_LEVELS).
const RATING_CAPS = [
  ["G", "G / TV-G / TV-Y7"], ["PG", "PG / TV-PG"], ["PG-13", "PG-13 / TV-14"], ["R", "R / TV-MA"],
];

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
      ${src.type === "plex_filter" ? `<div class="row" style="flex-wrap:nowrap">${input}<button type="button" class="small" data-build>Build filter</button></div>` : input}
      <input type="number" data-field="limit" min="1" placeholder="Limit" value="${src.limit ?? ""}" title="Max items from this source">
      <button type="button" class="small danger" data-remove="${idx}" title="Remove source">✕</button>
      <div class="filter-builder full-row" hidden></div>
    </div>`;
}

const PLEX_SORTS = [
  ["", "Plex default"], ["originallyAvailableAt:desc", "Newest release first"], ["originallyAvailableAt", "Oldest release first"],
  ["audienceRating:desc", "Highest audience rating"], ["rating:desc", "Highest critic rating"],
  ["addedAt:desc", "Recently added"], ["titleSort", "Title"], ["viewCount:desc", "Most played"],
];

// Builds a Plex filter query (genre=12&year>>=1980…) from form fields.
async function openFilterBuilder(box, src, sectionId, onApply) {
  if (!box.hidden) { box.hidden = true; return; }
  if (!sectionId) return toast("Pick one Plex library first (a Plex filter works on a single library)", true);
  box.hidden = false;
  box.innerHTML = `<p class="muted small">Loading library filters…</p>`;
  let f;
  try {
    f = await api("GET", `/plex/libraries/${encodeURIComponent(sectionId)}/filters`);
  } catch (err) {
    box.innerHTML = `<p class="no small">${esc(err.message)}</p>`;
    return;
  }
  const cur = new URLSearchParams(src.value);
  const opts = (list, selected) => `<option value="">Any</option>` + list.map((v) =>
    `<option value="${esc(v.id)}" ${v.id === selected ? "selected" : ""}>${esc(v.title)}</option>`).join("");
  const days = (cur.get("addedAt>>") || "").match(/^-(\d+)d$/)?.[1] || "";
  box.innerHTML = `
    <div class="grid">
      <div><label>Genre</label><select data-q="genre">${opts(f.genre, cur.get("genre"))}</select></div>
      ${f.director.length ? `<div><label>Director</label><select data-q="director">${opts(f.director, cur.get("director"))}</select></div>` : ""}
      ${f.studio.length ? `<div><label>Studio / network</label><select data-q="studio">${opts(f.studio, cur.get("studio"))}</select></div>` : ""}
      <div><label>Content rating</label><select data-q="contentRating">${opts(f.contentRating, cur.get("contentRating"))}</select></div>
      <div><label>Year from</label><input type="number" data-q="year>>" value="${esc(cur.get("year>>") || "")}" placeholder="1980"></div>
      <div><label>Year to</label><input type="number" data-q="year<<" value="${esc(cur.get("year<<") || "")}" placeholder="1989"></div>
      <div><label>Added in the last … days</label><input type="number" min="1" data-days value="${esc(days)}" placeholder="30"></div>
      <div><label>Sort</label><select data-q="sort">${PLEX_SORTS.map(([v, l]) =>
        `<option value="${v}" ${v === (cur.get("sort") || "") ? "selected" : ""}>${l}</option>`).join("")}</select></div>
      <div><label class="check"><input type="checkbox" data-q="unwatched" ${cur.get("unwatched") === "1" ? "checked" : ""}> Unwatched only</label></div>
    </div>
    <div class="row" style="margin-top:10px"><button type="button" class="small primary" data-apply>Use this filter</button>
      <span class="hint">Matches titles already in this library. Combine it with other lists, or use it on its own.</span></div>`;
  box.querySelector("[data-apply]").onclick = () => {
    const parts = [];
    box.querySelectorAll("[data-q]").forEach((el) => {
      const value = el.type === "checkbox" ? (el.checked ? "1" : "") : el.value.trim();
      if (value) parts.push(`${el.dataset.q}=${encodeURIComponent(value)}`);
    });
    const n = box.querySelector("[data-days]").value.trim();
    if (n) parts.push(`addedAt>>=-${Number(n)}d`);
    if (!parts.some((p) => !p.startsWith("sort="))) return toast("Pick at least one filter", true);
    box.hidden = true;
    onApply(parts.join("&"));
  };
}

async function editor(id, params = new URLSearchParams()) {
  await catalog();
  const [row, libs] = await Promise.all([
    id ? api("GET", `/collections/${id}`) : null,
    libraries().catch((err) => { toast(`Plex: ${err.message}`, true); return []; }),
  ]);
  const cfg = { ...DEFAULTS, ...(row?.config || {}) };
  cfg.sources = cfg.sources.map((s) => ({ ...s }));
  cfg.exclude = [...cfg.exclude];
  if (!id && params.get("kind") === "playlist") cfg.kind = "playlist";
  const isPlaylist = cfg.kind === "playlist";
  const noun = isPlaylist ? "playlist" : "collection";
  cfg.section_ids = [...(cfg.section_ids || [])];
  if (isPlaylist && !id && !cfg.section_ids.length) {
    // New playlists start with every movie and TV library ticked.
    cfg.section_ids = libs.map((l) => l.id);
  }
  // Linking an existing Plex collection: keep its name and library, and default
  // to append so the titles already in it are not removed.
  const link = !id && params.get("link");
  if (link) {
    Object.assign(cfg, { name: params.get("title") || "", sync_mode: "append" });
    if (params.get("section")) cfg.section_id = params.get("section");
  }
  // "+ New collection" on the Movies / TV page starts on a library of that type.
  if (!id && !link && params.get("type")) {
    cfg.section_id = libs.find((l) => l.type === params.get("type"))?.id || "";
  }
  const kind = collectionKind(cfg, libs) || params.get("type") || "movie";
  const backHash = () => {
    if (cfg.holiday) return "#/holidays";
    if (isPlaylist) return "#/playlists";
    const opt = view.querySelector("#f-lib")?.selectedOptions[0];
    return KINDS[opt?.dataset.type || kind].hash;
  };
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active",
    a.getAttribute("href") === (cfg.holiday ? "#/holidays" : isPlaylist ? "#/playlists" : KINDS[kind].hash)));
  // Libraries picked for the lists: one for a collection, any number for a playlist.
  const pickedLibs = () => isPlaylist
    ? [...view.querySelectorAll("[data-lib]:checked")].map((b) => ({ id: b.value, title: b.dataset.title, type: b.dataset.type }))
    : [view.querySelector("#f-lib").selectedOptions[0]].filter(Boolean)
      .map((o) => ({ id: o.value, title: o.dataset.title || "", type: o.dataset.type }));
  const settings = await api("GET", "/settings").catch(() => ({ values: {} }));
  const defaultSchedule = settings.values.default_schedule || "";
  // Image files picked in the form; uploaded (or removed) when the collection is saved.
  const images = { poster: { file: null, remove: false }, art: { file: null, remove: false } };

  const libOptions = libs.map((l) =>
    `<option value="${esc(l.id)}" data-title="${esc(l.title)}" data-type="${esc(l.type)}" ${l.id === cfg.section_id || (!cfg.section_id && l.title === cfg.library) ? "selected" : ""}>${esc(l.title)} (${l.type === "show" ? "TV" : "Movies"})</option>`).join("");

  view.innerHTML = `
    <div class="page-head">
      <h1>${id ? esc(cfg.name) : link ? `Sync “${esc(cfg.name)}”` : `New ${noun}`}</h1>
      <div class="actions">
        ${id ? `<button id="dryRun">Dry run</button>` : ""}
        <button id="save">Save</button>
        <button id="saveRun" class="primary">Save &amp; sync</button>
      </div>
    </div>

    ${link ? `<div class="notice">
      Linking to the existing Plex ${noun} <strong>${esc(cfg.name)}</strong> (${esc(params.get("items") || "0")} items).
      Add the lists it should follow below. <strong>Append</strong> mode is selected so the titles already in it stay;
      switch to <strong>Sync</strong> only if you want Curatarr to remove anything that isn't on your lists.
    </div>` : ""}

    ${row && row.plex_owned === 0 ? `<div class="notice">
      A Plex ${noun} named <strong>${esc(cfg.name)}</strong> already existed, so Curatarr is using it but only
      <strong>adds</strong> titles — it never removes titles from it or deletes it.
      <div style="margin-top:8px"><button type="button" class="small" id="ownIt">Let Curatarr remove titles too</button></div>
    </div>` : ""}

    <div class="card">
      <h2>Basics</h2>
      <div class="grid">
        <div><label for="f-name">${isPlaylist ? "Playlist" : "Collection"} name</label><input type="text" id="f-name" value="${esc(cfg.name)}" placeholder="${isPlaylist ? "MCU in order" : "IMDb Top 250"}" ${link ? "readonly" : ""}></div>
        ${isPlaylist ? `<div><label>Libraries to take titles from</label>${libs.map((l) => `
          <label class="check"><input type="checkbox" data-lib value="${esc(l.id)}" data-title="${esc(l.title)}" data-type="${esc(l.type)}"
            ${cfg.section_ids.includes(l.id) ? "checked" : ""}> ${esc(l.title)} (${l.type === "show" ? "TV" : "Movies"})</label>`).join("")
            || `<p class="muted small">Connect Plex first.</p>`}</div>`
        : `<div><label for="f-lib">Plex library</label>
          <select id="f-lib" ${link ? "disabled" : ""}>${libOptions || `<option value="${esc(cfg.section_id)}" data-title="${esc(cfg.library)}">${esc(cfg.library || "Connect Plex first")}</option>`}</select></div>`}
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
        <div ${isPlaylist ? "hidden" : ""}><label for="f-order">Order in Plex</label>
          <select id="f-order">
            <option value="custom" ${cfg.order === "custom" ? "selected" : ""}>List order</option>
            <option value="release" ${cfg.order === "release" ? "selected" : ""}>Release date</option>
            <option value="alpha" ${cfg.order === "alpha" ? "selected" : ""}>Alphabetical</option>
          </select></div>
        <div><label for="f-limit">Max items (0 = no limit)</label><input type="number" id="f-limit" min="0" value="${cfg.item_limit}"></div>
        <div><label for="f-min">Minimum matched items</label><input type="number" id="f-min" min="0" value="${cfg.min_items}">
          <label class="check"><input type="checkbox" id="f-delmin" ${cfg.delete_below_min ? "checked" : ""}> Delete the Plex ${noun} when below minimum</label></div>
        <div><label for="f-schedule">Schedule (cron)</label><input type="text" id="f-schedule" value="${esc(cfg.schedule)}" placeholder="${esc(defaultSchedule)} (default)">
          <div class="hint">Five-field cron, e.g. <code>0 */6 * * *</code> for every 6 hours.</div></div>
        <div><label class="check"><input type="checkbox" id="f-request" ${cfg.request_missing ? "checked" : ""}> Send missing titles to Radarr / Sonarr</label></div>
        <div><label for="f-rating">Highest content rating</label>
          <select id="f-rating">
            <option value="">No limit</option>
            ${RATING_CAPS.map(([v, label]) => `<option value="${v}" ${cfg.max_rating === v ? "selected" : ""}>${esc(label)}</option>`).join("")}
          </select>
          <label class="check"><input type="checkbox" id="f-unrated" ${cfg.drop_unrated ? "checked" : ""}> Also leave out unrated titles</label></div>
        <div class="full"><label>Excluded titles</label><div id="excluded"></div>
          <div class="hint">Excluded titles are never added, even when a list has them. Exclude a title from the ${noun}'s <strong>View</strong> page.</div></div>
      </div>
    </div>

    <div class="card">
      <h2>Appearance in Plex</h2>
      <div class="grid">
        <div class="full"><label for="f-summary">Summary</label><textarea id="f-summary">${esc(cfg.summary)}</textarea></div>
        <div ${isPlaylist ? "hidden" : ""}><label for="f-sort">Sort title</label><input type="text" id="f-sort" value="${esc(cfg.sort_title)}" placeholder="!01 Top 250"></div>
        <div ${isPlaylist ? "hidden" : ""}><label for="f-labels">Labels (comma separated)</label><input type="text" id="f-labels" value="${esc(cfg.labels.join(", "))}"></div>
        <div ${isPlaylist ? "hidden" : ""}><label for="f-cmode">Collection visibility in library</label>
          <select id="f-cmode">
            <option value="default" ${cfg.collection_mode === "default" ? "selected" : ""}>Library default</option>
            <option value="hide" ${cfg.collection_mode === "hide" ? "selected" : ""}>Hide collection</option>
            <option value="hideItems" ${cfg.collection_mode === "hideItems" ? "selected" : ""}>Hide items, show collection</option>
            <option value="showItems" ${cfg.collection_mode === "showItems" ? "selected" : ""}>Show collection and items</option>
          </select></div>
        <div ${isPlaylist ? "hidden" : ""}><label>Home screen</label>
          <label class="check"><input type="checkbox" id="f-rec" ${cfg.promote_recommended ? "checked" : ""}> Library recommended</label>
          <label class="check"><input type="checkbox" id="f-home" ${cfg.promote_home ? "checked" : ""}> My home</label>
          <label class="check"><input type="checkbox" id="f-shared" ${cfg.promote_shared ? "checked" : ""}> Friends' home</label></div>
        <div class="full calendar" ${isPlaylist ? "hidden" : ""}>
          <label class="check"><input type="checkbox" id="f-window" ${cfg.promote_window ? "checked" : ""}> Only show on the home screen between these dates</label>
          <div class="row" id="window-fields">
            <div><label for="f-wstart">From</label><input type="date" id="f-wstart" value="${esc(cfg.promote_start)}"></div>
            <div><label for="f-wend">Until (inclusive)</label><input type="date" id="f-wend" value="${esc(cfg.promote_end)}"></div>
            <div><label class="check"><input type="checkbox" id="f-wyearly" ${cfg.promote_yearly ? "checked" : ""}> Repeat every year</label></div>
          </div>
          <label class="check"><input type="checkbox" id="f-seasonal" ${cfg.seasonal_only ? "checked" : ""}> Only keep the collection in Plex during these dates (deleted after, re-created when they come round)</label>
          <label class="check"><input type="checkbox" id="f-pin" ${cfg.pin_top ? "checked" : ""}> Move it to the top of the home screen during these dates (put back after)</label>
          <div class="hint" id="window-status"></div>
        </div>
      </div>
    </div>

    <div class="card" ${isPlaylist ? "hidden" : ""}>
      <h2>Poster overlays</h2>
      <p class="hint" style="margin-top:-6px">Draws a ribbon and badges on every title's poster in this collection.
        The original posters are kept and put back if you turn these off or delete the collection.</p>
      <div class="overlay-edit">
        <div class="grid" style="flex:1">
          <div class="full"><label class="check"><input type="checkbox" id="r-on" ${cfg.ribbon?.enabled ? "checked" : ""}> Ribbon on every title's poster</label></div>
          <div><label for="r-text">Ribbon text</label><input type="text" id="r-text" maxlength="40"
            value="${esc(cfg.ribbon?.text || "")}" placeholder="${esc(cfg.name.replace(/^!\d+_/, "").replace(/ Collection$/i, "").toUpperCase() || "TOP 250")}"></div>
          <div><label for="r-corner">Corner</label><select id="r-corner">
            <option value="top-right" ${cfg.ribbon?.corner !== "top-left" ? "selected" : ""}>Top right</option>
            <option value="top-left" ${cfg.ribbon?.corner === "top-left" ? "selected" : ""}>Top left</option>
            <option value="bottom-right" ${cfg.ribbon?.corner === "bottom-right" ? "selected" : ""}>Bottom right</option>
            <option value="bottom-left" ${cfg.ribbon?.corner === "bottom-left" ? "selected" : ""}>Bottom left</option></select></div>
          <div><label for="r-size">Size</label><select id="r-size">${[["small", "Small"], ["medium", "Medium"],
            ["large", "Large"], ["xlarge", "Extra large"]].map(([v, l]) =>
            `<option value="${v}" ${(cfg.ribbon?.size || "medium") === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
          <div><label for="r-font">Font</label><select id="r-font"><option value="${esc(cfg.ribbon?.font || "sans")}">…</option></select></div>
          <div><label for="r-color">Ribbon colour</label><input type="color" id="r-color" value="${esc(cfg.ribbon?.color || "#f5c518")}"></div>
          <div><label for="r-tcolor">Text colour</label><input type="color" id="r-tcolor" value="${esc(cfg.ribbon?.text_color || "#000000")}"></div>
          <div class="full"><label class="check"><input type="checkbox" id="b-quality" ${cfg.badges?.quality ? "checked" : ""}>
            Quality badges: resolution, HDR or Dolby Vision, Atmos (movies)</label>
            <label class="check"><input type="checkbox" id="b-cert" ${cfg.badges?.content_rating ? "checked" : ""}>
            Content rating badge: PG-13, TV-MA and so on</label>
            <label class="check"><input type="checkbox" id="f-fresh" ${cfg.fresh_poster ? "checked" : ""}>
            Start from a fresh poster from Plex's sources</label>
            <div class="hint">Swaps each title's poster for the first one from Plex's metadata sources (such as TMDB),
              dropping artwork other tools added. On its own, without a ribbon or badges, it just switches to that clean poster.
              The current posters are kept and put back if you turn this off.</div></div>
          <div><label for="b-rating">Rating badge</label><select id="b-rating">
            <option value="">None</option>
            <option value="audience" ${cfg.badges?.rating === "audience" ? "selected" : ""}>Audience rating (e.g. IMDb)</option>
            <option value="critic" ${cfg.badges?.rating === "critic" ? "selected" : ""}>Critic rating (e.g. Rotten Tomatoes)</option></select>
            <div class="hint">Uses the ratings shown in Plex, set in the library's settings.</div></div>
          <div><label for="b-min">Only show ratings of at least (out of 10)</label>
            <input type="number" id="b-min" min="0" max="10" step="0.1" value="${cfg.badges?.rating_min || 0}"></div>
          <div class="full"><button type="button" class="small" id="r-preview">Preview</button>
            <span class="hint">Shown on the collection's first title (sample badges where it has no data).
              Applied to Plex after you save, then kept up to date at every sync.</span></div>
        </div>
        <div class="overlay-preview image-box" id="r-out">▦</div>
      </div>
    </div>

    <div class="card">
      <h2>Artwork</h2>
      <div class="images">
        ${imageSlot(id, cfg, "poster", "Poster (2:3)")}
        ${isPlaylist ? "" : imageSlot(id, cfg, "art", "Background (16:9)")}
      </div>
      <div id="tmdbPicker" class="tmdb-picker" hidden></div>
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
      el.querySelector("[data-build]")?.addEventListener("click", () => openFilterBuilder(
        el.querySelector(".filter-builder"), src, pickedLibs().length > 1 ? "" : pickedLibs()[0]?.id, (query) => {
          src.value = query;
          el.querySelector("[data-field=value]").value = query;
        }));
    });
  };
  renderSources();
  const renderExcluded = () => {
    const el = view.querySelector("#excluded");
    el.innerHTML = cfg.exclude.length
      ? cfg.exclude.map((e, i) => `<span class="chip">${esc(e.title || e.id)}<button type="button" data-unexclude="${i}" title="Allow this title again">✕</button></span>`).join("")
      : `<span class="muted small">None</span>`;
    el.querySelectorAll("[data-unexclude]").forEach((b) => b.onclick = () => {
      cfg.exclude.splice(Number(b.dataset.unexclude), 1);
      renderExcluded();
    });
  };
  renderExcluded();
  const updateRating = () => { view.querySelector("#f-unrated").disabled = !view.querySelector("#f-rating").value; };
  view.querySelector("#f-rating").onchange = updateRating;
  updateRating();
  // Home screen calendar: date fields only matter when the box is ticked; ticking it
  // with no home screen spots chosen selects all three.
  const spots = ["#f-rec", "#f-home", "#f-shared"].map((s) => view.querySelector(s));
  const updateWindow = () => {
    const on = view.querySelector("#f-window").checked;
    view.querySelectorAll("#window-fields input, #f-seasonal, #f-pin").forEach((el) => { el.disabled = !on; });
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

  // The ribbon text box shows a suggestion; an empty box uses it.
  const ribbonFields = () => ({
    enabled: !isPlaylist && view.querySelector("#r-on").checked,
    text: view.querySelector("#r-text").value.trim() || view.querySelector("#r-text").placeholder,
    corner: view.querySelector("#r-corner").value,
    size: view.querySelector("#r-size").value,
    font: view.querySelector("#r-font").value,
    color: view.querySelector("#r-color").value,
    text_color: view.querySelector("#r-tcolor").value,
  });
  const badgeFields = () => ({
    quality: !isPlaylist && view.querySelector("#b-quality").checked,
    content_rating: !isPlaylist && view.querySelector("#b-cert").checked,
    rating: isPlaylist ? "" : view.querySelector("#b-rating").value,
    rating_min: Number(view.querySelector("#b-min").value || 0),
  });
  // Ribbon fonts: only the ones installed on this server.
  api("GET", "/overlays/fonts").then((fonts) => {
    const select = view.querySelector("#r-font");
    const current = cfg.ribbon?.font || "sans";
    select.innerHTML = fonts.map((f) => `<option value="${esc(f.key)}" ${f.key === current ? "selected" : ""}>${esc(f.name)}</option>`).join("")
      || `<option value="sans">Sans bold</option>`;
  }).catch(() => {});
  view.querySelector("#r-preview").onclick = () => guard(async () => {
    const out = view.querySelector("#r-out");
    out.textContent = "…";
    const resp = await api("POST", "/overlays/preview",
      { ribbon: { ...ribbonFields(), enabled: view.querySelector("#r-on").checked }, badges: badgeFields(),
        fresh_poster: view.querySelector("#f-fresh").checked, collection_id: id }, true);
    if (!resp.ok) { out.textContent = "▦"; throw new Error(`Preview failed (HTTP ${resp.status})`); }
    out.innerHTML = `<img src="${URL.createObjectURL(await resp.blob())}" alt="Overlay preview">`;
  });
  const collect = () => {
    const picked = pickedLibs();
    return {
      ...cfg,
      name: view.querySelector("#f-name").value,
      section_id: picked[0]?.id || "",
      library: picked[0]?.title || "",
      section_ids: isPlaylist ? picked.map((l) => l.id) : [],
      libraries: isPlaylist ? picked.map((l) => l.title) : [],
      enabled: view.querySelector("#f-enabled").checked,
      sync_mode: view.querySelector("#f-mode").value,
      order: isPlaylist ? "custom" : view.querySelector("#f-order").value,
      item_limit: Number(view.querySelector("#f-limit").value || 0),
      min_items: Number(view.querySelector("#f-min").value || 0),
      delete_below_min: view.querySelector("#f-delmin").checked,
      schedule: view.querySelector("#f-schedule").value,
      request_missing: view.querySelector("#f-request").checked,
      max_rating: view.querySelector("#f-rating").value,
      drop_unrated: view.querySelector("#f-unrated").checked,
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
      pin_top: view.querySelector("#f-pin").checked,
      ribbon: ribbonFields(),
      badges: badgeFields(),
      fresh_poster: !isPlaylist && view.querySelector("#f-fresh").checked,
      poster_url: view.querySelector("#poster-url").value,
      art_url: view.querySelector("#art-url")?.value || "",
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
      const r = await api("POST", "/preview", { section_id: body.section_id, library: body.library, section_ids: body.section_ids, sources: body.sources, item_limit: body.item_limit });
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

  view.querySelector("#poster-tmdb").onclick = () => {
    const box = view.querySelector("#tmdbPicker");
    if (!box.hidden) { box.hidden = true; return; }
    const franchises = cfg.sources.filter((s) => s.type === "tmdb_collection"
      || (s.type === "tmdb_list" && s.value.includes("/collection/"))).map((s) => s.value);
    tmdbPosterPicker(box, view.querySelector("#f-name").value.replace(/^!\d+_/, "").replace(/ Collection$/i, ""),
      franchises, (url) => {
        const input = view.querySelector("#poster-url");
        input.value = url;
        input.dispatchEvent(new Event("input"));
        if (images.poster.file || (cfg.poster_file && !images.poster.remove)) {
          toast("Poster URL set. Remove the poster image file to use it, since a file takes priority.");
        } else {
          toast("Poster chosen. It's applied in Plex at the next sync after you save.");
        }
      });
  };
  for (const kind of isPlaylist ? ["poster"] : ["poster", "art"]) {
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
      ${kind === "poster" ? `<button type="button" class="small" id="poster-tmdb">Choose from TMDB…</button>` : ""}
    </div>`;
}

// Poster choices from TMDB: the franchise's own posters, then matches for a search.
async function tmdbPosterPicker(box, query, collections, onPick) {
  box.hidden = false;
  const search = async (q) => {
    const grid = box.querySelector(".tmdb-grid");
    grid.innerHTML = `<p class="muted small">Searching TMDB…</p>`;
    try {
      const params = new URLSearchParams({ query: q });
      collections.forEach((c) => params.append("collection", c));
      const posters = await api("GET", `/tmdb/posters?${params}`);
      grid.innerHTML = posters.length ? posters.map((p, i) => `
        <button type="button" class="tmdb-pick" data-pick="${i}" title="${esc(p.label)}">
          <img loading="lazy" src="${esc(p.thumb)}" alt="" referrerpolicy="no-referrer"></button>`).join("")
        : `<p class="muted small">No posters found. Try another search.</p>`;
      grid.querySelectorAll("[data-pick]").forEach((b) => b.onclick = () => {
        onPick(posters[Number(b.dataset.pick)].url);
        box.hidden = true;
      });
    } catch (err) {
      grid.innerHTML = `<p class="no small">${esc(err.message)}</p>`;
    }
  };
  box.innerHTML = `
    <div class="row"><div class="grow"><input type="text" id="tmdbQuery" value="${esc(query)}" placeholder="Search TMDB collections"></div>
      <button type="button" class="small" id="tmdbSearch">Search</button>
      <button type="button" class="small" id="tmdbClose">Close</button></div>
    <div class="tmdb-grid"></div>`;
  box.querySelector("#tmdbSearch").onclick = () => search(box.querySelector("#tmdbQuery").value);
  box.querySelector("#tmdbQuery").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); search(e.target.value); } };
  box.querySelector("#tmdbClose").onclick = () => { box.hidden = true; };
  await search(query);
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
          <td>${r.added_items.length || r.removed_items.length ? `<details><summary>+${r.added} / −${r.removed}</summary>
              <ul class="small changes">${r.added_items.map((i) => `<li class="yes">+ ${esc(i.title || i.rk)}</li>`).join("")}
                ${r.removed_items.map((i) => `<li class="no">− ${esc(i.title || i.rk)}</li>`).join("")}</ul></details>`
            : `+${r.added} / −${r.removed}`}${r.requested ? `<div class="small muted">${r.requested} requested</div>` : ""}</td>
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
            ${h.custom ? `<div class="small"><span class="badge">yours</span>
              <button type="button" class="small" data-edit-holiday="${esc(h.key)}">Edit holiday</button>
              <button type="button" class="small danger" data-del-holiday="${esc(h.key)}">Delete holiday</button></div>` : ""}
          </div>
        </div>`;
    }).join("");

    view.innerHTML = `
      <div class="page-head"><h1>Holiday collections</h1>
        <div class="actions"><button class="primary" id="addHoliday">+ Add holiday</button></div></div>
      <div id="holidayForm" class="card" hidden></div>
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
    view.querySelector("#addHoliday").onclick = () => holidayForm(null);
    view.querySelectorAll("[data-edit-holiday]").forEach((b) => b.onclick = () =>
      holidayForm(list.find((h) => h.key === b.dataset.editHoliday)));
    view.querySelectorAll("[data-del-holiday]").forEach((b) => b.onclick = () => guard(async () => {
      const h = list.find((x) => x.key === b.dataset.delHoliday);
      if (!confirm(`Delete ${h.name}? Its collections are removed from Curatarr too.`)) return;
      const fromPlex = h.collections.length
        && confirm("Also delete its collections from Plex?\n\nOK = delete them in Plex too, Cancel = keep them in Plex.");
      const r = await api("DELETE", `/holidays/custom/${h.key}?remove_from_plex=${Boolean(fromPlex)}`);
      toast(r.message || `${h.name} deleted`, Boolean(r.message));
      route();
    }));
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

// Add or edit one of your own holidays: name, dates, TMDB link and poster colours.
async function holidayForm(h) {
  const box = view.querySelector("#holidayForm");
  const schemes = state.schemes ||= await api("GET", "/holidays/schemes");
  const scheme = h?.scheme || "royal";
  box.hidden = false;
  box.innerHTML = `
    <h2>${h ? `Edit ${esc(h.name)}` : "Add a holiday"}</h2>
    <div class="grid">
      <div><label for="hName">Name</label><input type="text" id="hName" value="${esc(h?.name || "")}" placeholder="Earth Day"></div>
      <div><label for="hStart">From</label><input type="date" id="hStart" value="${h ? `2000-${esc(h.start)}` : ""}"></div>
      <div><label for="hEnd">Until (inclusive)</label><input type="date" id="hEnd" value="${h ? `2000-${esc(h.end)}` : ""}">
        <div class="hint">Only the month and day are used; it repeats every year.</div></div>
      <div class="full"><label for="hLink">TMDB keyword or list link</label>
        <input type="url" id="hLink" value="${esc(h?.link || "")}" placeholder="https://www.themoviedb.org/keyword/…">
        <div class="hint">Find a keyword on themoviedb.org (search, then Keywords) and paste its page link. Its 100 most popular movies are used.</div></div>
      <div class="full"><label>Poster colours</label><div class="swatches">${Object.entries(schemes).map(([key, c]) => `
        <label class="swatch" title="${esc(key)}"><input type="radio" name="hScheme" value="${esc(key)}" ${key === scheme ? "checked" : ""}>
          <span style="background:linear-gradient(${esc(c.top)}, ${esc(c.bottom)})"><i style="background:${esc(c.icon)}"></i></span></label>`).join("")}
      </div></div>
    </div>
    <div class="row" style="margin-top:12px">
      <button type="button" class="primary" id="hSave">${h ? "Save" : "Add holiday"}</button>
      <button type="button" id="hCancel">Cancel</button>
    </div>`;
  box.scrollIntoView({ behavior: "smooth", block: "start" });
  box.querySelector("#hCancel").onclick = () => { box.hidden = true; };
  box.querySelector("#hSave").onclick = () => guard(async () => {
    const md = (sel) => box.querySelector(sel).value.slice(5);     // YYYY-MM-DD -> MM-DD
    const body = {
      name: box.querySelector("#hName").value, start: md("#hStart"), end: md("#hEnd"),
      link: box.querySelector("#hLink").value, scheme: box.querySelector("[name=hScheme]:checked")?.value,
    };
    await (h ? api("PUT", `/holidays/custom/${h.key}`, body) : api("POST", "/holidays/custom", body));
    toast(h ? `${body.name} saved` : `${body.name} added. Tick it to create its collection`);
    route();
  });
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
// Poster overlays: how many posters Curatarr changed, with redraw and remove-all.
// Settings sub-pages: Poster overlays and Napalm.
async function overlaysPage() {
  view.innerHTML = `<div class="page-head"><h1>Poster overlays</h1></div><div class="card" id="overlayCard"></div>`;
  await overlayCard(view.querySelector("#overlayCard"));
}

async function napalmPage() {
  view.innerHTML = `<div class="page-head"><h1>Napalm</h1></div><div class="card napalm" id="napalmCard"></div>`;
  await napalmCard(view.querySelector("#napalmCard"));
}

async function overlayCard(card) {
  const o = await api("GET", "/overlays").catch(() => null);
  if (!o) { card.hidden = true; return; }
  card.innerHTML = `
    <h2>Posters with overlays</h2>
    <p class="hint" style="margin-top:-6px">Ribbons and badges are set per collection, under <strong>Poster overlays</strong> in its settings.
      Titles with an overlay get the Plex label <span class="mono">${esc(o.label)}</span>; their original posters are kept in the config folder.</p>
    <p>${o.posters} poster${o.posters === 1 ? "" : "s"} with overlays, from ${o.collections.length} collection${o.collections.length === 1 ? "" : "s"}.</p>
    <div class="row">
      <button type="button" id="ovApply">Update overlays now</button>
      <button type="button" class="danger" id="ovRemove" ${o.posters ? "" : "disabled"}>Remove all overlays</button>
    </div>`;
  libraryBadges(card);
  card.querySelector("#ovApply").onclick = () => guard(async () => {
    await api("POST", "/overlays/apply");
    toast("Updating overlays in the background; see Logs for progress");
  });
  card.querySelector("#ovRemove").onclick = () => guard(async () => {
    if (!confirm("Put every original poster back and turn off all ribbons and badges?")) return;
    await api("POST", "/overlays/apply?remove_all=true");
    toast("Restoring original posters in the background");
  });
}

// Badges on every movie or show in a library, not just those in a collection.
async function libraryBadges(card) {
  const [libs, saved] = await Promise.all([libraries().catch(() => []), api("GET", "/overlays/libraries").catch(() => ({}))]);
  if (!libs.length) return;
  const box = document.createElement("div");
  box.className = "library-badges";
  const row = (l) => {
    const b = saved[l.id] || {};
    return `
      <div class="library-badge" data-lib="${esc(l.id)}">
        <div class="lib-name"><strong>${esc(l.title)}</strong> <span class="muted small">(${l.type === "show" ? "TV" : "Movies"})</span></div>
        <label class="check"><input type="checkbox" data-k="content_rating" ${b.content_rating ? "checked" : ""}> Content rating</label>
        ${l.type === "movie" ? `<label class="check"><input type="checkbox" data-k="quality" ${b.quality ? "checked" : ""}> Quality</label>` : ""}
        <select data-k="rating" title="Rating badge">
          <option value="">No rating badge</option>
          <option value="audience" ${b.rating === "audience" ? "selected" : ""}>Audience rating</option>
          <option value="critic" ${b.rating === "critic" ? "selected" : ""}>Critic rating</option></select>
        <button type="button" class="small" data-lib-preview>Preview</button>
      </div>`;
  };
  box.innerHTML = `
    <h3 style="margin:18px 0 6px">Whole libraries</h3>
    <p class="hint" style="margin-top:0">Badges on <strong>every</strong> movie or show in a library, not just those in a collection.
      Titles also in a collection with badges get them combined, not twice.
      The first update draws one poster per title, which takes a while for a big library (roughly an hour for 5,000 titles);
      progress shows in the top bar. Turning a library off puts its original posters back.</p>
    ${libs.map(row).join("")}
    <div class="row" style="margin-top:10px"><button type="button" class="primary" id="libSave">Save library badges</button>
      <div class="overlay-preview image-box" id="libPreview" hidden></div></div>`;
  card.appendChild(box);
  const read = (el) => ({
    content_rating: el.querySelector('[data-k="content_rating"]').checked,
    quality: Boolean(el.querySelector('[data-k="quality"]')?.checked),
    rating: el.querySelector('[data-k="rating"]').value, rating_min: 0,
  });
  box.querySelectorAll("[data-lib-preview]").forEach((b) => b.onclick = () => guard(async () => {
    const el = b.closest("[data-lib]");
    const out = box.querySelector("#libPreview");
    out.hidden = false;
    out.textContent = "…";
    const resp = await api("POST", "/overlays/preview", { badges: read(el), section_id: el.dataset.lib }, true);
    if (!resp.ok) { out.textContent = "▦"; throw new Error(`Preview failed (HTTP ${resp.status})`); }
    out.innerHTML = `<img src="${URL.createObjectURL(await resp.blob())}" alt="Badge preview">`;
  }));
  box.querySelector("#libSave").onclick = () => guard(async () => {
    const body = {};
    box.querySelectorAll("[data-lib]").forEach((el) => {
      const b = read(el);
      if (b.content_rating || b.quality || b.rating) body[el.dataset.lib] = b;
    });
    const added = Object.keys(body).filter((k) => !saved[k]);
    if (added.length && !confirm(`Draw badges on every title in ${libs.filter((l) => added.includes(l.id)).map((l) => l.title).join(", ")}?\n\n`
      + "Each title's poster is redrawn, which takes a while for big libraries. The original posters are kept and put back if you turn this off.")) return;
    Object.assign(saved, body);
    Object.keys(saved).forEach((k) => { if (!body[k]) delete saved[k]; });
    await api("PUT", "/overlays/libraries", body);
    toast("Library badges saved. Posters update in the background; progress is in the top bar.");
  });
}

// What napalm turns off: a collection, or a library's library-wide badges (id null).
function napalmTarget(c, libs) {
  if (c.id === null || c.id === undefined) {
    const lib = (libs || []).find((l) => l.id === c.library);
    return `Library-wide badges <span class="muted">(${esc(lib?.title || c.library)})</span>`;
  }
  return `<a href="#/collections/${c.id}">${esc(c.name)}</a> <span class="muted">(${esc(c.library)})</span>`;
}

// "I love the smell of napalm in the morning": a fresh poster for every title.
async function napalmCard(card) {
  const libs = await libraries().catch(() => []);
  if (!libs.length) { card.hidden = true; return; }
  card.innerHTML = `
    <h2>I love the smell of napalm in the morning</h2>
    <p class="hint" style="margin-top:-6px">Gives every movie and show in the libraries you pick a fresh poster: the first proper
      (tall, 2:3) poster from Plex's metadata sources, such as TMDB. Wide images like video frames are skipped. Use it to clear out posters with old overlays or artwork from other tools.</p>
    <div class="notice napalm-warning">
      <strong>Before you light it up:</strong>
      <ul>
        <li>Every title's poster changes, <strong>including posters you picked by hand</strong> in Plex.</li>
        <li>Nothing is deleted: the old posters stay in each title's poster list in Plex (Edit → Poster), where you can pick them again.
          Curatarr can't undo it in one click.</li>
        <li><strong>Curatarr's own poster overlays are turned off</strong> (ribbon, badges and fresh poster) on every
          collection in these libraries, so the new posters stay clean. You can turn them back on in each collection's settings.</li>
        <li>Big libraries take a while, about one Plex request or two per title. You can stop it part way.</li>
        <li>Everyone using your server sees the new posters.</li>
        <li>Titles labelled <strong>Curatarr Keep Poster</strong> are skipped. Set it on fan edits and custom posters
          from <a href="#/unmatched">Unmatched and Fan Edits</a>.</li>
      </ul>
    </div>
    <div id="napalmLast"></div>
    <div class="row" style="gap:16px;margin:10px 0">${libs.map((l) => `
      <label class="check"><input type="checkbox" data-napalm-lib value="${esc(l.id)}">
        ${esc(l.title)} (${l.type === "show" ? "TV" : "Movies"})<span class="muted small" data-napalm-count="${esc(l.id)}"></span></label>`).join("")}</div>
    <div class="row">
      <button type="button" id="napalmPreview">Preview</button>
      <label class="check"><input type="checkbox" id="napalmAgree"> I understand every poster in these libraries will change</label>
      <button type="button" class="danger" id="napalmRun" disabled>Refresh every poster</button>
      <button type="button" id="napalmStop" hidden>Stop</button>
    </div>
    <div id="napalmAffected" class="small"></div>
    <div id="napalmOut"></div>`;
  const picked = () => [...card.querySelectorAll("[data-napalm-lib]:checked")].map((b) => b.value);
  const run = card.querySelector("#napalmRun");
  const agree = card.querySelector("#napalmAgree");
  const update = () => { run.disabled = !(agree.checked && picked().length); };
  // Which collections lose their overlays, for the libraries ticked.
  const showAffected = async () => {
    const el = card.querySelector("#napalmAffected");
    card.querySelectorAll("[data-napalm-count]").forEach((s) => {
      if (!picked().includes(s.dataset.napalmCount)) s.textContent = "";
    });
    if (!picked().length) { el.innerHTML = ""; return; }
    const params = new URLSearchParams();
    picked().forEach((s) => params.append("section", s));
    el.innerHTML = `<p class="muted" style="margin:10px 0 0">Counting titles…</p>`;
    const r = await api("GET", `/napalm/affected?${params}`).catch(() => ({ libraries: [], collections: [] }));
    const plural = (n, kind) => `${n.toLocaleString()} ${kind === "show" ? (n === 1 ? "TV show" : "TV shows") : (n === 1 ? "movie" : "movies")}`;
    r.libraries.forEach((l) => {
      const span = card.querySelector(`[data-napalm-count="${l.id}"]`);
      if (span) span.textContent = ` · ${plural(l.count, l.type)}`;
    });
    const byType = {};
    r.libraries.forEach((l) => { byType[l.type] = (byType[l.type] || 0) + l.count; });
    const total = Object.entries(byType).map(([type, n]) => plural(n, type)).join(" and ");
    el.innerHTML = `
      <p style="margin:10px 0 0"><strong>${total || "No titles"}</strong> will be checked. Only titles not already on their fresh poster change.</p>
      ${r.collections.length
        ? `<div class="notice" style="margin:10px 0 0">Poster overlays will be turned off on: ${r.collections.map((c) =>
            napalmTarget(c, libs)).join(", ")}.</div>`
        : `<p class="muted" style="margin:6px 0 0">No collections in these libraries have poster overlays.</p>`}`;
  };
  napalmLastRun(card.querySelector("#napalmLast"));
  card.querySelectorAll("[data-napalm-lib]").forEach((b) => b.onchange = () => { update(); showAffected(); });
  agree.onchange = update;
  card.querySelector("#napalmPreview").onclick = (e) => guard(async () => {
    if (!picked().length) return toast("Pick at least one library", true);
    const out = card.querySelector("#napalmOut");
    e.target.disabled = true;
    out.innerHTML = `<p class="muted small">Picking some titles and looking up their fresh posters…</p>`;
    try {
      const params = new URLSearchParams();
      picked().forEach((s) => params.append("section", s));
      const sample = await api("GET", `/napalm/preview?${params}`);
      out.innerHTML = `
        <p class="small muted">${sample.filter((s) => s.status === "changes").length
          ? "Titles whose poster would change, starting with ones that have Curatarr overlays"
          : "No titles that would change turned up in this sample"}: current poster on the left, the one it would get on the right.
          ${sample.some((s) => s.status !== "changes") ? "Titles that keep their poster are shown last." : ""}
          Click <strong>Preview</strong> again for others.</p>
        <div class="napalm-grid">${sample.map((s) => `
          <div class="napalm-pair">
            <div class="napalm-imgs">
              <div class="item-poster">${s.current ? `<img loading="lazy" src="${esc(s.current)}" alt="Current poster">` : "▦"}</div>
              <span class="muted">→</span>
              <div class="item-poster">${s.fresh ? `<img loading="lazy" src="${esc(s.fresh)}" alt="Fresh poster" referrerpolicy="no-referrer">` : "—"}</div>
            </div>
            <div class="item-title" title="${esc(s.title)}">${esc(s.title)}${s.year ? ` <span class="muted">(${esc(s.year)})</span>` : ""}</div>
            <div class="small ${s.status === "changes" ? "" : "muted"}">${s.status === "changes"
              ? (s.overlay ? "Gets the new poster; its Curatarr overlay is removed" : "Gets the new poster") : esc(s.status)}</div>
          </div>`).join("")}</div>`;
    } catch (err) {
      out.innerHTML = `<p class="no">${esc(err.message)}</p>`;
    } finally {
      e.target.disabled = false;
    }
  });
  run.onclick = () => guard(async () => {
    const names = libs.filter((l) => picked().includes(l.id)).map((l) => l.title).join(", ");
    if (!confirm(`Give every title in ${names} a fresh poster?\n\nPosters you picked by hand are replaced too, and `
      + "Curatarr's poster overlays are turned off on the collections in these libraries. "
      + "The old posters stay in Plex's poster list, but Curatarr can't undo this in one click.")) return;
    activity.napalmStarted = Date.now();
    await api("POST", "/napalm/run", { section_ids: picked(), confirm: "napalm" });
    card.querySelector("#napalmAffected").innerHTML = "";
    toast("Refreshing posters in the background. Progress is in the top bar.");
    agree.checked = false;
    update();
  });
  card.querySelector("#napalmStop").onclick = () => guard(async () => {
    await api("POST", "/napalm/stop");
    toast("Stopping after the current title");
  });
}

// The current or last poster refresh, with the collections whose overlays it turned off.
async function napalmLastRun(el) {
  const n = await api("GET", "/napalm/last").catch(() => null);
  if (!el || !n || !n.finished || n.running) { if (el) el.innerHTML = ""; return; }
  el.innerHTML = `<div class="notice small" style="margin:10px 0 0">
    <strong>Last refresh</strong> (${esc(when(n.finished))}): ${n.changed} poster(s) changed, ${n.unchanged} already fresh,
    ${n.no_poster} without a source poster${n.kept ? `, ${n.kept} kept (Keep Poster label)` : ""}${n.errors ? `, ${n.errors} failed` : ""}.
    ${n.overlays_off.length ? `<br>Poster overlays were turned off on: ${n.overlays_off.map((c) =>
      napalmTarget(c, state.libraries)).join(", ")}.` : ""}</div>`;
}

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
pollActivity();
