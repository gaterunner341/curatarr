""""I love the smell of napalm in the morning": a fresh poster for every title.

Switches every movie and show in the chosen libraries to the first poster from
Plex's metadata sources (not an uploaded or local file). It uses Plex's own
poster selection, so nothing is deleted: the previous posters stay in each
title's poster list in Plex and can be picked again there. Titles with Curatarr
overlays are redrawn on their fresh poster afterwards.
"""
import logging
import random
import threading

from . import db, plex as plexmod
from .plex import Plex, PlexError

log = logging.getLogger(__name__)

_lock = threading.Lock()
progress: dict = {"running": False, "done": 0, "total": 0, "changed": 0, "unchanged": 0, "no_poster": 0,
                  "errors": 0, "stopping": False, "started": None, "finished": None}


def _selected(poster: dict) -> bool:
    return str(poster.get("selected", "")).lower() in ("1", "true")


def _sections(plex: Plex, section_ids: list[str]) -> list[dict]:
    wanted = {str(s) for s in section_ids}
    sections = [s for s in plex.sections() if s["id"] in wanted]
    if not sections:
        raise PlexError("Pick at least one movie or TV library")
    return sections


def _image_url(path: str) -> str:
    """A poster address the browser can show: Plex paths go through Curatarr (no token in the page)."""
    from urllib.parse import quote
    return f"/api/plex/image?path={quote(path, safe='')}" if path.startswith("/") else path


def preview(section_ids: list[str], count: int = 8) -> list[dict]:
    """A random sample of titles with their current poster and the one they'd get."""
    from .sync import library_index
    with plexmod.from_settings(db.get_settings()) as plex:
        candidates = []
        for section in _sections(plex, section_ids):
            index = library_index(plex, section)
            candidates += [(rk, index) for rk in index.details]
        out = []
        for rk, index in random.sample(candidates, min(count, len(candidates))):
            info = index.details.get(rk, {})
            entry = {"ratingKey": rk, "title": index.titles.get(rk, ""), "year": info.get("year"),
                     "current": _image_url(info["thumb"]) if info.get("thumb") else "", "fresh": "", "status": ""}
            try:
                fresh = plex.fresh_poster(plex.posters(rk))
            except PlexError as exc:
                entry["status"] = f"error: {exc}"
                out.append(entry)
                continue
            if not fresh:
                entry["status"] = "no poster from Plex's sources; it keeps its current one"
            else:
                entry["fresh"] = _image_url(fresh.get("thumb") or fresh["key"])
                entry["status"] = "already using it" if _selected(fresh) else "changes"
            out.append(entry)
        return out


def stop() -> None:
    if progress["running"]:
        progress["stopping"] = True


def run(section_ids: list[str]) -> dict:
    """Switch every title in the libraries to a fresh poster. One run at a time."""
    if not _lock.acquire(blocking=False):
        return {"running": True}
    progress.update(running=True, done=0, total=0, changed=0, unchanged=0, no_poster=0, errors=0,
                    stopping=False, started=db.now(), finished=None)
    try:
        with plexmod.from_settings(db.get_settings()) as plex:
            items = []
            for section in _sections(plex, section_ids):
                items += [(str(i["ratingKey"]), i.get("title")) for i in plex.section_items(section["id"], section["type"])]
            progress["total"] = len(items)
            log.info("Napalm: refreshing the posters of %d title(s)", len(items))
            for rk, title in items:
                if progress["stopping"]:
                    log.info("Napalm: stopped by the user after %d title(s)", progress["done"])
                    break
                try:
                    fresh = plex.fresh_poster(plex.posters(rk))
                    if not fresh:
                        progress["no_poster"] += 1
                    elif _selected(fresh):
                        progress["unchanged"] += 1
                    else:
                        plex.select_poster(rk, fresh)
                        progress["changed"] += 1
                except PlexError as exc:
                    progress["errors"] += 1
                    log.warning("Napalm: '%s' (%s) failed: %s", title, rk, exc)
                progress["done"] += 1
        log.info("Napalm: %d poster(s) changed, %d already fresh, %d with no poster from Plex's sources, "
                 "%d failed", progress["changed"], progress["unchanged"], progress["no_poster"], progress["errors"])
    finally:
        progress.update(running=False, stopping=False, finished=db.now())
        _lock.release()
    # Titles with overlays now have a new poster underneath: redraw them on it.
    from .sync import run_overlays
    run_overlays()
    return dict(progress)
