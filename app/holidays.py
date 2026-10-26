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

# start/end are "MM-DD" and repeat yearly; windows may cross New Year.
HOLIDAYS: list[dict] = [
    {"key": "new-years", "name": "New Year's", "start": "12-26", "end": "01-02",
     "sources": [], "poster": ""},
    {"key": "valentines", "name": "Valentine's Day", "start": "02-01", "end": "02-14",
     "sources": [], "poster": ""},
    {"key": "st-patricks", "name": "St. Patrick's Day", "start": "03-10", "end": "03-17",
     "sources": [], "poster": ""},
    {"key": "easter", "name": "Easter", "start": "03-20", "end": "04-25",
     "sources": [], "poster": ""},
    {"key": "independence-day", "name": "Independence Day", "start": "06-25", "end": "07-04",
     "sources": [], "poster": ""},
    {"key": "halloween", "name": "Halloween", "start": "10-01", "end": "10-31",
     "sources": [], "poster": ""},
    {"key": "thanksgiving", "name": "Thanksgiving", "start": "11-01", "end": "11-30",
     "sources": [], "poster": ""},
    {"key": "christmas", "name": "Christmas", "start": "11-25", "end": "12-26",
     "sources": [], "poster": ""},
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


def collection_config(holiday: dict, section: dict) -> dict:
    """Config for a new collection built from a holiday."""
    start, end = window_dates(holiday)
    cfg = {
        "name": f"{holiday['name']} Collection",
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
