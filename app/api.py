"""REST API used by the web UI (and available for scripting)."""
import logging
import os
from datetime import datetime
from pathlib import Path

import httpx
import yaml
from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import ValidationError

from . import arr, config, db, holidays, logs, plex as plexmod, plextv, scheduler, sources, sync
from .models import CollectionConfig, PreviewRequest
from .plex import PlexError
from .sources import SourceContext, SourceError
from .sources.tmdb import TMDB

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

@router.get("/plex/libraries")
def plex_libraries():
    with _plex() as plex:
        try:
            return plex.sections()
        except PlexError as exc:
            raise HTTPException(502, str(exc))


@router.get("/plex/libraries/{section_id}/collections")
def plex_collections(section_id: str):
    with _plex() as plex:
        try:
            return plex.collections(section_id)
        except PlexError as exc:
            raise HTTPException(502, str(exc))


@router.get("/plex/collections")
def plex_all_collections():
    """Every collection in Plex, marked with the Curatarr collection that manages it (if any)."""
    rows = db.list_collections()
    by_key = {str(r["plex_rating_key"]): r["id"] for r in rows if r.get("plex_rating_key")}
    by_title = {(str(r["config"].get("section_id")), r["config"]["name"].strip().lower()): r["id"]
                for r in rows}
    result = []
    with _plex() as plex:
        try:
            for section in plex.sections():
                for coll in plex.collections(section["id"]):
                    managed = by_key.get(coll["ratingKey"]) or by_title.get(
                        (section["id"], (coll["title"] or "").strip().lower()))
                    result.append({**coll, "section_id": section["id"],
                                   "section_title": section["title"],
                                   "section_type": section["type"], "managed_id": managed})
        except PlexError as exc:
            raise HTTPException(502, str(exc))
    return result


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
    for h in holidays.HOLIDAYS:
        colls = [_collection_out(r) for r in rows if r["config"].get("holiday") == h["key"]]
        result.append({
            "key": h["key"], "name": h["name"], "start": h["start"], "end": h["end"],
            "link": h.get("link", ""), "arr_ready": arr_ready,
            "available": holidays.available(h),
            "poster": f"/static/holidays/{h['poster']}" if h.get("poster") else "",
            "collections": colls,
        })
    return result


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
    return {"deleted": True, "message": message}


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
        return sync.preview(req.section_id, req.library, req.sources, req.item_limit)
    except (PlexError, sync.SyncError) as exc:
        raise HTTPException(400, str(exc))


@router.get("/runs")
def runs(collection_id: int | None = None, limit: int = Query(100, le=1000)):
    return db.list_runs(collection_id, limit)


# --- YAML import / export -----------------------------------------------------

EXPORT_EXCLUDE = {"section_id", "poster_file", "art_file"}


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
                    cfg[field] = cfg[field] or row["config"].get(field, "")
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
