"""REST API used by the web UI (and available for scripting)."""
import logging
import os
from datetime import date, datetime
from pathlib import Path

import httpx
import yaml
from fastapi import APIRouter, Body, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import ValidationError

from . import arr, config, db, holidays, logs, packs, plex as plexmod, plextv, scheduler, sources, sync
from .models import CollectionConfig, PreviewRequest
from .plex import PlexError
from .sources import SourceContext, SourceError
from .sources.tmdb import TMDB, _first_number

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

MASK = "********"
IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def _plex():
    try:
        return plexmod.from_settings(db.get_settings())
    except PlexError as exc:
        raise HTTPException(400, str(exc))


def _validate(cfg: dict) -> CollectionConfig:
    try:
        model = CollectionConfig(**cfg)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False, include_context=False))
    if model.schedule:
        try:
            scheduler.validate_cron(model.schedule)
        except ValueError as exc:
            raise HTTPException(422, f"Invalid schedule: {exc}")
    return model


def _collection_out(row: dict) -> dict:
    return {
        **row,
        "next_run": scheduler.next_run(row["id"]),
        "running": sync.is_running(row["id"]),
    }


# --- status -------------------------------------------------------------------

@router.get("/health")
def health():
    return {"status": "ok", "version": config.VERSION}


@router.get("/status")
def status():
    settings = db.get_settings()
    result = {"version": config.VERSION, "collections": len(db.list_collections()),
              "plex": None, "plex_error": None}
    if settings.get("plex_url") and settings.get("plex_token"):
        try:
            with plexmod.from_settings(settings, timeout=10) as plex:
                result["plex"] = plex.server_info()
        except PlexError as exc:
            result["plex_error"] = str(exc)
    else:
        result["plex_error"] = "Plex is not configured"
    return result


@router.get("/sources")
def source_catalog():
    return sources.CATALOG


# --- settings -----------------------------------------------------------------

@router.get("/settings")
def get_settings():
    values = db.get_settings()
    values.pop(config.PLEX_CLIENT_ID_KEY, None)
    from_env = [k for k, env in config.ENV_SETTINGS.items()
                if values.get(k) and values[k] == os.environ.get(env)]
    for key in config.SECRET_SETTINGS:
        if values.get(key):
            values[key] = MASK
    return {"values": values, "from_env": from_env}


@router.put("/settings")
def put_settings(values: dict[str, str] = Body(...)):
    allowed = set(config.DEFAULT_SETTINGS)
    clean = {k: v.strip() for k, v in values.items() if k in allowed and v != MASK}
    if clean.get("default_schedule"):
        try:
            scheduler.validate_cron(clean["default_schedule"])
        except ValueError as exc:
            raise HTTPException(422, f"Invalid default schedule: {exc}")
    if "plex_url" in clean:
        clean["plex_url"] = clean["plex_url"].rstrip("/")
    db.save_settings(clean)
    sync.clear_index_cache()
    scheduler.reload_jobs()
    return get_settings()


@router.post("/settings/test/{service}")
def test_service(service: str):
    settings = db.get_settings()
    try:
        if service == "plex":
            with plexmod.from_settings(settings, timeout=10) as plex:
                info = plex.server_info()
                return {"ok": True, "message": f"Connected to {info['name']} (v{info['version']})"}
        with httpx.Client(timeout=20) as http:
            if service == "tmdb":
                TMDB(settings.get("tmdb_api_key", ""), http).get("configuration")
                return {"ok": True, "message": "TMDB key is valid"}
            if service == "trakt":
                sources.trakt.fetch_chart("movies/trending",
                                          SourceContext(settings, http, "movie"), 1)
                return {"ok": True, "message": "Trakt client id is valid"}
            if service == "mdblist":
                resp = http.get("https://api.mdblist.com/user",
                                params={"apikey": settings.get("mdblist_api_key", "")})
                if resp.status_code >= 400:
                    raise SourceError(f"MDBList returned HTTP {resp.status_code}")
                return {"ok": True, "message": "MDBList key is valid"}
            if service in ("radarr", "sonarr"):
                info = arr.Arr(service, settings, http).status()
                return {"ok": True, "message": f"Connected to {service.title()} v{info.get('version')}"}
    except (PlexError, SourceError, arr.ArrError, httpx.HTTPError) as exc:
        return {"ok": False, "message": str(exc)}
    raise HTTPException(404, f"Unknown service '{service}'")


@router.get("/arr/{kind}/options")
def arr_options(kind: str):
    if kind not in ("radarr", "sonarr"):
        raise HTTPException(404)
    try:
        with httpx.Client(timeout=20) as http:
            return arr.Arr(kind, db.get_settings(), http).options()
    except (arr.ArrError, httpx.HTTPError, ValueError) as exc:
        raise HTTPException(400, str(exc))


# --- plex ---------------------------------------------------------------------

def _primary_first(sections: list[dict]) -> list[dict]:
    """Libraries with the primary movie and TV libraries (Settings) first, so pickers start on them."""
    settings = db.get_settings()
    primary = [settings.get("primary_movie_library"), settings.get("primary_tv_library")]
    rank = lambda s: primary.index(s["id"]) if s["id"] in primary else len(primary)  # noqa: E731
    return [{**s, "primary": s["id"] in primary} for s in sorted(sections, key=rank)]


@router.get("/plex/libraries")
def plex_libraries():
    with _plex() as plex:
        try:
            return _primary_first(plex.sections())
        except PlexError as exc:
            raise HTTPException(502, str(exc))


@router.get("/plex/libraries/{section_id}/collections")
def plex_collections(section_id: str):
    with _plex() as plex:
        try:
            return plex.collections(section_id)
        except PlexError as exc:
            raise HTTPException(502, str(exc))


