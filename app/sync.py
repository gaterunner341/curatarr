"""The sync engine: makes a Plex collection match its configured lists."""
import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field

import httpx

from . import arr, config, db, notify, plex as plexmod
from .models import CollectionConfig
from .plex import COLLECTION_MODES, COLLECTION_ORDERS, LibraryIndex, Plex, PlexError
from .sources import MediaRef, SourceContext, resolve
from .sources.tmdb import TMDB, _first_number

log = logging.getLogger(__name__)

INDEX_TTL = 300
_index_cache: dict[tuple[str, str], tuple[float, LibraryIndex]] = {}
_index_lock = threading.Lock()
_run_locks: dict[int, threading.Lock] = {}
_run_locks_guard = threading.Lock()


class SyncError(Exception):
    pass


@dataclass
class SyncResult:
    status: str = "success"          # success | warning | skipped | error
    matched: int = 0
    added: int = 0
    removed: int = 0
    requested: int = 0
    missing: list[dict] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    state: dict = field(default_factory=dict)

    def warn(self, message: str) -> None:
        self.messages.append(message)
        if self.status == "success":
            self.status = "warning"


def library_index(plex: Plex, section: dict, refresh: bool = False) -> LibraryIndex:
    key = (plex.url, section["id"])
    with _index_lock:
        cached = _index_cache.get(key)
        if cached and not refresh and time.monotonic() - cached[0] < INDEX_TTL:
            return cached[1]
    index = plex.library_index(section["id"], section["type"])
    with _index_lock:
        _index_cache[key] = (time.monotonic(), index)
    return index


def clear_index_cache() -> None:
    with _index_lock:
        _index_cache.clear()


def resolve_section(plex: Plex, section_id: str, library: str) -> dict:
    sections = plex.sections()
    for section in sections:
        if section_id and section["id"] == str(section_id):
            return section
    for section in sections:
        if library and (section["title"] or "").lower() == library.lower():
            return section
    raise SyncError(f"Plex library '{library or section_id}' was not found")


def reorder_moves(current: list[str], desired: list[str]) -> list[tuple[str, str | None]]:
    """Moves (item, after) that turn ``current`` into ``desired`` order.

    Only items present in both lists are considered; others keep their place at the end.
    """
    present = set(current)
    target = [rk for rk in desired if rk in present]
    target += [rk for rk in current if rk not in set(target)]
    working = list(current)
    moves: list[tuple[str, str | None]] = []
    for i, rk in enumerate(target):
        if working[i] != rk:
            after = target[i - 1] if i else None
            moves.append((rk, after))
            working.remove(rk)
            working.insert(i, rk)
    return moves


def image_stamp(cfg: CollectionConfig, kind: str) -> tuple[str, bytes | None, str | None]:
    """(stamp, file bytes, url) for the poster or art configured on a collection."""
    filename = cfg.poster_file if kind == "poster" else cfg.art_file
    url = cfg.poster_url if kind == "poster" else cfg.art_url
    if filename:
        path = config.IMAGE_DIR / filename
        if path.is_file():
            data = path.read_bytes()
            return "file:" + hashlib.sha1(data).hexdigest(), data, None
    if url:
        return "url:" + url, None, url
    return "", None, None


