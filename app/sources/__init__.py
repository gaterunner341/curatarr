"""List source registry: turns a collection's sources into MediaRefs."""
import re
from typing import Callable

from . import imdb, mdblist, tmdb, trakt
from .base import MediaRef, SourceContext, SourceError

Fetcher = Callable[[str, SourceContext, int | None], list[MediaRef]]


def _from_csv(value: str) -> list[MediaRef]:
    """IMDb list exports are CSVs with a ``Const`` column of title ids."""
    seen: dict[str, None] = {}
    for tt in re.findall(r"\btt\d{7,}\b", value):
        seen.setdefault(tt, None)
    return [MediaRef(None, imdb=tt) for tt in seen]


def fetch_static(value: str, ctx: SourceContext, limit: int | None) -> list[MediaRef]:
    """One id per line or comma: ``tt0133093``, ``imdb:tt0133093``, ``tmdb:603``, ``tvdb:81189``.

    A pasted IMDb CSV export is accepted too.
    """
    if re.search(r"^\s*(Position,)?\s*Const\b", value, re.M | re.I):
        refs = _from_csv(value)
        return refs[:limit] if limit else refs
    refs: list[MediaRef] = []
    for token in re.split(r"[\s,]+", value):
        token = token.strip()
        if not token:
            continue
        provider, _, ident = token.rpartition(":")
        provider = provider.lower() or ("imdb" if ident.startswith("tt") else "")
        if provider == "imdb" and re.fullmatch(r"tt\d+", ident):
            refs.append(MediaRef(None, imdb=ident))
        elif provider == "tmdb" and ident.isdigit():
            refs.append(MediaRef(None, tmdb=int(ident)))
        elif provider == "tvdb" and ident.isdigit():
            refs.append(MediaRef(None, tvdb=int(ident)))
        else:
            raise SourceError(f"Unrecognised id '{token}' (use imdb:tt…, tmdb:123 or tvdb:123)")
    return refs[:limit] if limit else refs


FETCHERS: dict[str, Fetcher] = {
    "tmdb_list": tmdb.fetch_list,
    "tmdb_collection": tmdb.fetch_collection,
    "tmdb_chart": tmdb.fetch_chart,
    "tmdb_discover": tmdb.fetch_discover,
    "imdb_list": imdb.fetch_list,
    "imdb_chart": imdb.fetch_chart,
    "trakt_list": trakt.fetch_list,
    "trakt_chart": trakt.fetch_chart,
    "mdblist": mdblist.fetch_list,
    "static": fetch_static,
}

# Describes each source for the web UI.
CATALOG = [
    {"type": "tmdb_list", "label": "TMDB list or page link", "provider": "TMDB",
     "placeholder": "themoviedb.org link: list, collection, company (studio), keyword, network or person"},
    {"type": "tmdb_collection", "label": "TMDB collection (franchise)", "provider": "TMDB",
     "placeholder": "https://www.themoviedb.org/collection/10 or 10"},
    {"type": "tmdb_chart", "label": "TMDB chart", "provider": "TMDB", "options": tmdb.CHARTS},
    {"type": "tmdb_discover", "label": "TMDB discover query", "provider": "TMDB",
     "placeholder": "movie?with_genres=27&sort_by=vote_average.desc&vote_count.gte=1000"},
    {"type": "imdb_list", "label": "IMDb list / watchlist", "provider": "IMDb",
     "placeholder": "https://www.imdb.com/list/ls055592025/ or ls055592025"},
    {"type": "imdb_chart", "label": "IMDb chart", "provider": "IMDb", "options": imdb.CHARTS},
    {"type": "trakt_list", "label": "Trakt list / watchlist", "provider": "Trakt",
     "placeholder": "https://trakt.tv/users/username/lists/list-slug"},
    {"type": "trakt_chart", "label": "Trakt chart", "provider": "Trakt", "options": trakt.CHARTS},
    {"type": "mdblist", "label": "MDBList list", "provider": "MDBList",
     "placeholder": "https://mdblist.com/lists/username/list-slug"},
    {"type": "static", "label": "Static ids", "provider": "Manual",
     "placeholder": "tt0133093, tmdb:604, tvdb:81189 — or paste an IMDb list CSV export"},
]


def fetch_source(source, ctx: SourceContext) -> list[MediaRef]:
    fetcher = FETCHERS.get(source.type)
    if not fetcher:
        raise SourceError(f"Unknown source type '{source.type}'")
    if not source.value:
        raise SourceError(f"{source.type} needs a value")
    return fetcher(source.value, ctx, source.limit)


def resolve(sources, ctx: SourceContext, item_limit: int = 0) -> tuple[list[MediaRef], list[str]]:
    """Fetch every source, merge them in order and drop duplicates and wrong media types.

    Returns the merged refs and a list of per-source error messages; a failing
    source does not stop the others.
    """
    merged: list[MediaRef] = []
    seen: set[str] = set()
    errors: list[str] = []
    for source in sources:
        try:
            refs = fetch_source(source, ctx)
        except SourceError as exc:
            errors.append(f"{source.type}: {exc}")
            continue
        for ref in refs:
            if ref.media_type and ref.media_type != ctx.media_type:
                continue
            ref.media_type = ref.media_type or ctx.media_type
            key = ref.key()
            if key not in seen:
                seen.add(key)
                merged.append(ref)
    if item_limit:
        merged = merged[:item_limit]
    return merged, errors


__all__ = ["CATALOG", "MediaRef", "SourceContext", "SourceError", "resolve", "fetch_source"]