@router.get("/plex/libraries/{section_id}/filters")
def plex_filters(section_id: str):
    """Choices for the Plex filter builder. Fields a library doesn't have come back empty."""
    out = {}
    with _plex() as plex:
        # No actor list: big libraries have tens of thousands of actors.
        for field in ("genre", "director", "contentRating", "studio"):
            try:
                out[field] = sorted(plex.filter_values(section_id, field), key=lambda v: v["title"].lower())
            except PlexError as exc:
                if exc.status in (400, 404):
                    out[field] = []
                else:
                    raise HTTPException(502, str(exc))
    return out


@router.get("/plex/collections")
def plex_all_collections():
    """Every collection in Plex, marked with the Curatarr collection that manages it (if any)."""
    rows = [r for r in db.list_collections() if r["config"].get("kind", "collection") == "collection"]
    by_key = {str(r["plex_rating_key"]): r["id"] for r in rows if r.get("plex_rating_key")}
    by_title = {(str(r["config"].get("section_id")), r["config"]["name"].strip().lower()): r["id"]
                for r in rows}
    result = []
    with _plex() as plex:
        try:
            for section in _primary_first(plex.sections()):
                for coll in plex.collections(section["id"]):
                    managed = by_key.get(coll["ratingKey"]) or by_title.get(
                        (section["id"], (coll["title"] or "").strip().lower()))
                    result.append({**coll, "section_id": section["id"],
                                   "section_title": section["title"],
                                   "section_type": section["type"], "managed_id": managed})
        except PlexError as exc:
            raise HTTPException(502, str(exc))
    return result


@router.get("/plex/collections/{rating_key}/items")
def plex_collection_items(rating_key: str):
    with _plex() as plex:
        try:
            return plex.collection_contents(rating_key)
        except PlexError as exc:
            raise HTTPException(404 if exc.status == 404 else 502, str(exc))


@router.get("/plex/playlists")
def plex_all_playlists():
    """Video playlists of the Plex account Curatarr uses, marked when Curatarr manages one."""
    rows = [r for r in db.list_collections() if r["config"].get("kind") == "playlist"]
    by_key = {str(r["plex_rating_key"]): r["id"] for r in rows if r.get("plex_rating_key")}
    by_title = {r["config"]["name"].strip().lower(): r["id"] for r in rows}
    with _plex() as plex:
        try:
            return [{**p, "managed_id": by_key.get(p["ratingKey"]) or by_title.get((p["title"] or "").strip().lower())}
                    for p in plex.playlists()]
        except PlexError as exc:
            raise HTTPException(502, str(exc))


@router.get("/plex/playlists/{rating_key}/items")
def plex_playlist_items(rating_key: str):
    with _plex() as plex:
        try:
            return plex.playlist_contents(rating_key)
        except PlexError as exc:
            raise HTTPException(404 if exc.status == 404 else 502, str(exc))


@router.get("/tmdb/posters")
def tmdb_posters(query: str = "", collection: list[str] = Query(default=[])):
    """Poster choices from TMDB for a collection's name or TMDB franchise ids/links."""
    ids = []
    for value in collection:
        try:
            ids.append(_first_number(value, r"/collection/(\d+)"))
        except SourceError:
            continue
    try:
        with httpx.Client(timeout=20) as http:
            return TMDB(db.get_settings().get("tmdb_api_key", ""), http).poster_choices(query, ids)
    except SourceError as exc:
        raise HTTPException(400, str(exc))


@router.get("/plex/image")
def plex_image(path: str):
    with _plex() as plex:
        try:
            data, content_type = plex.image(path)
        except PlexError as exc:
            raise HTTPException(404, str(exc))
    return Response(data, media_type=content_type, headers={"Cache-Control": "max-age=3600"})


@router.post("/plex/auth/pin")
def plex_pin():
    try:
        return plextv.create_pin(db.plex_client_identifier())
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"plex.tv: {exc}")


@router.get("/plex/auth/pin/{pin_id}")
def plex_pin_check(pin_id: int):
    client_id = db.plex_client_identifier()
    try:
        token = plextv.check_pin(client_id, pin_id)
        if not token:
            return {"authorized": False}
        return {"authorized": True, "token": token,
                "servers": plextv.servers(client_id, token)}
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"plex.tv: {exc}")


# --- collections --------------------------------------------------------------

@router.get("/collections")
def list_collections():
    return [_collection_out(r) for r in db.list_collections()]


@router.post("/collections", status_code=201)
def create_collection(cfg: dict = Body(...), plex_rating_key: str = ""):
    """Create a collection. ``plex_rating_key`` links it to an existing Plex collection."""
    model = _validate(cfg)
    collection_id = db.create_collection(model.model_dump())
    if plex_rating_key:     # linked on purpose via "Sync with a list"
        db.update_collection_state(collection_id, plex_rating_key=plex_rating_key, plex_owned=1)
    scheduler.reload_jobs()
    return _collection_out(db.get_collection(collection_id))


@router.get("/holidays")
def list_holidays():
    rows = db.list_collections()
    settings = db.get_settings()
    with httpx.Client() as http:
        arr_ready = {kind: arr.Arr(kind, settings, http).configured for kind in ("radarr", "sonarr")}
    result = []
    for h in holidays.all_holidays():
        colls = [_collection_out(r) for r in rows if r["config"].get("holiday") == h["key"]]
        poster = ""
        if h.get("custom"):
            poster = f"/api/holidays/{h['key']}/poster?v={h.get('scheme', '')}-{h['name']}"
        elif h.get("poster"):
            poster = f"/static/holidays/{h['poster']}"
        result.append({
            "key": h["key"], "name": h["name"], "start": h["start"], "end": h["end"],
            "link": h.get("link", ""), "arr_ready": arr_ready,
            "available": holidays.available(h), "custom": bool(h.get("custom")),
            "scheme": h.get("scheme", ""), "poster": poster, "collections": colls,
        })
    return result


