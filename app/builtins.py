"""Built-in collections (the Hall of Fame page), such as the IMDb Top 250.

A built-in collection has a fixed look (name, poster, ribbon, order); only its feed (the list
it follows), whether it's on, its schedule and the Radarr setting can be changed. Every save
goes through ``enforce`` so the fixed settings stay as defined here.
"""
import io

from PIL import Image, ImageDraw

from . import config
from .posters import PosterError, font

BUILTINS: list[dict] = [
    {
        "key": "imdb_top_250",
        "name": "IMDb Top 250",
        "media": "movie",
        "description": "The 250 highest-rated movies on IMDb, in IMDb's order.",
        "sources": {"movie": {"type": "tmdb_list", "value": "https://www.themoviedb.org/list/634-top-250-imdb"}},
        # Earlier default feeds, and what a collection still on one moves to.
        "moved_sources": [({"type": "imdb_chart", "value": "top"},
                           {"type": "tmdb_list", "value": "https://www.themoviedb.org/list/634-top-250-imdb"})],
        "poster": "imdb",
        "fixed": {
            "name": "IMDb Top 250",
            "summary": "The 250 highest-rated movies on IMDb, as voted by IMDb users.",
            "order": "custom",
            "sync_mode": "sync",
            "ribbon": {"enabled": True, "text": "IMDb TOP 250", "color": "#f5c518", "text_color": "#000000",
                       "corner": "bottom-right", "size": "medium", "font": "sans", "image": "imdb_top_250"},
        },
    },
    {
        "key": "netflix_top_10",
        "name": "Netflix Top 10",
        "media": "any",
        "description": "This week's most-watched on Netflix worldwide (netflix.com/tudum/top10): the top 10 films "
                       "in movie libraries, the top 10 shows in TV libraries. Needs a TMDB API key to match titles.",
        "sources": {"movie": {"type": "tmdb_list", "value": "https://www.themoviedb.org/list/8300585-top-10-movies-netflix"},
                    "show": {"type": "netflix_chart", "value": "tv"}},
        "moved_sources": [({"type": "netflix_chart", "value": "films"},
                           {"type": "tmdb_list", "value": "https://www.themoviedb.org/list/8300585-top-10-movies-netflix"})],
        "poster": "netflix",
        "fixed": {
            "name": "Netflix Top 10",
            "summary": "This week's most-watched on Netflix, in Netflix's order.",
            "order": "custom",
            "sync_mode": "sync",
            "ribbon": {"enabled": True, "text": "TOP 10", "color": "#f5c518", "text_color": "#000000",
                       "corner": "bottom-right", "size": "medium", "font": "sans", "image": "netflix_top_10"},
        },
    },
]

# What the user can still change on a built-in collection.
EDITABLE = ("sources", "enabled", "schedule", "request_missing", "exclude", "manual_order")

POSTER_FONTS = ["impact.ttf", "Anton-Regular.ttf", "RobotoCondensed-Bold.ttf", "LiberationSansNarrow-Bold.ttf",
                "ARIALNB.TTF", "DejaVuSans-Bold.ttf"]


def get(key: str) -> dict | None:
    return next((b for b in BUILTINS if b["key"] == key), None)


def collection_config(builtin: dict, section: dict, request_missing: bool = False,
                      keep: dict | None = None) -> dict:
    """Config for the built-in in ``section``. ``keep`` is an existing collection being taken
    over: its feed, schedule and the other editable settings are kept."""
    source = builtin["sources"].get(section["type"]) or next(iter(builtin["sources"].values()))
    cfg = {"name": builtin["name"], "library": section["title"], "section_id": section["id"],
           "sources": [dict(source)], "request_missing": request_missing}
    if keep:
        cfg.update({k: keep[k] for k in EDITABLE if k in keep})
    cfg.update({k: (dict(v) if isinstance(v, dict) else v) for k, v in builtin["fixed"].items()})
    cfg["builtin"] = builtin["key"]
    return cfg


