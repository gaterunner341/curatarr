"""Build a collection from the Plex library itself, using Plex's own filters."""
from urllib.parse import parse_qsl

from ..plex import SECTION_TYPES, TYPE_MOVIE, parse_guid
from .base import MediaRef, SourceContext, SourceError

DEFAULT_LIMIT = 500


def filter_params(value: str) -> dict:
    """The filter query as params, without anything that could change who Plex thinks is asking.

    Plex operators are part of the key: ``year>>=1980`` parses as ``year>>`` = ``1980``.
    """
    params = {k: v for k, v in parse_qsl(value.strip().lstrip("?"), keep_blank_values=True)
              if k and not k.lower().startswith("x-plex")}
    if not params:
        raise SourceError("Plex filter is empty: pick at least one filter")
    return params


def fetch(value: str, ctx: SourceContext, limit: int | None) -> list[MediaRef]:
    """Titles in the collection's own library that match a Plex filter query.

    ``value`` is a query such as ``genre=12&year>>=1980&year<<=1989&unwatched=1``.
    """
    if not ctx.plex or not ctx.section:
        raise SourceError("Plex filter needs a connected Plex library")
    media = ctx.section["type"]
    items = ctx.plex._paged(f"/library/sections/{ctx.section['id']}/all", {
        **filter_params(value),
        "type": SECTION_TYPES.get(media, TYPE_MOVIE),
        "includeGuids": 1,
    })
    refs = []
    for item in items[:limit or DEFAULT_LIMIT]:
        ids = dict(filter(None, (parse_guid(g.get("id", "")) for g in item.get("Guid") or [])))
        refs.append(MediaRef(media, title=item.get("title") or "", year=item.get("year"),
                             imdb=ids.get("imdb"),
                             tmdb=int(ids["tmdb"]) if ids.get("tmdb", "").isdigit() else None,
                             tvdb=int(ids["tvdb"]) if ids.get("tvdb", "").isdigit() else None))
    return refs