@router.get("/holidays/schemes")
def holiday_schemes():
    from . import posters
    return posters.SCHEMES


@router.get("/holidays/{key}/poster")
def holiday_poster(key: str):
    holiday = holidays.get(key)
    path = holidays.poster_path(holiday) if holiday else None
    if not path:
        raise HTTPException(404, "No poster")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})


def _save_custom_holiday(entry: dict) -> dict:
    from . import posters
    try:
        stored = holidays.save_custom(entry)
    except (ValueError, posters.PosterError) as exc:
        raise HTTPException(422, str(exc))
    # Collections already made from this holiday follow its new dates and poster.
    holiday = holidays.get(stored["key"])
    start, end = holidays.window_dates(holiday)
    for row in db.list_collections():
        cfg = row["config"]
        if cfg.get("holiday") != stored["key"]:
            continue
        changes = {"promote_start": start, "promote_end": end}
        if cfg.get("poster_file") == f"{row['id']}-poster.jpg":
            holidays.install_poster(holiday, row["id"])
        db.update_collection_config(row["id"], {**cfg, **changes})
    scheduler.reload_jobs()
    return stored


@router.post("/holidays/custom", status_code=201)
def add_custom_holiday(body: dict = Body(...)):
    """Add your own holiday: name, start/end ("MM-DD"), TMDB keyword or list link, colour scheme."""
    return _save_custom_holiday({k: body.get(k) for k in ("name", "start", "end", "link", "scheme")})


@router.put("/holidays/custom/{key}")
def edit_custom_holiday(key: str, body: dict = Body(...)):
    return _save_custom_holiday({**{k: body.get(k) for k in ("name", "start", "end", "link", "scheme")},
                                 "key": key})


@router.delete("/holidays/custom/{key}")
def delete_custom_holiday(key: str, remove_from_plex: bool = False):
    """Delete one of your holidays and the collections made from it (like unticking it)."""
    if not key.startswith(holidays.CUSTOM_PREFIX) or not holidays.get(key):
        raise HTTPException(404, "Unknown holiday")
    messages = []
    for row in db.list_collections():
        if row["config"].get("holiday") == key:
            r = delete_collection(row["id"], remove_from_plex)
            if r.get("message"):
                messages.append(r["message"])
    holidays.delete_custom(key)
    return {"deleted": True, "message": "; ".join(messages) or None}


@router.post("/holidays/{key}/enable", status_code=201)
def enable_holiday(key: str, section_id: str = Body(..., embed=True),
                   request_missing: bool = Body(False, embed=True),
                   seasonal_only: bool = Body(False, embed=True)):
    """Create the holiday's collection.

    ``request_missing`` sends missing titles to Radarr/Sonarr; ``seasonal_only``
    keeps the Plex collection only during the holiday's dates.
    """
    holiday = holidays.get(key)
    if not holiday:
        raise HTTPException(404, "Unknown holiday")
    if not holidays.available(holiday):
        raise HTTPException(409, f"{holiday['name']} has no lists yet")
    for row in db.list_collections():
        if row["config"].get("holiday") == key and str(row["config"].get("section_id")) == section_id:
            raise HTTPException(409, f"{holiday['name']} is already on for that library")
    with _plex() as plex:
        try:
            section = sync.resolve_section(plex, section_id, "")
        except (PlexError, sync.SyncError) as exc:
            raise HTTPException(400, str(exc))
    model = _validate(holidays.collection_config(holiday, section, request_missing, seasonal_only))
    collection_id = db.create_collection(model.model_dump())
    poster = holidays.install_poster(holiday, collection_id)
    if poster:
        db.update_collection_config(collection_id, {**model.model_dump(), "poster_file": poster})
    scheduler.reload_jobs()
    scheduler.run_now(collection_id)
    return _collection_out(db.get_collection(collection_id))


@router.get("/dashboard")
def dashboard():
    """Overview from the database only (fast); watched counts come from /dashboard/watched."""
    rows = db.list_collections()
    latest = db.latest_runs()
    today = date.today()
    kinds = {"collections": 0, "holidays": 0, "playlists": 0, "overlays": 0}
    attention, coming, missing_rank = [], [], []
    titles = missing = 0
    for r in rows:
        cfg = r["config"]
        kind = "playlists" if cfg.get("kind") == "playlist" else "overlays" if cfg.get("kind") == "overlay" \
            else "holidays" if cfg.get("holiday") else "collections"
        kinds[kind] += 1
        run = latest.get(r["id"])
        brief = {"id": r["id"], "name": cfg["name"], "kind": kind}
        if run:
            titles += run["matched"] or 0
            missing += len(run["missing"])
            if run["missing"]:
                missing_rank.append({**brief, "missing": len(run["missing"]), "matched": run["matched"]})
        if r.get("last_status") in ("error", "warning") or not cfg.get("enabled", True):
            attention.append({**brief, "status": r.get("last_status") if cfg.get("enabled", True) else "paused",
                              "message": r.get("last_message") or "", "when": r.get("last_run")})
        try:
            change = sync.next_calendar_change(CollectionConfig(**cfg), today)
        except (ValidationError, ValueError):
            change = None
        if change:
            day, appears = change
            entry = {**brief, "date": day.isoformat(), "appears": appears,
                     "seasonal": bool(cfg.get("seasonal_only")), "library": cfg.get("library", ""),
                     "start": cfg.get("promote_start"), "end": cfg.get("promote_end"),
                     "yearly": cfg.get("promote_yearly", True)}
            # The same collection on the same dates in several libraries is one entry.
            same = next((c for c in coming if all(c[k] == entry[k] for k in
                         ("name", "date", "appears", "seasonal", "start", "end"))), None)
            if same:
                if entry["library"] and entry["library"] not in same["libraries"]:
                    same["libraries"].append(entry["library"])
            else:
                coming.append({**entry, "libraries": [entry["library"]] if entry["library"] else []})
    recent = [{k: v for k, v in run.items() if k not in ("missing", "added_items", "removed_items")}
              | {"missing": len(run["missing"])} for run in db.list_runs(limit=10)]
    return {
        "counts": {**kinds, "titles": titles, "missing": missing,
                   "enabled": sum(1 for r in rows if r["config"].get("enabled", True))},
        "attention": attention,
        "coming": sorted(coming, key=lambda c: c["date"])[:5],
        "most_missing": sorted(missing_rank, key=lambda m: -m["missing"])[:5],
        "recent": recent,
    }


