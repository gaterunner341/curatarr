"""Trakt lists, watchlists and charts (needs a Trakt API client id)."""
import re

import httpx

from .base import MediaRef, SourceContext, SourceError, to_int

API = "https://api.trakt.tv"
DEFAULT_LIMIT = 100

CHARTS = {
    "movies/trending": "Trending movies",
    "movies/popular": "Popular movies",
    "movies/anticipated": "Anticipated movies",
    "movies/boxoffice": "Box office movies",
    "movies/watched/weekly": "Most watched movies (week)",
    "movies/watched/monthly": "Most watched movies (month)",
    "movies/watched/all": "Most watched movies (all time)",
    "shows/trending": "Trending shows",
    "shows/popular": "Popular shows",
    "shows/anticipated": "Anticipated shows",
    "shows/watched/weekly": "Most watched shows (week)",
    "shows/watched/monthly": "Most watched shows (month)",
    "shows/watched/all": "Most watched shows (all time)",
}


def _get(ctx: SourceContext, path: str, params: dict | None = None) -> list:
    client_id = ctx.settings.get("trakt_client_id", "")
    if not client_id:
        raise SourceError("Trakt client id is not configured (Settings > Trakt)")
    try:
        resp = ctx.http.get(f"{API}{path}", params=params, headers={
            "Content-Type": "application/json",
            "trakt-api-version": "2",
            "trakt-api-key": client_id,
        })
    except httpx.HTTPError as exc:
        raise SourceError(f"Trakt request failed: {exc}") from exc
    if resp.status_code in (401, 403):
        raise SourceError("Trakt rejected the request (check the client id / list privacy)")
    if resp.status_code == 404:
        raise SourceError(f"Trakt could not find '{path}'")
    if resp.status_code >= 400:
        raise SourceError(f"Trakt error {resp.status_code} for '{path}'")
    return resp.json()


def _ref(entry: dict) -> MediaRef | None:
    for key, media_type in (("movie", "movie"), ("show", "show")):
        obj = entry.get(key)
        if obj is None and key == "movie" and "ids" in entry:
            obj = entry   # chart endpoints such as /popular return bare objects
            media_type = None
        if obj:
            ids = obj.get("ids") or {}
            return MediaRef(media_type, obj.get("title") or "", to_int(obj.get("year")),
                            imdb=ids.get("imdb"), tmdb=to_int(ids.get("tmdb")),
                            tvdb=to_int(ids.get("tvdb")))
    return None


def parse_list(value: str) -> tuple[str, str]:
    match = re.search(r"users/([^/]+)/(?:lists/)?([^/?#]+)", value)
    if match:
        return match.group(1), match.group(2)
    parts = value.strip("/ ").split("/")
    if len(parts) == 2:
        return parts[0], parts[1]
    raise SourceError("Trakt list must be a trakt.tv URL or 'username/list-slug'")


def fetch_list(value: str, ctx: SourceContext, limit: int | None) -> list[MediaRef]:
    user, slug = parse_list(value)
    path = (f"/users/{user}/watchlist/movie,show" if slug == "watchlist"
            else f"/users/{user}/lists/{slug}/items/movie,show")
    refs = [r for r in (_ref(e) for e in _get(ctx, path)) if r]
    return refs[:limit] if limit else refs


def fetch_chart(value: str, ctx: SourceContext, limit: int | None) -> list[MediaRef]:
    chart = value.strip("/ ").lower()
    if chart not in CHARTS:
        raise SourceError(f"Unknown Trakt chart '{value}'. Use one of: {', '.join(CHARTS)}")
    media_type = "show" if chart.startswith("shows") else "movie"
    refs = [r for r in (_ref(e) for e in _get(ctx, f"/{chart}", {"limit": limit or DEFAULT_LIMIT})) if r]
    for ref in refs:
        ref.media_type = media_type
    return refs