def sync_collection(cfg: CollectionConfig, state: dict, plex: Plex, section: dict,
                    refs: list[MediaRef], settings: dict, dry_run: bool = False) -> SyncResult:
    """Apply ``refs`` to the Plex collection described by ``cfg``.

    ``state`` holds what earlier runs recorded (rating key, applied images). The
    returned result carries the updated state.
    """
    result = SyncResult(state=dict(state))
    index = library_index(plex, section)

    matched: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        rk = index.match(ref)
        if rk is None:
            result.missing.append(ref.to_dict())
        elif rk not in seen:
            seen.add(rk)
            matched.append(rk)
    result.matched = len(matched)

    existing = state.get("plex_rating_key")
    if existing and not plex.collection_exists(existing):
        existing = None
    if not existing:
        existing = plex.find_collection(section["id"], cfg.name)
    result.state["plex_rating_key"] = existing

    if len(matched) < max(cfg.min_items, 1):
        if existing and cfg.delete_below_min and not dry_run:
            plex.delete_collection(section["id"], existing)
            result.state.update(plex_rating_key=None, poster_applied=None, art_applied=None)
            result.messages.append(f"Deleted: only {len(matched)} item(s) matched "
                                   f"(minimum {cfg.min_items})")
        else:
            result.messages.append(f"Skipped: {len(matched)} item(s) matched "
                                   f"(minimum {max(cfg.min_items, 1)})")
        result.status = "skipped"
        return result

    if dry_run:
        current = plex.collection_items(existing) if existing else []
        result.added = len([rk for rk in matched if rk not in set(current)])
        if cfg.sync_mode == "sync":
            result.removed = len([rk for rk in current if rk not in seen])
        result.messages.append("Dry run: no changes were made")
        return result

    created = False
    if not existing:
        existing = plex.create_collection(section["id"], section["type"], cfg.name, matched)
        created = True
        result.added = len(matched)
        result.state["plex_rating_key"] = existing
        result.state["poster_applied"] = None
        result.state["art_applied"] = None
        current = list(matched)
    else:
        current = plex.collection_items(existing)
        current_set = set(current)
        to_add = [rk for rk in matched if rk not in current_set]
        if to_add:
            plex.add_items(existing, to_add)
            current += to_add
            result.added = len(to_add)
        if cfg.sync_mode == "sync":
            to_remove = [rk for rk in current if rk not in seen]
            for rk in to_remove:
                plex.remove_item(existing, rk)
            current = [rk for rk in current if rk in seen]
            result.removed = len(to_remove)

    rk = existing
    plex.set_prefs(rk, collectionMode=COLLECTION_MODES[cfg.collection_mode],
                   collectionSort=COLLECTION_ORDERS[cfg.order])
    if cfg.order == "custom":
        if result.added and not created:
            current = plex.collection_items(rk)
        for item, after in reorder_moves(current, matched):
            plex.move_item(rk, item, after)

    labels = list(cfg.labels)
    managed = settings.get("managed_label", "").strip()
    if managed and managed not in labels:
        labels.append(managed)
    plex.edit_collection(section["id"], rk, summary=cfg.summary or None,
                         sort_title=cfg.sort_title or None, labels=labels)

    for kind in ("poster", "art"):
        stamp, data, url = image_stamp(cfg, kind)
        if kind == "poster" and not stamp:
            url = auto_poster_url(cfg, settings)
            stamp = "url:" + url if url else ""
        if stamp and stamp != result.state.get(f"{kind}_applied"):
            try:
                plex.upload_image(rk, kind, data=data, url=url)
                result.state[f"{kind}_applied"] = stamp
            except PlexError as exc:
                result.warn(f"Could not upload {kind}: {exc}")

    promoted = cfg.promote_home or cfg.promote_shared or cfg.promote_recommended
    # Existing collections are always checked so that turning promotion off un-pins them.
    if promoted or not created:
        try:
            plex.set_hub_visibility(section["id"], rk, cfg.promote_recommended,
                                    cfg.promote_home, cfg.promote_shared)
        except PlexError as exc:
            result.warn(f"Could not update home screen visibility: {exc}")

    verb = "Created" if created else "Updated"
    result.messages.insert(0, f"{verb} with {len(matched)} item(s): "
                              f"+{result.added} / -{result.removed}, {len(result.missing)} missing")
    return result


def auto_poster_url(cfg: CollectionConfig, settings: dict) -> str | None:
    """Use the TMDB franchise poster for collections built from a TMDB collection."""
    for source in cfg.sources:
        if source.type == "tmdb_collection":
            try:
                with httpx.Client(timeout=20) as http:
                    return TMDB(settings.get("tmdb_api_key", ""), http).collection_poster(
                        _first_number(source.value, r"/collection/(\d+)"))
            except Exception as exc:   # poster is optional; never fail the sync for it
                log.debug("No TMDB poster: %s", exc)
            return None
    return None


def _lock_for(collection_id: int) -> threading.Lock:
    with _run_locks_guard:
        return _run_locks.setdefault(collection_id, threading.Lock())


