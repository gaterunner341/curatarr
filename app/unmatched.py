"""Find titles that aren't tied to IMDb, TMDB or TVDB, and fan edits.

Listed are titles labeled "Fan Edit" (or "FanEdit", "fan-edit", ...) in Plex,
whatever their match, plus two kinds of titles without outside ids:

* **not matched**: Plex has no metadata match at all (a ``local://`` or
  "none" agent guid). Their posters are whatever you uploaded or put in the folder.
* **no IDs**: matched in Plex, but without IMDb, TMDB or TVDB ids. A fan edit
  matched to the wrong title ends up here, and would get that title's posters.

Titles with the Plex label ``Curatarr Keep Poster`` are never given a different
poster by napalm or the fresh-poster option.
"""
import logging
import threading
import time

from . import db, plex as plexmod
from .plex import Plex, parse_guid

log = logging.getLogger(__name__)

KEEP_LABEL = "Curatarr Keep Poster"
UNMATCHED_SCHEMES = ("local://", "com.plexapp.agents.none")

_cache: dict = {"at": 0.0, "result": None}
_lock = threading.Lock()


def classify(item: dict) -> str | None:
    """"unmatched", "no_ids", or None for a title tied to IMDb, TMDB or TVDB."""
    guid = item.get("guid") or ""
    if not guid or guid.startswith(UNMATCHED_SCHEMES):
        return "unmatched"
    ids = [parse_guid(g.get("id", "")) for g in item.get("Guid") or []] + [parse_guid(guid)]
    return None if any(ids) else "no_ids"


def _labeled(plex: Plex, section: dict, matches) -> set[str]:
    """Rating keys in a library with any label whose name ``matches``."""
    keys: set[str] = set()
    for label in plex.filter_values(section["id"], "label"):
        if matches(label["title"]):
            items = plex._paged(f"/library/sections/{section['id']}/all", {
                "type": plexmod.SECTION_TYPES.get(section["type"], plexmod.TYPE_MOVIE), "label": label["id"]})
            keys |= {str(i["ratingKey"]) for i in items}
    return keys


def keep_set(plex: Plex, section: dict) -> set[str]:
    """Rating keys in a library that have the Keep Poster label."""
    return _labeled(plex, section, lambda name: name == KEEP_LABEL)


def is_fan_edit_label(name: str) -> bool:
    """"Fan Edit", "FanEdit", "fan-edit", "Fan Edits" and the like."""
    return "".join(ch for ch in name.lower() if ch.isalnum()) in ("fanedit", "fanedits")


def fan_edit_set(plex: Plex, section: dict) -> set[str]:
    return _labeled(plex, section, is_fan_edit_label)


def has_keep_label(item: dict) -> bool:
    return any(t.get("tag") == KEEP_LABEL for t in item.get("Label") or [])


def scan(refresh: bool = False, max_age: float = 600) -> dict:
    """Every library's titles that aren't tied to IMDb, TMDB or TVDB (cached for ``max_age`` seconds)."""
    with _lock:
        if not refresh and _cache["result"] and time.monotonic() - _cache["at"] < max_age:
            return _cache["result"]
        titles, libraries = [], []
        with plexmod.from_settings(db.get_settings()) as plex:
            for section in plex.sections():
                items = plex.section_items(section["id"], section["type"])
                keep = keep_set(plex, section)
                fan_edits = fan_edit_set(plex, section)
                found = 0
                for item in items:
                    kind = classify(item) or "matched"
                    fan_edit = str(item["ratingKey"]) in fan_edits
                    if kind == "matched" and not fan_edit:
                        continue
                    found += 1
                    parts = [p for m in item.get("Media") or [] for p in m.get("Part") or []]
                    titles.append({
                        "ratingKey": str(item["ratingKey"]), "title": item.get("title") or "",
                        "year": item.get("year"), "type": item.get("type") or section["type"],
                        "thumb": item.get("thumb") or "", "kind": kind, "fan_edit": fan_edit,
                        "file": (parts[0].get("file") or "").replace("\\", "/").rsplit("/", 1)[-1] if parts else "",
                        "section_id": section["id"], "library": section["title"],
                        "keep": str(item["ratingKey"]) in keep})
                libraries.append({"id": section["id"], "title": section["title"], "type": section["type"],
                                  "total": len(items), "found": found})
        result = {"titles": titles, "libraries": libraries, "scanned": db.now()}
        log.info("Unmatched titles and fan edits: %d found in %d librar%s", len(titles), len(libraries),
                 "y" if len(libraries) == 1 else "ies")
        _cache.update(at=time.monotonic(), result=result)
        return result


def set_keep(rating_keys: list[dict], keep: bool) -> int:
    """Add or remove the Keep Poster label: items are [{ratingKey, section_id, type}]."""
    done = 0
    with plexmod.from_settings(db.get_settings()) as plex:
        for item in rating_keys:
            plex.set_item_label(str(item["section_id"]), str(item["ratingKey"]), item.get("type") or "movie",
                                KEEP_LABEL, keep)
            done += 1
    result = _cache.get("result")
    if result:                       # keep the cached scan in step
        wanted = {str(i["ratingKey"]) for i in rating_keys}
        for title in result["titles"]:
            if title["ratingKey"] in wanted:
                title["keep"] = keep
    return done


def update_cached(rating_key: str, thumb: str | None = None, keep: bool | None = None) -> None:
    """Keep the cached scan in step after a change to one title."""
    for title in (_cache.get("result") or {}).get("titles", []):
        if title["ratingKey"] == str(rating_key):
            if thumb:
                title["thumb"] = thumb
            if keep is not None:
                title["keep"] = keep
