"""Starter packs: ready-made collections built from TMDB discover queries.

Company and network ids were checked against themoviedb.org.
"""

STUDIOS = [   # (name, TMDB company id)
    ("Pixar", 3), ("Walt Disney Animation Studios", 6125), ("DreamWorks Animation", 521),
    ("Studio Ghibli", 10342), ("LAIKA", 11537), ("Aardman", 297), ("Marvel Studios", 420),
    ("Lucasfilm", 1), ("A24", 41077), ("Blumhouse", 3172), ("Legendary Pictures", 923),
    ("New Line Cinema", 12),
]
NETWORKS = [  # (name, TMDB network id)
    ("HBO", 49), ("Netflix", 213), ("AMC", 174), ("FX", 88), ("Apple TV+", 2552),
    ("Disney+", 2739), ("Prime Video", 1024), ("Hulu", 453), ("Showtime", 67), ("BBC One", 4),
]
MOVIE_GENRES = [
    ("Action", 28), ("Animation", 16), ("Comedy", 35), ("Crime", 80), ("Documentary", 99),
    ("Drama", 18), ("Family", 10751), ("Fantasy", 14), ("Horror", 27), ("Romance", 10749),
    ("Science Fiction", 878), ("Thriller", 53), ("War", 10752), ("Western", 37),
]
TV_GENRES = [
    ("Animation", 16), ("Comedy", 35), ("Crime", 80), ("Documentary", 99), ("Drama", 18),
    ("Kids", 10762), ("Mystery", 9648), ("Sci-Fi & Fantasy", 10765), ("Reality", 10764),
    ("Western", 37),
]
MOVIE_DECADES = range(1950, 2030, 10)
TV_DECADES = range(1980, 2030, 10)


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")


def _item(group: str, name: str, value: str, limit: int, order: str, about: str) -> dict:
    return {"key": f"{group}.{_slug(name)}", "name": name, "about": about,
            "source": {"type": "tmdb_discover", "value": value, "limit": limit}, "order": order}


def _build() -> list[dict]:
    packs = [
        {"key": "studios", "media": "movie", "name": "Studios",
         "about": "Every feature film from the studio, oldest first.",
         "items": [_item("studios", f"{name} Collection",
                         f"movie?with_companies={cid}&with_runtime.gte=60&sort_by=primary_release_date.asc",
                         500, "release", f"TMDB company {cid}") for name, cid in STUDIOS]},
        {"key": "movie-decades", "media": "movie", "name": "Decades",
         "about": "The 100 most-rated movies of each decade.",
         "items": [_item("movie-decades", f"Best of the {y}s",
                         f"movie?primary_release_date.gte={y}-01-01&primary_release_date.lte={y + 9}-12-31"
                         "&sort_by=vote_count.desc", 100, "custom", f"{y}–{y + 9}") for y in MOVIE_DECADES]},
        {"key": "movie-genres", "media": "movie", "name": "Top rated by genre",
         "about": "The 100 highest-rated movies of each genre (at least 1,000 votes).",
         "items": [_item("movie-genres", f"Top {name}",
                         f"movie?with_genres={gid}&vote_count.gte=1000&sort_by=vote_average.desc",
                         100, "custom", f"TMDB genre {gid}") for name, gid in MOVIE_GENRES]},
        {"key": "networks", "media": "show", "name": "Networks & streamers",
         "about": "The 200 most popular shows from each network.",
         "items": [_item("networks", f"{name} Originals",
                         f"tv?with_networks={nid}&sort_by=popularity.desc", 200, "custom",
                         f"TMDB network {nid}") for name, nid in NETWORKS]},
        {"key": "tv-decades", "media": "show", "name": "Decades",
         "about": "The 100 most-rated shows that started in each decade.",
         "items": [_item("tv-decades", f"Best TV of the {y}s",
                         f"tv?first_air_date.gte={y}-01-01&first_air_date.lte={y + 9}-12-31"
                         "&sort_by=vote_count.desc", 100, "custom", f"{y}–{y + 9}") for y in TV_DECADES]},
        {"key": "tv-genres", "media": "show", "name": "Top rated by genre",
         "about": "The 100 highest-rated shows of each genre (at least 200 votes).",
         "items": [_item("tv-genres", f"Top {name} Shows",
                         f"tv?with_genres={gid}&vote_count.gte=200&sort_by=vote_average.desc",
                         100, "custom", f"TMDB genre {gid}") for name, gid in TV_GENRES]},
    ]
    return packs


PACKS = _build()
ITEMS = {item["key"]: (pack, item) for pack in PACKS for item in pack["items"]}


def collection_config(item: dict, section: dict, sync_mode: str = "sync",
                      request_missing: bool = False) -> dict:
    return {
        "name": item["name"], "library": section["title"], "section_id": section["id"],
        "sources": [dict(item["source"])], "order": item["order"], "sync_mode": sync_mode,
        "request_missing": request_missing,
    }
