"""Rogue Filenames: files that don't follow the naming formats set in Radarr and Sonarr.

Radarr and Sonarr work this out themselves: their rename preview (``GET /api/v3/rename``)
lists each file whose name differs from what their own naming settings would give it.
Curatarr asks for that preview for every movie and series and keeps the result, so nothing
here is a guess about how files ought to be named.

The last scan is stored in the "naming_scan" setting as JSON:
    {finished, services: {radarr|sonarr: {formats: {...}, error, checked, items: [
        {id, title, year, path, files: [{existing, new}]}]}}}
"""
import json
import logging
import threading

import httpx

from . import arr, db

log = logging.getLogger(__name__)

_lock = threading.Lock()
progress: dict = {"running": False, "stopping": False, "service": "", "done": 0, "total": 0,
                  "started": None, "finished": None}


def last() -> dict:
    try:
        saved = json.loads(db.get_settings().get("naming_scan") or "{}")
    except ValueError:
        saved = {}
    return saved if isinstance(saved, dict) else {}


def _scan_service(client: arr.Arr) -> dict:
    """One service: its naming formats and every title with files named differently."""
    formats = client.naming()
    titles = client.titles_with_files()
    progress.update(service=client.kind, done=0, total=len(titles))
    items = []
    for t in titles:
        if progress["stopping"]:
            break
        try:
            files = client.rename_preview(t["id"])
        except (arr.ArrError, httpx.HTTPError, ValueError) as exc:
            log.warning("Rogue Filenames: %s '%s' could not be checked: %s", client.kind.title(), t["title"], exc)
            files = []
        if files:
            items.append({**t, "files": files})
        progress["done"] += 1
    log.info("Rogue Filenames: %s: %d of %d title(s) have files that don't follow its naming format",
             client.kind.title(), len(items), progress["done"])
    return {"formats": formats, "error": "", "checked": progress["done"], "items": items}


def scan() -> dict:
    """Check every movie (Radarr) and series (Sonarr). One scan at a time."""
    if not _lock.acquire(blocking=False):
        return {"running": True}
    progress.update(running=True, stopping=False, service="", done=0, total=0, started=db.now(), finished=None)
    result: dict = {"services": {}}
    try:
        settings = db.get_settings()
        with httpx.Client(timeout=60) as http:
            for kind in ("radarr", "sonarr"):
                client = arr.Arr(kind, settings, http)
                if not (client.url and client.api_key):
                    continue
                try:
                    result["services"][kind] = _scan_service(client)
                except (arr.ArrError, httpx.HTTPError, ValueError) as exc:
                    log.warning("Rogue Filenames: %s scan failed: %s", kind.title(), exc)
                    result["services"][kind] = {"formats": {}, "error": str(exc), "checked": 0, "items": []}
                if progress["stopping"]:
                    break
        result["finished"] = db.now()
        result["stopped"] = progress["stopping"]
        db.save_settings({"naming_scan": json.dumps(result)})
    finally:
        progress.update(running=False, stopping=False, finished=db.now())
        _lock.release()
    return result


def stop() -> None:
    if progress["running"]:
        progress["stopping"] = True
