"""Plex prerolls, managed from a Plex library instead of a typed list of paths.

Plex has one server setting for prerolls, ``CinemaTrailersPrerollID``: file paths
(as the Plex server sees them) separated by commas (Plex plays them all, in order) or
semicolons (Plex plays one at random). Curatarr builds that string from clips
picked in a Plex library (e.g. "PreRolls"), with a default set and seasonal sets
that switch automatically, and keeps the setting's original value so it can be
restored.

Stored in the "prerolls" setting as JSON:
    {enabled, section_id, mode: random|sequence|daily, daily_count, default: [rating keys],
     sets: [{id, name, start: "MM-DD", end: "MM-DD", items: [rating keys]}],
     backup, backup_at, applied, applied_at, applied_set}
"""
import json
import logging
import random
from datetime import date

from . import db, plex as plexmod
from .plex import Plex, PlexError

log = logging.getLogger(__name__)

PREF = "CinemaTrailersPrerollID"
MODES = ("random", "sequence", "daily")
DEFAULTS = {"enabled": False, "section_id": "", "mode": "random", "daily_count": 3, "default": [], "sets": [],
            "backup": None, "backup_at": None, "applied": None, "applied_at": None, "applied_set": None}


class PrerollError(Exception):
    pass


# --- settings ----------------------------------------------------------------------

def load() -> dict:
    try:
        saved = json.loads(db.get_settings().get("prerolls") or "{}")
    except ValueError:
        saved = {}
    return {**DEFAULTS, **(saved if isinstance(saved, dict) else {})}


def _store(cfg: dict) -> dict:
    db.save_settings({"prerolls": json.dumps(cfg)})
    return cfg


def save(changes: dict) -> dict:
    """Save the editable parts (library, mode, sets) and check them."""
    cfg = load()
    for key in ("enabled", "section_id", "mode", "daily_count", "default", "sets"):
        if key in changes:
            cfg[key] = changes[key]
    if cfg["mode"] not in MODES:
        raise PrerollError("Play mode must be random, sequence or daily")
    cfg["daily_count"] = max(1, min(int(cfg.get("daily_count") or 3), 50))
    cfg["section_id"] = str(cfg.get("section_id") or "")
    cfg["default"] = [str(k) for k in cfg.get("default") or []]
    clean = []
    for i, s in enumerate(cfg.get("sets") or []):
        name = str(s.get("name") or "").strip() or f"Set {i + 1}"
        start, end = str(s.get("start") or ""), str(s.get("end") or "")
        if not (_valid_md(start) and _valid_md(end)):
            raise PrerollError(f"'{name}' needs dates as month and day, like 10-01")
        clean.append({"id": str(s.get("id") or f"set{i + 1}"), "name": name, "start": start, "end": end,
                      "items": [str(k) for k in s.get("items") or []]})
    cfg["sets"] = clean
    return _store(cfg)


def _valid_md(value: str) -> bool:
    try:
        month, day = (int(x) for x in value.split("-"))
        date(2000, month, day)
        return True
    except (ValueError, TypeError):
        return False


# --- what plays today ----------------------------------------------------------------

def _in_window(start: str, end: str, today: date) -> bool:
    day = (today.month, today.day)
    first, last = tuple(int(x) for x in start.split("-")), tuple(int(x) for x in end.split("-"))
    return first <= day <= last if first <= last else (day >= first or day <= last)   # may span New Year


def active_set(cfg: dict, today: date | None = None) -> dict:
    """The set in effect today: the first seasonal set whose dates include today, else the default."""
    today = today or date.today()
    for s in cfg["sets"]:
        if s["items"] and _in_window(s["start"], s["end"], today):
            return s
    return {"id": "default", "name": "Default", "items": cfg["default"]}


def next_change(cfg: dict, today: date | None = None) -> dict | None:
    """When the active set next changes: {date, set} within the coming year, or None."""
    from datetime import timedelta
    today = today or date.today()
    current = active_set(cfg, today)["id"]
    for n in range(1, 367):
        day = today + timedelta(days=n)
        s = active_set(cfg, day)
        if s["id"] != current:
            return {"date": day.isoformat(), "set": s["name"]}
    return None


def build_value(cfg: dict, paths: list[str], today: date | None = None) -> str:
    """The CinemaTrailersPrerollID string for these clip paths and the play mode."""
    if not paths:
        return ""
    if cfg["mode"] == "sequence":
        return ",".join(paths)
    if cfg["mode"] == "daily":           # the same few clips all day, a new pick each day
        today = today or date.today()
        pick = random.Random(today.toordinal()).sample(paths, min(cfg["daily_count"], len(paths)))
        return ",".join(pick)
    return ";".join(paths)


def parse_value(value: str) -> tuple[list[str], str]:
    """(paths, "random" or "sequence") from a CinemaTrailersPrerollID string."""
    value = (value or "").strip()
    if not value:
        return [], "random"
    sep, mode = (",", "sequence") if "," in value and ";" not in value else (";", "random")
    return [p.strip() for p in value.split(sep) if p.strip()], mode