@router.get("/dashboard/watched")
def dashboard_watched():
    """How much of each collection and playlist has been watched (asks Plex; slower)."""
    out, watched, total = {}, 0, 0
    with _plex() as plex:
        for r in db.list_collections():
            if not r.get("plex_rating_key"):
                continue
            try:
                items = (plex.playlist_contents if r["config"].get("kind") == "playlist"
                         else plex.collection_contents)(r["plex_rating_key"])
            except PlexError:
                continue
            seen = sum(1 for i in items if i["watched"])
            out[r["id"]] = {"watched": seen, "total": len(items)}
            watched, total = watched + seen, total + len(items)
    return {"watched": watched, "total": total, "collections": out}


@router.get("/packs")
def list_packs(media: str = "movie"):
    """Starter packs for a library type, with the libraries each item already exists in."""
    names: dict[str, list[str]] = {}
    for r in db.list_collections():
        names.setdefault(r["config"]["name"].strip().lower(), []).append(str(r["config"].get("section_id")))
    return [{**pack, "items": [{**item, "in_libraries": names.get(item["name"].lower(), [])}
                               for item in pack["items"]]}
            for pack in packs.PACKS if pack["media"] == media]


@router.post("/packs", status_code=201)
def create_from_packs(body: dict = Body(...)):
    keys = body.get("keys") or []
    if not keys:
        raise HTTPException(422, "Pick at least one collection")
    with _plex() as plex:
        try:
            section = sync.resolve_section(plex, str(body.get("section_id") or ""), "")
        except (PlexError, sync.SyncError) as exc:
            raise HTTPException(400, str(exc))
    existing = {(r["config"]["name"].strip().lower(), str(r["config"].get("section_id")))
                for r in db.list_collections()}
    created, skipped = [], []
    for key in keys:
        if key not in packs.ITEMS:
            raise HTTPException(404, f"Unknown starter pack item '{key}'")
        pack, item = packs.ITEMS[key]
        if pack["media"] != section["type"]:
            raise HTTPException(422, f"'{item['name']}' is for {pack['media']} libraries")
        if (item["name"].lower(), section["id"]) in existing:
            skipped.append(item["name"])
            continue
        cfg = _validate(packs.collection_config(item, section, body.get("sync_mode") or "sync",
                                                bool(body.get("request_missing"))))
        created.append(db.create_collection(cfg.model_dump()))
    scheduler.reload_jobs()
    if body.get("sync_now"):
        for cid in created:
            scheduler.run_now(cid)
    log.info("Starter packs: created %d collection(s) in '%s'", len(created), section["title"])
    return {"created": len(created), "skipped": skipped}


@router.post("/collections/run-all")
def run_all():
    rows = [r for r in db.list_collections() if r["config"].get("enabled", True)]
    for row in rows:
        scheduler.run_now(row["id"])
    return {"queued": len(rows)}


@router.get("/collections/{collection_id}")
def get_collection(collection_id: int):
    row = db.get_collection(collection_id)
    if not row:
        raise HTTPException(404, "Collection not found")
    return _collection_out(row)


@router.put("/collections/{collection_id}")
def update_collection(collection_id: int, cfg: dict = Body(...)):
    row = db.get_collection(collection_id)
    if not row:
        raise HTTPException(404, "Collection not found")
    # Image files are managed by the upload endpoints.
    cfg["poster_file"] = row["config"].get("poster_file", "")
    cfg["art_file"] = row["config"].get("art_file", "")
    model = _validate(cfg)
    db.update_collection_config(collection_id, model.model_dump())
    scheduler.reload_jobs()
    before = CollectionConfig(**row["config"])
    if (model.ribbon, model.badges, model.fresh_poster) != (before.ribbon, before.badges, before.fresh_poster):
        scheduler.run_task(sync.run_overlays, "Poster overlays")     # draw or remove it now
    return _collection_out(db.get_collection(collection_id))


@router.delete("/collections/{collection_id}")
def delete_collection(collection_id: int, remove_from_plex: bool = False):
    row = db.get_collection(collection_id)
    if not row:
        raise HTTPException(404, "Collection not found")
    message = None
    if remove_from_plex and row.get("plex_rating_key"):
        try:
            with _plex() as plex:
                if row["config"].get("kind") == "playlist":
                    plex.delete_playlist(row["plex_rating_key"])
                else:
                    section = sync.resolve_section(plex, row["config"].get("section_id"),
                                                   row["config"].get("library"))
                    plex.delete_collection(section["id"], row["plex_rating_key"])
        except (PlexError, sync.SyncError) as exc:
            message = f"Removed from Curatarr, but Plex deletion failed: {exc}"
    for kind in ("poster_file", "art_file"):
        if row["config"].get(kind):
            (config.IMAGE_DIR / row["config"][kind]).unlink(missing_ok=True)
    db.delete_collection(collection_id)
    scheduler.reload_jobs()
    if row["config"].get("ribbon", {}).get("enabled") or any((row["config"].get("badges") or {}).values()) \
            or row["config"].get("fresh_poster"):
        scheduler.run_task(sync.run_overlays, "Poster overlays")     # put the original posters back
    return {"deleted": True, "message": message}


