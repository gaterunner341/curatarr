"""Built-in holiday collections with default home screen calendars.

Each holiday becomes an ordinary Curatarr collection when it is switched on,
tagged with ``holiday`` so the Holidays page can find it. Its dates repeat
every year and can be edited afterwards like any other collection.

``sources`` and ``poster`` are filled in per holiday; a holiday without
sources is listed but can't be switched on yet. Posters live in
``app/static/holidays/`` and are copied into the config folder on enable.
"""
import json
import re
import shutil
from datetime import date
from pathlib import Path

from . import config

POSTER_DIR = Path(__file__).parent / "static" / "holidays"

HOLIDAY_LIMIT = 100   # most popular titles per holiday; keeps Radarr requests sane


def _keyword(keyword_id: int | str) -> list[dict]:
    """A TMDB keyword (or several, as "613|5632") as a source: its most popular movies."""
    return [{"type": "tmdb_discover",
             "value": f"movie?with_keywords={keyword_id}&sort_by=popularity.desc",
             "limit": HOLIDAY_LIMIT}]


# start/end are "MM-DD" and repeat yearly; windows may cross New Year.
# "link" is the TMDB page the list comes from, shown on the Holidays page.
HOLIDAYS: list[dict] = [
    {"key": "new-years", "name": "New Year's", "start": "12-26", "end": "01-02",
     "link": "https://www.themoviedb.org/keyword/613-new-year-s-eve/movie",
     "sources": _keyword("613|5632"), "poster": "new-years.jpg"},
    # Lunar New Year falls between Jan 21 and Feb 20.
    {"key": "lunar-new-year", "name": "Lunar New Year", "start": "01-20", "end": "02-20",
     "link": "https://www.themoviedb.org/keyword/250496-chinese-new-year/movie",
     "sources": _keyword("250496|356063"), "poster": "lunar-new-year.jpg"},
    {"key": "football", "name": "Football", "start": "01-25", "end": "02-15",
     "link": "https://www.themoviedb.org/keyword/579-american-football/movie",
     "sources": _keyword(579), "poster": "football.jpg"},
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
    # Mother's Day is the second Sunday in May, Father's Day the third Sunday in June.
    {"key": "mothers-day", "name": "Mother's Day", "start": "05-01", "end": "05-14",
     "link": "https://www.themoviedb.org/keyword/173983-mother-s-day/movie",
     "sources": _keyword(173983), "poster": "mothers-day.jpg"},
    {"key": "fathers-day", "name": "Father's Day", "start": "06-01", "end": "06-21",
     "link": "https://www.themoviedb.org/keyword/195439-father-s-day/movie",
     "sources": _keyword(195439), "poster": "fathers-day.jpg"},
    {"key": "independence-day", "name": "Independence Day", "start": "06-25", "end": "07-04",
     "link": "https://www.themoviedb.org/keyword/282190-4th-of-july/movie",
     "sources": _keyword(282190), "poster": "independence-day.jpg"},
    {"key": "back-to-school", "name": "Back to School", "start": "08-10", "end": "09-10",
     "link": "https://www.themoviedb.org/keyword/187282-back-to-school/movie",
     "sources": _keyword("187282|6270"), "poster": "back-to-school.jpg"},
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
    # Hanukkah starts between late November and late December.
    {"key": "hanukkah", "name": "Hanukkah", "start": "11-28", "end": "01-02",
     "link": "https://www.themoviedb.org/keyword/7328-hanukkah/movie",
     "sources": _keyword("7328|272884"), "poster": "hanukkah.jpg"},
]

BY_KEY = {h["key"]: h for h in HOLIDAYS}

# --- holidays you add yourself -----------------------------------------------------
# Stored in the "custom_holidays" setting as JSON; their posters are drawn by the
# app (app.posters) into the config folder.

CUSTOM_PREFIX = "custom-"
CUSTOM_POSTER_DIR = config.CONFIG_DIR / "holiday-posters"
DATE_RE = re.compile(r"(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])")