# --- Plex -----------------------------------------------------------------------------

def clips(plex: Plex, section_id: str) -> list[dict]:
    """The clips in the preroll library: [{ratingKey, title, duration (s), thumb, file}]."""
    section = next((s for s in plex.all_sections() if s["id"] == str(section_id)), None)
    if not section:
        raise PrerollError("That preroll library wasn't found in Plex")
    out = []
    for item in plex._paged(f"/library/sections/{section['id']}/all", {}):
        parts = [p for m in item.get("Media") or [] for p in m.get("Part") or [] if p.get("file")]
        if not parts:
            continue
        out.append({"ratingKey": str(item["ratingKey"]), "title": item.get("title") or "",
                    "duration": round((item.get("duration") or 0) / 1000), "thumb": item.get("thumb") or "",
                    "file": parts[0]["file"]})
    return sorted(out, key=lambda c: c["title"].lower())


def _guess_library(libraries: list[dict]) -> str:
    """A library called "PreRolls", "Pre-rolls", ... ("" when there's none)."""
    guess = next((s for s in libraries if "preroll" in "".join(c for c in (s["title"] or "").lower() if c.isalnum())), None)
    return guess["id"] if guess else ""


def library_id(plex: Plex) -> str:
    """The preroll library: the one chosen on the Prerolls page, else one named like "PreRolls"."""
    return load()["section_id"] or _guess_library(plex.all_sections())


def overview(today: date | None = None) -> dict:
    """Everything the Prerolls page shows: settings, clips, Plex's current value matched to clips."""
    cfg = load()
    with plexmod.from_settings(db.get_settings()) as plex:
        libraries = plex.all_sections()
        if not cfg["section_id"]:        # a library called "PreRolls", "Pre-rolls", ... by default
            cfg["section_id"] = _guess_library(libraries)
        current = plex.pref(PREF) or ""
        items = clips(plex, cfg["section_id"]) if cfg["section_id"] else []
    paths, current_mode = parse_value(current)
    by_path = {c["file"]: c["ratingKey"] for c in items}
    # Not set up yet: start from what Plex plays now (saved once the user saves the page).
    from_plex = not cfg["enabled"] and cfg["backup"] is None and not cfg["default"] and not cfg["sets"]
    if from_plex:
        cfg["default"] = [by_path[p] for p in paths if p in by_path]
        cfg["mode"] = current_mode
    active = active_set(cfg, today)
    return {
        "settings": cfg, "libraries": libraries, "clips": items, "from_plex": from_plex and bool(cfg["default"]),
        "current": {"value": current, "mode": current_mode,
                    "matched": [by_path[p] for p in paths if p in by_path],
                    "unmatched": [p for p in paths if p not in by_path]},
        "active": {"id": active["id"], "name": active["name"], "count": len(active["items"])},
        "next_change": next_change(cfg, today),
    }


def apply(today: date | None = None, force: bool = False) -> dict:
    """Write today's preroll list to Plex when managing is on. Returns what was done."""
    cfg = load()
    if not cfg["enabled"] or not cfg["section_id"]:
        return {"applied": False, "reason": "Preroll management is off"}
    with plexmod.from_settings(db.get_settings()) as plex:
        current = plex.pref(PREF) or ""
        if cfg["backup"] is None:        # the value Plex had before Curatarr first changed it
            cfg["backup"], cfg["backup_at"] = current, db.now()
        by_key = {c["ratingKey"]: c["file"] for c in clips(plex, cfg["section_id"])}
        active = active_set(cfg, today)
        paths = [by_key[k] for k in active["items"] if k in by_key]
        value = build_value(cfg, paths, today)
        if value != current or force:
            plex.set_server_prefs({PREF: value})
            log.info("Prerolls: '%s' set active, %d clip(s) (%s)", active["name"], len(paths), cfg["mode"])
    cfg.update(applied=value, applied_at=db.now(), applied_set=active["name"])
    _store(cfg)
    return {"applied": True, "set": active["name"], "clips": len(paths), "value": value}


def restore() -> dict:
    """Put Plex's original preroll list back and stop managing it."""
    cfg = load()
    if cfg["backup"] is None:
        raise PrerollError("Curatarr hasn't changed Plex's prerolls, so there's nothing to restore")
    with plexmod.from_settings(db.get_settings()) as plex:
        plex.set_server_prefs({PREF: cfg["backup"]})
    log.info("Prerolls: restored Plex's original preroll list and stopped managing it")
    cfg.update(enabled=False, applied=None, applied_at=None, applied_set=None, backup=None, backup_at=None)
    _store(cfg)
    return {"restored": True}


def daily() -> None:
    """Scheduler job: switch sets on their dates (and pick new daily clips)."""
    try:
        result = apply()
        if result.get("applied"):
            log.debug("Prerolls daily update: %s", result)
    except (PlexError, PrerollError) as exc:
        log.warning("Prerolls: daily update failed: %s", exc)