@router.get("/collections/{collection_id}/items")
def collection_items(collection_id: int):
    """What's in a Curatarr collection's Plex collection right now."""
    row = db.get_collection(collection_id)
    if not row:
        raise HTTPException(404, "Collection not found")
    if row["config"].get("kind") == "overlay":     # a list overlay: the titles it found
        if not row.get("members"):
            return {"in_plex": False, "items": []}
        with _plex() as plex:
            try:
                items = plex.items_contents(row["members"])
            except PlexError as exc:
                raise HTTPException(502, str(exc))
        overlaid = db.overlay_rows()
        for item in items:
            item["overlay"] = item["ratingKey"] in overlaid
        return {"in_plex": True, "items": items}
    if not row.get("plex_rating_key"):
        return {"in_plex": False, "items": []}
    with _plex() as plex:
        try:
            contents = plex.playlist_contents if row["config"].get("kind") == "playlist"                 else plex.collection_contents
            items = contents(row["plex_rating_key"])
            overlaid = db.overlay_rows()
            for item in items:            # so the View page can show which posters have overlays
                item["overlay"] = item["ratingKey"] in overlaid
            return {"in_plex": True, "items": items}
        except PlexError as exc:
            if exc.status == 404:    # deleted in Plex, or removed off season
                return {"in_plex": False, "items": []}
            raise HTTPException(502, str(exc))


@router.get("/collections/{collection_id}/planned")
def collection_planned(collection_id: int):
    """What a collection that isn't in Plex right now (e.g. off season) would contain."""
    if not db.get_collection(collection_id):
        raise HTTPException(404, "Collection not found")
    try:
        return sync.planned_contents(collection_id)
    except (PlexError, sync.SyncError) as exc:
        raise HTTPException(400, str(exc))


@router.post("/collections/{collection_id}/exclude")
def exclude_title(collection_id: int, body: dict = Body(...)):
    """Keep a title out of a collection for good, and take it out of Plex now."""
    row = db.get_collection(collection_id)
    if not row:
        raise HTTPException(404, "Collection not found")
    ident = str(body.get("id") or "").strip()
    if not ident:
        raise HTTPException(422, "id is required")
    cfg = row["config"]
    if any(e["id"] == ident for e in cfg.get("exclude") or []):
        return _collection_out(row)
    cfg["exclude"] = [*(cfg.get("exclude") or []), {"id": ident, "title": body.get("title") or ""}]
    db.update_collection_config(collection_id, _validate(cfg).model_dump())
    if ident.startswith("plex:") and row.get("plex_rating_key"):
        with _plex() as plex:
            try:
                sync.remove_titles(plex, CollectionConfig(**cfg), row["plex_rating_key"], [ident[5:]])
            except PlexError as exc:
                raise HTTPException(502, f"Excluded, but removing it from Plex failed: {exc}")
    return _collection_out(db.get_collection(collection_id))


@router.post("/collections/{collection_id}/request")
def request_title(collection_id: int, body: dict = Body(...)):
    """Send one missing title to Radarr (movie libraries) or Sonarr (TV libraries)."""
    row = db.get_collection(collection_id)
    if not row:
        raise HTTPException(404, "Collection not found")
    kind = "sonarr" if body.get("media_type") == "show" else "radarr"
    fields = {k: body.get(k) for k in ("title", "year", "imdb", "tmdb", "tvdb")}
    ref = sources.MediaRef(media_type=body.get("media_type"), **{k: v for k, v in fields.items() if v})
    settings = db.get_settings()
    with httpx.Client(timeout=30) as http:
        client = arr.Arr(kind, settings, http, row["config"].get("section_id"))   # that library's root folder
        if not client.configured:
            raise HTTPException(400, f"{kind.title()} isn't set up in Settings")
        try:
            outcome = client.add(ref)
        except arr.ArrError as exc:
            raise HTTPException(502, str(exc))
    if outcome == "not_found":
        raise HTTPException(404, f"{kind.title()} couldn't find this title")
    log.info("%s: %s %s (requested by hand)", kind.title(), outcome, ref.title or ref.imdb or ref.tmdb)
    return {"status": outcome, "service": kind}


@router.get("/overlays")
def overlay_status():
    from . import overlays
    rows = db.overlay_rows()
    return {"posters": len(rows), "label": overlays.LABEL,
            "collections": [r["id"] for r in db.list_collections()
                            if overlays.uses_overlays(CollectionConfig(**r["config"]))]}


@router.get("/overlays/progress")
def overlay_progress():
    """Background work for the web UI's indicator: running syncs, and the overlay pass's progress."""
    from . import overlays
    syncing = [r["config"]["name"] for r in db.list_collections() if sync.is_running(r["id"])]
    from . import napalm
    return {**overlays.progress, "queued": overlays._again.is_set(), "syncing": syncing,
            "napalm": napalm.progress}


@router.get("/unmatched")
def unmatched_titles(refresh: bool = False):
    """Titles not tied to IMDb, TMDB or TVDB, in every library (cached for 10 minutes)."""
    from . import unmatched
    try:
        return unmatched.scan(refresh=refresh)
    except PlexError as exc:
        raise HTTPException(502, str(exc))


@router.post("/unmatched/keep")
def unmatched_keep(body: dict = Body(...)):
    """Add or remove the "Curatarr Keep Poster" label: {items: [{ratingKey, section_id, type}], keep}."""
    from . import unmatched
    items = body.get("items") or []
    if not items:
        raise HTTPException(422, "No titles given")
    try:
        done = unmatched.set_keep(items, bool(body.get("keep", True)))
    except PlexError as exc:
        raise HTTPException(502, str(exc))
    return {"updated": done, "label": unmatched.KEEP_LABEL}