def is_running(collection_id: int) -> bool:
    lock = _run_locks.get(collection_id)
    return bool(lock and lock.locked())


def run_collection(collection_id: int, trigger: str = "manual", dry_run: bool = False) -> dict:
    """Load a collection from the database, sync it and record the run."""
    lock = _lock_for(collection_id)
    if not lock.acquire(blocking=False):
        return {"status": "skipped", "message": "A sync for this collection is already running"}
    try:
        return _run_collection(collection_id, trigger, dry_run)
    finally:
        lock.release()


def _run_collection(collection_id: int, trigger: str, dry_run: bool) -> dict:
    row = db.get_collection(collection_id)
    if not row:
        raise SyncError(f"Collection {collection_id} does not exist")
    cfg = CollectionConfig(**row["config"])
    settings = db.get_settings()
    run = {"collection_id": collection_id, "collection_name": cfg.name, "trigger": trigger,
           "started": db.now(), "status": "error"}
    log.info("Syncing collection '%s' (%s)", cfg.name, trigger)
    try:
        with plexmod.from_settings(settings) as plex, httpx.Client(timeout=30) as http:
            section = resolve_section(plex, cfg.section_id, cfg.library)
            if section["id"] != cfg.section_id or section["title"] != cfg.library:
                cfg.section_id, cfg.library = section["id"], section["title"]
                db.update_collection_config(collection_id, cfg.model_dump())
            ctx = SourceContext(settings=settings, http=http, media_type=section["type"])
            refs, source_errors = resolve(cfg.sources, ctx, cfg.item_limit)
            run["source_count"] = len(refs)
            if source_errors and not refs:
                raise SyncError("; ".join(source_errors))
            state = {k: row.get(k) for k in ("plex_rating_key", "poster_applied", "art_applied")}
            result = sync_collection(cfg, state, plex, section, refs, settings, dry_run=dry_run)
            for err in source_errors:
                result.warn(err)
            if cfg.request_missing and result.missing and not dry_run:
                missing_refs = [MediaRef(**m) for m in result.missing]
                result.requested, arr_errors = arr.request_missing(
                    section["type"], missing_refs, settings, http)
                for err in arr_errors:
                    result.warn(err)
                if result.requested:
                    result.messages.append(f"Requested {result.requested} missing title(s)")
        run.update(status=result.status, matched=result.matched, added=result.added,
                   removed=result.removed, requested=result.requested, missing=result.missing,
                   message=" | ".join(result.messages))
        if not dry_run:
            db.update_collection_state(collection_id, **{
                k: result.state.get(k) for k in ("plex_rating_key", "poster_applied", "art_applied")
            })
    except (PlexError, SyncError) as exc:
        run["message"] = str(exc)
        log.error("Sync of '%s' failed: %s", cfg.name, exc)
    except Exception as exc:   # keep the scheduler alive and record the failure
        run["message"] = f"Unexpected error: {exc}"
        log.exception("Sync of '%s' crashed", cfg.name)
    run["finished"] = db.now()
    if dry_run:
        return run
    db.record_run(run)
    db.update_collection_state(collection_id, last_run=run["finished"],
                               last_status=run["status"], last_message=run.get("message", ""))
    notify.notify_run(settings, run)
    return run


def preview(section_id: str, library: str, sources, item_limit: int = 0) -> dict:
    """Fetch lists and report which titles are already in Plex, without changing anything."""
    settings = db.get_settings()
    with plexmod.from_settings(settings) as plex, httpx.Client(timeout=30) as http:
        section = resolve_section(plex, section_id, library)
        refs, errors = resolve(sources, SourceContext(settings, http, section["type"]), item_limit)
        index = library_index(plex, section, refresh=True)
        items = []
        for ref in refs:
            rk = index.match(ref)
            items.append({**ref.to_dict(), "in_plex": rk is not None, "rating_key": rk,
                          "plex_title": index.titles.get(rk) if rk else None})
    return {"library": section, "items": items, "errors": errors,
            "matched": sum(1 for i in items if i["in_plex"]), "total": len(items)}