def enforce(new: dict, old: dict) -> dict:
    """A built-in collection's saved config: the old one with only the editable settings taken
    from ``new``, and the fixed ones as defined."""
    builtin = get(old.get("builtin", ""))
    if not builtin:
        return new
    cfg = {**old, **{k: new[k] for k in EDITABLE if k in new}}
    cfg.update({k: (dict(v) if isinstance(v, dict) else v) for k, v in builtin["fixed"].items()})
    return cfg


def refresh_all() -> int:
    """Re-apply each built-in collection's fixed settings (they can change between versions).
    Returns how many collections changed."""
    from . import db                        # local import, as in holidays.backfill
    count = 0
    for row in db.list_collections():
        cfg = row["config"]
        builtin = get(cfg.get("builtin", ""))
        if builtin:
            fixed = enforce(cfg, cfg)
            moved = builtin.get("moved_sources", [])
            feed = [{k: s.get(k) for k in ("type", "value")} for s in cfg.get("sources") or []]
            if len(feed) == 1:              # still on an earlier default feed: move it to the new one
                new = next((dict(n) for old, n in moved if old == feed[0]), None)
                if new:
                    fixed["sources"] = [new]
            if fixed != cfg:
                db.update_collection_config(row["id"], fixed)
                count += 1
    return count


def poster(builtin: dict) -> bytes:
    """The built-in's poster as a JPEG."""
    return _netflix_poster() if builtin.get("poster") == "netflix" else _imdb_poster()


def _netflix_poster() -> bytes:
    """Black with "TOP 10" large in white and "NETFLIX" in red above it."""
    w, h = 1000, 1500
    img = Image.new("RGB", (w, h), (12, 12, 12))
    draw = ImageDraw.Draw(img)
    size = 400
    big, small = font(POSTER_FONTS, size), font(POSTER_FONTS, 130)
    while draw.textlength("TOP 10", font=big) > w * 0.84 and size > 100:
        size -= 10
        big = font(POSTER_FONTS, size)
    for text, fnt, colour, y in (("NETFLIX", small, (229, 9, 20), 430), ("TOP 10", big, (255, 255, 255), 600)):
        x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=fnt)
        draw.text(((w - (x1 - x0)) / 2 - x0, y - y0), text, font=fnt, fill=colour)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=92)
    return out.getvalue()


def _imdb_poster() -> bytes:
    """IMDb yellow with "THE / IMDb / TOP 250"."""
    w, h = 1000, 1500
    img = Image.new("RGB", (w, h), (229, 184, 30))
    draw = ImageDraw.Draw(img)
    try:
        big, small = font(POSTER_FONTS, 420), font(POSTER_FONTS, 120)
    except PosterError:
        big = small = None
    word, top, bottom = "IMDb", "THE", "TOP 250"
    if big:
        size = 420
        while draw.textlength(word, font=big) > w * 0.8 and size > 100:
            size -= 10
            big = font(POSTER_FONTS, size)
    bx0, by0, bx1, by1 = draw.textbbox((0, 0), word, font=big)
    x = (w - (bx1 - bx0)) / 2 - bx0
    y = (h - (by1 - by0)) / 2 - by0
    draw.text((x, y), word, font=big, fill=(0, 0, 0))
    left, right = x + bx0, x + bx1
    tx0, ty0, tx1, ty1 = draw.textbbox((0, 0), top, font=small)
    draw.text((left - tx0, y + by0 - 24 - ty1), top, font=small, fill=(0, 0, 0))
    sx0, sy0, sx1, sy1 = draw.textbbox((0, 0), bottom, font=small)
    draw.text((right - sx1, y + by1 + 24 - sy0), bottom, font=small, fill=(0, 0, 0))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=92)
    return out.getvalue()


def install_poster(builtin: dict, collection_id: int) -> str:
    """Write the built-in's poster into the config folder; returns the file name."""
    name = f"{collection_id}-poster.jpg"
    (config.IMAGE_DIR / name).write_bytes(poster(builtin))
    return name