@router.get("/prerolls")
def prerolls_overview():
    """Preroll settings, the preroll library's clips, and Plex's current list matched to them."""
    from . import prerolls
    try:
        return prerolls.overview()
    except (PlexError, prerolls.PrerollError) as exc:
        raise HTTPException(400, str(exc))


@router.get("/prerolls/library")
def prerolls_library():
    """The preroll library's id, so other pages can leave it out."""
    from . import prerolls
    with _plex() as plex:
        try:
            return {"section_id": prerolls.library_id(plex)}
        except PlexError as exc:
            raise HTTPException(502, str(exc))


@router.put("/prerolls")
def prerolls_save(body: dict = Body(...)):
    """Save preroll settings; when managing is on, Plex is updated right away."""
    from . import prerolls
    try:
        prerolls.save(body)
        result = prerolls.apply(force=True)
    except (PlexError, prerolls.PrerollError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    return {**prerolls.overview(), "result": result}


@router.post("/prerolls/restore")
def prerolls_restore():
    from . import prerolls
    try:
        prerolls.restore()
    except (PlexError, prerolls.PrerollError) as exc:
        raise HTTPException(400, str(exc))
    return prerolls.overview()


@router.get("/napalm/preview")
def napalm_preview(section: list[str] = Query(default=[])):
    """A sample of titles with their current poster and the fresh one they'd get."""
    from . import napalm
    try:
        return napalm.preview(section)
    except PlexError as exc:
        raise HTTPException(400, str(exc))


@router.get("/napalm/affected")
def napalm_affected(section: list[str] = Query(default=[])):
    """What a refresh of these libraries touches: how many titles each has, and the
    collections whose poster overlays it turns off."""
    from . import napalm
    try:
        libraries = napalm.counts(section) if section else []
    except PlexError as exc:
        raise HTTPException(400, str(exc))
    return {"libraries": libraries, "collections": napalm.affected(section)}


@router.get("/napalm/last")
def napalm_last():
    """The current or last refresh's summary (since Curatarr started)."""
    from . import napalm
    return napalm.progress


@router.post("/napalm/run")
def napalm_run(body: dict = Body(...)):
    """Switch every title in the chosen libraries to a fresh poster (in the background)."""
    from . import napalm
    if body.get("confirm") != "napalm":
        raise HTTPException(422, "Confirm first")
    sections = [str(s) for s in body.get("section_ids") or []]
    if not sections:
        raise HTTPException(422, "Pick at least one library")
    if napalm.progress["running"]:
        raise HTTPException(409, "A poster refresh is already running")
    scheduler.run_task(lambda: napalm.run(sections), "Napalm poster refresh")
    return {"queued": True}


@router.post("/napalm/stop")
def napalm_stop():
    from . import napalm
    napalm.stop()
    return {"stopping": napalm.progress["running"]}


@router.post("/overlays/apply")
def overlay_apply(remove_all: bool = False):
    """Update every overlaid poster now (in the background); ``remove_all`` restores all originals."""
    from . import overlays
    if remove_all:
        # Turn ribbons and badges off too, or the next sync would draw them again.
        overlays.save_library_settings({})
        for row in db.list_collections():
            cfg = CollectionConfig(**row["config"])
            if cfg.ribbon.enabled or cfg.badges.quality or cfg.badges.rating or cfg.badges.content_rating \
                    or cfg.fresh_poster:
                cfg.ribbon.enabled, cfg.badges.quality, cfg.badges.rating = False, False, ""
                cfg.badges.content_rating = cfg.fresh_poster = False
                db.update_collection_config(row["id"], cfg.model_dump())
    scheduler.run_task(lambda: overlays.apply_all(remove_all=remove_all), "Poster overlays")
    return {"queued": True}


@router.get("/overlays/fonts")
def overlay_fonts():
    from . import overlays
    return overlays.available_fonts()


@router.get("/overlays/libraries")
def overlay_libraries():
    """Whole-library badge settings: {section id: {quality, content_rating, rating, rating_min}}."""
    from . import overlays
    return overlays.library_settings()


@router.put("/overlays/libraries")
def overlay_libraries_save(body: dict = Body(...)):
    from . import overlays
    try:
        saved = overlays.save_library_settings(body)
    except (ValidationError, TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc))
    scheduler.run_task(sync.run_overlays, "Poster overlays")     # draw or remove them now
    return saved


