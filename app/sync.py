"""The sync engine: makes a Plex collection match its configured lists."""
import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date

import httpx

from . import arr, config, db, plex as plexmod
from .models import CollectionConfig
from .plex import COLLECTION_MODES, COLLECTION_ORDERS, LibraryIndex, Plex, PlexError
from .sources import MediaRef, SourceContext, resolve
from .sources.tmdb import TMDB, _first_number

log = logging.getLogger(__name__)

INDEX_TTL = 300
STATE_KEYS = ("plex_rating_key", "plex_owned", "poster_applied", "art_applied")
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
    # Each move is a separate Plex call, so keep the longest run of items that are
    # already in the right relative order and only move the rest.
    position = {rk: i for i, rk in enumerate(target)}
    keep = _longest_increasing([position[rk] for rk in current])
    keep_items = {target[p] for p in keep}
    moves: list[tuple[str, str | None]] = []
    for i, rk in enumerate(target):
        if rk not in keep_items:
            moves.append((rk, target[i - 1] if i else None))
    return moves


def _longest_increasing(values: list[int]) -> set[int]:
    """Values forming a longest strictly increasing subsequence (O(n log n))."""
    import bisect
    tails: list[int] = []        # smallest tail value for each length
    tail_idx: list[int] = []     # index in ``values`` of that tail
    prev = [-1] * len(values)
    for i, v in enumerate(values):
        pos = bisect.bisect_left(tails, v)
        if pos == len(tails):
            tails.append(v)
            tail_idx.append(i)
        else:
            tails[pos] = v
            tail_idx[pos] = i
        prev[i] = tail_idx[pos - 1] if pos else -1
    result: set[int] = set()
    i = tail_idx[-1] if tail_idx else -1
    while i >= 0:
        result.add(values[i])
        i = prev[i]
    return result


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
                    refs: list[MediaRef], settings: dict, dry_run: bool = False,
                    today: date | None = None) -> SyncResult:
    """Apply ``refs`` to the Plex collection described by ``cfg``.

    ``state`` holds what earlier runs recorded (rating key, applied images). The
    returned result carries the updated state.
    """
    result = SyncResult(state=dict(state))
    name = cfg.name
    started = time.monotonic()
    index = library_index(plex, section)
    log.info("'%s': library index has %d item(s) (%.1fs)", name, len(index),
             time.monotonic() - started)

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
    # Curatarr only removes titles from (or deletes) Plex collections it created or that
    # were linked on purpose. Rows from before 0.5.3 have no flag and count as owned.
    owned = state.get("plex_owned")
    owned = True if owned is None else bool(owned)
    if existing:
        where = plex.collection_section(existing)
        if where is None:
            existing = None
        elif where and where != str(section["id"]):
            log.warning("'%s': Plex collection %s is in another library; creating one in '%s'",
                        name, existing, section["title"])
            result.messages.append("Library changed, so a new Plex collection was made; "
                                   "the one in the old library was left untouched")
            existing = None
    if not existing:
        existing = plex.find_collection(section["id"], name)
        owned = False                     # a same-named collection someone else made
    result.state["plex_rating_key"] = existing
    result.state["plex_owned"] = int(owned) if existing else None
    log.info("'%s': %d matched in Plex, %d missing; %s", name, len(matched),
             len(result.missing),
             f"updating Plex collection {existing}" if existing else "no Plex collection yet")

    if len(matched) < max(cfg.min_items, 1):
        if existing and owned and cfg.delete_below_min and not dry_run:
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
        if cfg.sync_mode == "sync" and owned:
            result.removed = len([rk for rk in current if rk not in seen])
        result.messages.append("Dry run: no changes were made")
        return result

    created = False
    if not existing:
        existing = plex.create_collection(section["id"], section["type"], cfg.name, matched)
        created = True
        result.added = len(matched)
        result.state["plex_rating_key"] = existing
        result.state["plex_owned"] = 1
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
        if cfg.sync_mode == "sync" and not owned:
            result.messages.append("This Plex collection already existed, so Curatarr only adds to it "
                                   "(see the collection's settings to let it remove titles too)")
        elif cfg.sync_mode == "sync":
            to_remove = [rk for rk in current if rk not in seen]
            for rk in to_remove:
                plex.remove_item(existing, rk)
            current = [rk for rk in current if rk in seen]
            result.removed = len(to_remove)

    log.info("'%s': %s collection %s: +%d / -%d (%.1fs)", name,
             "created" if created else "updated", existing, result.added, result.removed,
             time.monotonic() - started)

    rk = existing
    plex.set_prefs(rk, collectionMode=COLLECTION_MODES[cfg.collection_mode],
                   collectionSort=COLLECTION_ORDERS[cfg.order])
    if cfg.order == "custom":
        if result.added:
            current = plex.collection_items(rk)
        moves = reorder_moves(current, matched)
        if moves:
            log.info("'%s': reordering %d item(s) to match the list", name, len(moves))
        for n, (item, after) in enumerate(moves, 1):
            plex.move_item(rk, item, after)
            if n % 50 == 0:
                log.info("'%s': reordered %d/%d", name, n, len(moves))

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

    recommended, home, shared = cfg.promotion_flags(today or date.today())
    # Existing collections are always checked so that turning promotion off un-pins them.
    if recommended or home or shared or not created:
        try:
            plex.set_hub_visibility(section["id"], rk, recommended, home, shared)
        except PlexError as exc:
            result.warn(f"Could not update home screen visibility: {exc}")

    log.info("'%s': artwork, labels and home screen settings applied (%.1fs total)", name,
             time.monotonic() - started)
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
            state = {k: row.get(k) for k in STATE_KEYS}
            if cfg.off_season(date.today()):
                # Seasonal collections don't exist in Plex outside their dates; skip the lists.
                result = remove_off_season(cfg, state, plex, section, dry_run=dry_run)
                source_errors = []
            else:
                ctx = SourceContext(settings=settings, http=http, media_type=section["type"])
                log.info("'%s': library '%s' (id %s, %s), %d source(s)", cfg.name, section["title"],
                         section["id"], section["type"], len(cfg.sources))
                refs, source_errors = resolve(cfg.sources, ctx, cfg.item_limit)
                run["source_count"] = len(refs)
                for err in source_errors:
                    log.warning("'%s': source failed: %s", cfg.name, err)
                log.info("'%s': %d title(s) from lists", cfg.name, len(refs))
                if source_errors and not refs:
                    raise SyncError("; ".join(source_errors))
                result = sync_collection(cfg, state, plex, section, refs, settings, dry_run=dry_run)
            for err in source_errors:
                result.warn(err)
            if cfg.request_missing and result.missing and not dry_run:
                missing_refs = [MediaRef(**m) for m in result.missing]
                result.requested, arr_errors, limited = arr.request_missing(
                    section["type"], missing_refs, settings, http)
                for err in arr_errors:
                    result.warn(err)
                if result.requested:
                    result.messages.append(f"Requested {result.requested} missing title(s)"
                                           + (" (per-sync limit reached; more next sync)" if limited else ""))
        run.update(status=result.status, matched=result.matched, added=result.added,
                   removed=result.removed, requested=result.requested, missing=result.missing,
                   message=" | ".join(result.messages))
        log.info("'%s': %s - matched %d, added %d, removed %d, missing %d. %s", cfg.name,
                 result.status, result.matched, result.added, result.removed,
                 len(result.missing), run["message"])
        if result.missing:
            log.debug("'%s': missing %s", cfg.name, ", ".join(
                m.get("imdb") or f"tmdb:{m.get('tmdb')}" for m in result.missing))
        if not dry_run:
            db.update_collection_state(collection_id, **{
                k: result.state.get(k) for k in STATE_KEYS
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
    return run


def next_start(cfg: CollectionConfig, today: date) -> date:
    """The next day the collection's window opens."""
    start = date.fromisoformat(cfg.promote_start)
    if not cfg.promote_yearly:
        return start
    candidate = start.replace(year=today.year) if not (start.month == 2 and start.day == 29) \
        else date(today.year, 3, 1)
    return candidate if candidate > today else candidate.replace(year=today.year + 1)


def remove_off_season(cfg: CollectionConfig, state: dict, plex: Plex, section: dict,
                      dry_run: bool = False, today: date | None = None) -> SyncResult:
    """Delete a seasonal collection from Plex while it's out of season."""
    today = today or date.today()
    result = SyncResult(status="skipped", state=dict(state))
    opens = next_start(cfg, today)
    back = f"{opens:%b} {opens.day}"
    rk = state.get("plex_rating_key")
    owned = state.get("plex_owned")
    owned = True if owned is None else bool(owned)
    if rk and plex.collection_section(rk) is not None:
        if not owned:
            result.messages.append("Off season, but this Plex collection existed before Curatarr, "
                                   "so it was left in place")
            return result
        if dry_run:
            result.messages.append(f"Dry run: would remove it from Plex until {back}")
            return result
        plex.delete_collection(section["id"], rk)
        log.info("'%s': off season, deleted Plex collection %s until %s", cfg.name, rk, back)
        result.messages.append(f"Off season: removed from Plex until {back}")
    else:
        result.messages.append(f"Off season: not in Plex until {back}")
    result.state.update(plex_rating_key=None, plex_owned=None, poster_applied=None, art_applied=None)
    return result


def apply_home_calendars(today: date | None = None) -> int:
    """Apply collection calendars: home screen visibility and seasonal collections.

    Runs daily (and at startup) so a date window takes effect on its first and
    last day without waiting for the next full sync. Seasonal-only collections
    are synced when their window opens (creating them) and when it closes
    (deleting them). Returns how many collections were updated.
    """
    today = today or date.today()
    calendared = [r for r in db.list_collections()
                  if r["config"].get("promote_window") and r["config"].get("enabled", True)]
    updated = 0
    for row in calendared:
        cfg = CollectionConfig(**row["config"])
        if not cfg.seasonal_only:
            continue
        in_plex = bool(row.get("plex_rating_key"))
        if cfg.off_season(today) == in_plex:     # needs creating, or needs removing
            log.info("Calendar: '%s' %s", cfg.name, "season over, removing" if in_plex else "season started, creating")
            run_collection(row["id"], "calendar")
            updated += 1
    rows = [r for r in db.list_collections()
            if r["config"].get("promote_window") and r.get("plex_rating_key")]
    if not rows:
        return updated
    settings = db.get_settings()
    try:
        with plexmod.from_settings(settings) as plex:
            for row in rows:
                cfg = CollectionConfig(**row["config"])
                try:
                    section = resolve_section(plex, cfg.section_id, cfg.library)
                    flags = cfg.promotion_flags(today)
                    plex.set_hub_visibility(section["id"], row["plex_rating_key"], *flags)
                    updated += 1
                    log.info("Home screen calendar: '%s' %s", cfg.name,
                             "shown" if any(flags) else "hidden")
                except (PlexError, SyncError) as exc:
                    log.warning("Home screen calendar: '%s' failed: %s", cfg.name, exc)
    except PlexError as exc:
        log.warning("Home screen calendar skipped: %s", exc)
    return updated


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
