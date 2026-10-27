"""Built-in holiday collections with default home screen calendars.

Each holiday becomes an ordinary Curatarr collection when it is switched on,
tagged with ``holiday`` so the Holidays page can find it. Its dates repeat
every year and can be edited afterwards like any other collection.

``sources`` and ``poster`` are filled in per holiday; a holiday without
sources is listed but can't be switched on yet. Posters live in
``app/static/holidays/`` and are copied into the config folder on enable.
"""
import shutil
from datetime import date
from pathlib import Path

from . import config

POSTER_DIR = Path(__file__).parent / "static" / "holidays"

HOLIDAY_LIMIT = 100   # most popular titles per holiday; keeps Radarr requests sane


def _keyword(keyword_id: int) -> list[dict]:
    """A TMDB keyword as a source: its most popular movies."""
    return [{"type": "tmdb_discover",
             "value": f"movie?with_keywords={keyword_id}&sort_by=popularity.desc",
             "limit": HOLIDAY_LIMIT}]


# start/end are "MM-DD" and repeat yearly; windows may cross New Year.
# "link" is the TMDB page the list comes from, shown on the Holidays page.
HOLIDAYS: list[dict] = [
    {"key": "valentines", "name": "Valentine's Day", "start": "02-01", "end": "02-14",
     "link": "https://www.themoviedb.org/keyword/160404-valentine-s-day/movie",
     "sources": _keyword(160404), "poster": "valentines.jpg"},
    {"key": "st-patricks", "name": "St. Patrick's Day", "start": "03-10", "end": "03-17",
     "link": "https://www.themoviedb.org/keyword/209352-st-patrick-s-day/movie",
     "sources": _keyword(209352), "poster": "st-patricks.jpg"},
    # Easter moves each year; this window covers every possible date.
    {"key": "easter", "name": "Easter", "start": "03-20", "end": "04-25",
     "link": "https://www.themoviedb.org/keyword/9921-easter/movie",
     "sources": _keyword(9921), "poster": "easter.jpg"},
    {"key": "independence-day", "name": "Independence Day", "start": "06-25", "end": "07-04",
     "link": "https://www.themoviedb.org/keyword/282190-4th-of-july/movie",
     "sources": _keyword(282190), "poster": "independence-day.jpg"},
    {"key": "halloween", "name": "Halloween", "start": "10-01", "end": "10-31",
     "link": "https://www.themoviedb.org/keyword/3335-halloween/movie",
     "sources": _keyword(3335), "poster": "halloween.jpg"},
    {"key": "veterans-day", "name": "Veteran's Day", "start": "11-01", "end": "11-11",
     "link": "https://www.themoviedb.org/keyword/162365-military/movie",
     "sources": _keyword(162365), "poster": "veterans-day.jpg"},
    {"key": "thanksgiving", "name": "Thanksgiving", "start": "11-12", "end": "11-28",
     "link": "https://www.themoviedb.org/keyword/4543-thanksgiving/movie",
     "sources": _keyword(4543), "poster": "thanksgiving.jpg"},
    {"key": "christmas", "name": "Christmas", "start": "11-25", "end": "12-26",
     "link": "https://www.themoviedb.org/keyword/207317-christmas/movie",
     "sources": _keyword(207317), "poster": "christmas.jpg"},
]

BY_KEY = {h["key"]: h for h in HOLIDAYS}


def get(key: str) -> dict | None:
    return BY_KEY.get(key)


def available(holiday: dict) -> bool:
    return bool(holiday["sources"])


def window_dates(holiday: dict, year: int | None = None) -> tuple[str, str]:
    """The holiday's yearly window as YYYY-MM-DD strings (the year itself is ignored)."""
    year = year or date.today().year
    end_year = year + 1 if holiday["end"] < holiday["start"] else year
    return f"{year}-{holiday['start']}", f"{end_year}-{holiday['end']}"


SORT_PREFIX = "!01_"   # sorts holiday collections above everything else in Plex


def sort_title(holiday: dict) -> str:
    return f"{SORT_PREFIX}{holiday['name']} Collection"


def collection_config(holiday: dict, section: dict, request_missing: bool = False) -> dict:
    """Config for a new collection built from a holiday."""
    start, end = window_dates(holiday)
    cfg = {
        "request_missing": request_missing,
        "name": f"{holiday['name']} Collection",
        "sort_title": sort_title(holiday),
        "library": section["title"],
        "section_id": section["id"],
        "sources": [dict(s) for s in holiday["sources"]],
        "holiday": holiday["key"],
        "order": "release",
        "promote_recommended": True,
        "promote_home": True,
        "promote_shared": True,
        "promote_window": True,
        "promote_start": start,
        "promote_end": end,
        "promote_yearly": True,
    }
    return cfg


def backfill() -> int:
    """Bring holiday collections made by older versions up to date.

    Adds the built-in poster when no artwork is set and the !01_ sort title
    when none is set; anything the user chose is left alone.
    """
    from . import db                        # local import: db imports nothing from here
    count = 0
    for row in db.list_collections():
        cfg = row["config"]
        holiday = get(cfg.get("holiday", ""))
        if not holiday:
            continue
        changes = {}
        if not cfg.get("poster_file") and not cfg.get("poster_url"):
            name = install_poster(holiday, row["id"])
            if name:
                changes["poster_file"] = name
        if not cfg.get("sort_title"):
            changes["sort_title"] = sort_title(holiday)
        if changes:
            db.update_collection_config(row["id"], {**cfg, **changes})
            count += 1
    return count


def install_poster(holiday: dict, collection_id: int) -> str:
    """Copy the holiday's bundled poster into the config folder; returns the file name."""
    if not holiday.get("poster"):
        return ""
    src = POSTER_DIR / holiday["poster"]
    if not src.is_file():
        return ""
    name = f"{collection_id}-poster{src.suffix.lower()}"
    shutil.copyfile(src, config.IMAGE_DIR / name)
    return name