@router.post("/overlays/preview")
def overlay_preview(body: dict = Body(...)):
    """A poster with the ribbon and badges drawn on it.

    Uses the first title of ``collection_id`` (its real ratings and quality) when
    it's in Plex, otherwise a plain poster with sample values.
    """
    from . import overlays
    from .models import Badges, Ribbon
    try:
        ribbon = Ribbon(**(body.get("ribbon") or {}))
        badges = Badges(**(body.get("badges") or {}))
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False, include_context=False))
    ribbons = [{"kind": "ribbon", **ribbon.model_dump(exclude={"enabled"})}] if ribbon.enabled else []
    sample = {"kind": "badges", "quality": ["4K", "DV", "ATMOS"] if badges.quality else [],
              "rating": ({"source": "imdb", "value": "8.4"} if badges.rating == "audience"
                         else {"source": "rottentomatoes", "value": "92%"}) if badges.rating else None,
              "content_rating": "PG-13" if badges.content_rating else ""}
    has_sample = bool(sample["quality"] or sample["rating"] or sample["content_rating"])
    fresh = bool(body.get("fresh_poster"))
    row = db.get_collection(int(body["collection_id"])) if body.get("collection_id") else None
    section = str(body.get("section_id") or "")
    try:
        if (row and row.get("plex_rating_key")) or section:
            with _plex() as plex:
                try:
                    if row and row.get("plex_rating_key"):
                        items = plex.collection_raw(row["plex_rating_key"])
                    else:                    # a library: its first title with a poster
                        stype = next((s["type"] for s in plex.sections() if s["id"] == section), "movie")
                        page = plex._request("GET", f"/library/sections/{section}/all", params={
                            "type": plexmod.SECTION_TYPES.get(stype, 1), "X-Plex-Container-Start": 0,
                            "X-Plex-Container-Size": 20})
                        items = [i for i in page.get("Metadata") or [] if i.get("thumb")][:1]
                except PlexError:
                    items = []
                specs = list(ribbons)
                thumb, rk = "", ""
                if items:
                    item, thumb, rk = items[0], items[0].get("thumb") or "", str(items[0]["ratingKey"])
                    quality = overlays.quality_labels(plex.item(str(item["ratingKey"])) or item) \
                        if badges.quality and item.get("type") == "movie" else []
                    rating = overlays.rating_badge(item, badges.rating) if badges.rating else None
                    certificate = overlays.content_rating_label(item.get("contentRating")) \
                        if badges.content_rating else ""
                    # Sample values where this title has none, so the preview shows the look.
                    quality, rating = quality or sample["quality"], rating or sample["rating"]
                    certificate = certificate or sample["content_rating"]
                    if quality or rating or certificate:
                        specs.append({"kind": "badges", "quality": quality, "rating": rating,
                                      "content_rating": certificate})
                elif has_sample:
                    specs.append(sample)
                data = overlays.preview(specs, plex, thumb, rk, fresh)
        else:
            data = overlays.preview(ribbons + ([sample] if has_sample else []))
    except Exception as exc:
        raise HTTPException(500, f"Could not draw the preview: {exc}")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/arr/have")
def arr_have(body: dict = Body(...)):
    """Which of these titles Radarr (movies) or Sonarr (shows) already has, in one call per service.

    Each result is true, false, or null when that service isn't set up or can't be reached.
    """
    items = body.get("items") or []
    settings = db.get_settings()
    libraries: dict[str, dict | None] = {}
    with httpx.Client(timeout=30) as http:
        for kind in {("sonarr" if i.get("media_type") == "show" else "radarr") for i in items}:
            client = arr.Arr(kind, settings, http)
            try:
                libraries[kind] = client.library_ids() if client.configured else None
            except (arr.ArrError, httpx.HTTPError, ValueError) as exc:
                log.warning("Could not read the %s library: %s", kind.title(), exc)
                libraries[kind] = None
    out = []
    for i in items:
        have = libraries.get("sonarr" if i.get("media_type") == "show" else "radarr")
        ref = sources.MediaRef(**{k: i.get(k) for k in ("imdb", "tmdb", "tvdb")})
        out.append(None if have is None else arr.Arr.already_has(ref, have))
    return {"have": out}


@router.post("/collections/{collection_id}/undo")
def undo_collection(collection_id: int):
    if not db.get_collection(collection_id):
        raise HTTPException(404, "Collection not found")
    try:
        run = sync.undo_last_sync(collection_id)
    except (PlexError, sync.SyncError) as exc:
        raise HTTPException(400, str(exc))
    scheduler.reload_jobs()
    return run


@router.post("/collections/{collection_id}/order")
def set_order(collection_id: int, body: dict = Body(...)):
    """Save an order arranged by hand (ratingKeys); an empty list goes back to list order."""
    if not db.get_collection(collection_id):
        raise HTTPException(404, "Collection not found")
    order = body.get("order") or []
    try:
        sync.apply_manual_order(collection_id, order)
    except (PlexError, sync.SyncError) as exc:
        raise HTTPException(400, str(exc))
    if not order:         # back to list order: the next sync puts it right
        scheduler.run_now(collection_id)
    return _collection_out(db.get_collection(collection_id))


@router.get("/collections/{collection_id}/last-change")
def collection_last_change(collection_id: int):
    return db.last_change(collection_id)


@router.post("/collections/{collection_id}/own")
def own_collection(collection_id: int):
    """Let Curatarr fully manage a Plex collection that already existed (allow removals)."""
    if not db.get_collection(collection_id):
        raise HTTPException(404, "Collection not found")
    db.update_collection_state(collection_id, plex_owned=1)
    return _collection_out(db.get_collection(collection_id))


@router.post("/collections/{collection_id}/run")
def run_collection(collection_id: int, dry_run: bool = False):
    if not db.get_collection(collection_id):
        raise HTTPException(404, "Collection not found")
    if dry_run:
        return sync.run_collection(collection_id, "dry-run", dry_run=True)
    if sync.is_running(collection_id):
        return {"queued": False, "message": "Already running"}
    scheduler.run_now(collection_id)
    return {"queued": True}


def _image_kind(kind: str) -> str:
    if kind not in ("poster", "art"):
        raise HTTPException(404, "Image kind must be 'poster' or 'art'")
    return f"{kind}_file"


@router.post("/collections/{collection_id}/image/{kind}")
async def upload_image(collection_id: int, kind: str, file: UploadFile = File(...)):
    field = _image_kind(kind)
    row = db.get_collection(collection_id)
    if not row:
        raise HTTPException(404, "Collection not found")
    ext = IMAGE_TYPES.get(file.content_type or "")
    if not ext:
        raise HTTPException(415, "Upload a JPEG, PNG or WebP image")
    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Images must be 10 MB or smaller")
    cfg = row["config"]
    if cfg.get(field):
        (config.IMAGE_DIR / cfg[field]).unlink(missing_ok=True)
    filename = f"{collection_id}-{kind}{ext}"
    (config.IMAGE_DIR / filename).write_bytes(data)
    cfg[field] = filename
    db.update_collection_config(collection_id, cfg)
    return {"file": filename}