def _saved_custom() -> list[dict]:
    from . import db                        # local import: db imports nothing from here
    try:
        saved = json.loads(db.get_settings().get("custom_holidays") or "[]")
    except ValueError:
        return []
    return [h for h in saved if isinstance(h, dict) and h.get("key")]


def custom_holidays() -> list[dict]:
    return [{**h, "custom": True, "sources": sources_for_link(h.get("link", "")),
             "poster": f"{h['key']}.jpg"} for h in _saved_custom()]


def all_holidays() -> list[dict]:
    """Built-in holidays, then your own."""
    return HOLIDAYS + custom_holidays()


def get(key: str) -> dict | None:
    return BY_KEY.get(key) or next((h for h in custom_holidays() if h["key"] == key), None)


def sources_for_link(link: str) -> list[dict]:
    """A TMDB keyword page becomes its most popular movies; other TMDB links are list sources."""
    link = link.strip()
    match = re.search(r"/keyword/(\d+)", link)
    if match:
        return _keyword(int(match.group(1)))
    if re.search(r"themoviedb\.org/(list|collection|company|network|person)/\d+", link):
        return [{"type": "tmdb_list", "value": link, "limit": HOLIDAY_LIMIT}]
    return []


def save_custom(entry: dict) -> dict:
    """Add or replace one of your holidays and draw its poster. Returns the stored entry."""
    from . import db, posters
    name = (entry.get("name") or "").strip()
    start, end = (entry.get("start") or "").strip(), (entry.get("end") or "").strip()
    link = (entry.get("link") or "").strip()
    if not name:
        raise ValueError("Give the holiday a name")
    if not (DATE_RE.fullmatch(start) and DATE_RE.fullmatch(end)):
        raise ValueError("Dates must be a month and day, like 03-14")
    if not sources_for_link(link):
        raise ValueError("Paste a TMDB keyword or list link, like https://www.themoviedb.org/keyword/9840")
    scheme = entry.get("scheme") if entry.get("scheme") in posters.SCHEMES else "royal"
    saved = _saved_custom()
    key = entry.get("key") or CUSTOM_PREFIX + (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "holiday")
    if entry.get("key"):
        if not any(h["key"] == key for h in saved):
            raise ValueError("That holiday doesn't exist")
    elif key in BY_KEY or any(h["key"] == key for h in saved):
        raise ValueError(f"There's already a holiday called {name}")
    stored = {"key": key, "name": name, "start": start, "end": end, "link": link, "scheme": scheme}
    CUSTOM_POSTER_DIR.mkdir(parents=True, exist_ok=True)
    (CUSTOM_POSTER_DIR / f"{key}.jpg").write_bytes(posters.custom_poster(name, scheme))
    db.save_settings({"custom_holidays": json.dumps([h for h in saved if h["key"] != key] + [stored])})
    return stored


def delete_custom(key: str) -> None:
    from . import db
    db.save_settings({"custom_holidays": json.dumps([h for h in _saved_custom() if h["key"] != key])})
    (CUSTOM_POSTER_DIR / f"{key}.jpg").unlink(missing_ok=True)


def poster_path(holiday: dict) -> Path | None:
    if not holiday.get("poster"):
        return None
    path = (CUSTOM_POSTER_DIR if holiday.get("custom") else POSTER_DIR) / holiday["poster"]
    return path if path.is_file() else None


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


def collection_config(holiday: dict, section: dict, request_missing: bool = False,
                      seasonal_only: bool = False) -> dict:
    """Config for a new collection built from a holiday."""
    start, end = window_dates(holiday)
    cfg = {
        "request_missing": request_missing,
        "seasonal_only": seasonal_only,
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
        "pin_top": True,
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
        if "pin_top" not in cfg:            # 0.11.0: holidays go to the top while they're on
            changes["pin_top"] = True
        if changes:
            db.update_collection_config(row["id"], {**cfg, **changes})
            count += 1
    return count


def install_poster(holiday: dict, collection_id: int) -> str:
    """Copy the holiday's bundled poster into the config folder; returns the file name."""
    src = poster_path(holiday)
    if not src:
        return ""
    name = f"{collection_id}-poster{src.suffix.lower()}"
    shutil.copyfile(src, config.IMAGE_DIR / name)
    return name