@router.post("/titles/{rating_key}/poster")
async def upload_title_poster(rating_key: str, file: UploadFile | None = File(None), url: str = Form(""),
                              keep: bool = Form(True), section_id: str = Form(""), type: str = Form("movie")):
    """Give a movie or show a new poster (a file or an image URL), and by default keep it:
    the "Curatarr Keep Poster" label stops napalm and fresh posters replacing it."""
    from . import unmatched
    data = None
    if file is not None and file.filename:
        if not IMAGE_TYPES.get(file.content_type or ""):
            raise HTTPException(415, "Upload a JPEG, PNG or WebP image")
        data = await file.read()
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "Images must be 10 MB or smaller")
    url = url.strip()
    if not data and not url.startswith(("http://", "https://")):
        raise HTTPException(422, "Choose an image file or enter an image URL")
    with _plex() as plex:
        try:
            plex.upload_image(rating_key, "poster", data=data, url=None if data else url)
            if keep and section_id:
                plex.set_item_label(section_id, rating_key, type, unmatched.KEEP_LABEL, True)
            thumb = (plex.item(rating_key) or {}).get("thumb") or ""
        except PlexError as exc:
            raise HTTPException(502, str(exc))
    unmatched.update_cached(rating_key, thumb=thumb, keep=True if keep and section_id else None)
    log.info("New poster uploaded for %s%s", rating_key, " (kept)" if keep and section_id else "")
    if rating_key in db.overlay_rows():        # redraw its ribbons and badges on the new poster
        scheduler.run_task(sync.run_overlays, "Poster overlays")
    return {"thumb": thumb, "keep": bool(keep and section_id)}


@router.get("/collections/{collection_id}/image/{kind}")
def get_image(collection_id: int, kind: str):
    field = _image_kind(kind)
    row = db.get_collection(collection_id)
    if not row or not row["config"].get(field):
        raise HTTPException(404, "No image uploaded")
    path = config.IMAGE_DIR / Path(row["config"][field]).name
    if not path.is_file():
        raise HTTPException(404, "Image file is missing")
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@router.delete("/collections/{collection_id}/image/{kind}")
def delete_image(collection_id: int, kind: str):
    field = _image_kind(kind)
    row = db.get_collection(collection_id)
    if not row:
        raise HTTPException(404, "Collection not found")
    cfg = row["config"]
    if cfg.get(field):
        (config.IMAGE_DIR / cfg[field]).unlink(missing_ok=True)
        cfg[field] = ""
        db.update_collection_config(collection_id, cfg)
    return {"deleted": True}


# --- preview & history --------------------------------------------------------

@router.post("/preview")
def preview(req: PreviewRequest):
    try:
        return sync.preview(req.section_id, req.library, req.sources, req.item_limit, req.section_ids)
    except (PlexError, sync.SyncError) as exc:
        raise HTTPException(400, str(exc))


@router.get("/runs")
def runs(collection_id: int | None = None, limit: int = Query(100, le=1000)):
    return db.list_runs(collection_id, limit)


# --- YAML import / export -----------------------------------------------------

EXPORT_EXCLUDE = {"section_id", "section_ids", "poster_file", "art_file"}


def export_yaml() -> str:
    collections = []
    defaults = CollectionConfig(name="x", sources=[{"type": "static", "value": "x"}]).model_dump()
    for row in db.list_collections():
        cfg = CollectionConfig(**row["config"]).model_dump()
        out = {k: v for k, v in cfg.items()
               if k not in EXPORT_EXCLUDE and (k in ("name", "library", "sources") or v != defaults[k])}
        out["sources"] = [{k: v for k, v in s.items() if v is not None} for s in cfg["sources"]]
        collections.append(out)
    return yaml.safe_dump({"collections": collections}, sort_keys=False, allow_unicode=True)


def import_yaml(text: str, overwrite: bool = True) -> dict:
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}")
    items = data.get("collections") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("Expected a top-level 'collections:' list")
    existing = {(r["config"]["name"].lower(), (r["config"].get("library") or "").lower()): r
                for r in db.list_collections()}
    created = updated = 0
    errors = []
    for i, item in enumerate(items):
        try:
            model = CollectionConfig(**item)
            if model.schedule:
                scheduler.validate_cron(model.schedule)
        except (ValidationError, ValueError, TypeError) as exc:
            errors.append(f"#{i + 1} ({(item or {}).get('name', '?')}): {exc}")
            continue
        key = (model.name.lower(), model.library.lower())
        if key in existing:
            if overwrite:
                row = existing[key]
                cfg = model.model_dump()
                for field in EXPORT_EXCLUDE:
                    cfg[field] = cfg[field] or row["config"].get(field, cfg[field])
                db.update_collection_config(row["id"], cfg)
                updated += 1
        else:
            db.create_collection(model.model_dump())
            created += 1
    scheduler.reload_jobs()
    return {"created": created, "updated": updated, "errors": errors}


@router.get("/logs")
def get_logs(lines: int = Query(500, ge=1, le=5000), level: str = "", search: str = ""):
    return logs.tail(lines, level, search)


@router.get("/logs/download")
def download_logs():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    data = logs.bundle(db.get_settings(), db.list_collections())
    return Response(data, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="curatarr-logs-{stamp}.zip"'})


@router.get("/export", response_class=PlainTextResponse)
def export():
    return PlainTextResponse(export_yaml(), media_type="application/x-yaml", headers={
        "Content-Disposition": 'attachment; filename="curatarr-collections.yml"'})


@router.post("/import")
def import_(text: str = Body(..., media_type="text/plain"), overwrite: bool = True):
    try:
        return import_yaml(text, overwrite)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
