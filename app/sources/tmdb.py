"""The Movie Database (TMDB) lists, collections, charts and discover queries."""
import re
from urllib.parse import parse_qsl

import httpx

from .base import MediaRef, SourceContext, SourceError, to_int, year_of

API = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/original"
THUMB_BASE = "https://image.tmdb.org/t/p/w342"
DEFAULT_LIMIT = 100

CHARTS = {
    "movie/popular": "Popular movies",
    "movie/top_rated": "Top rated movies",
    "movie/now_playing": "Movies now playing",
    "movie/upcoming": "Upcoming movies",
    "trending/movie/day": "Trending movies (today)",
    "trending/movie/week": "Trending movies (this week)",
    "tv/popular": "Popular shows",
    "tv/top_rated": "Top rated shows",
    "tv/on_the_air": "Shows on the air",
    "tv/airing_today": "Shows airing today",
    "trending/tv/day": "Trending shows (today)",
    "trending/tv/week": "Trending shows (this week)",
}


class TMDB:
    def __init__(self, api_key: str, http: httpx.Client):
        if not api_key:
            raise SourceError("TMDB API key is not configured (Settings > TMDB)")
        self.http = http
        # v4 "API Read Access Tokens" are JWTs; v3 keys are 32 hex characters.
        if api_key.startswith("eyJ"):
            self.auth_headers = {"Authorization": f"Bearer {api_key}"}
            self.auth_params = {}
        else:
            self.auth_headers = {}
            self.auth_params = {"api_key": api_key}

    def get(self, path: str, **params) -> dict:
        try:
            resp = self.http.get(f"{API}/{path.lstrip('/')}",
                                 params={**self.auth_params, **params},
                                 headers={"Accept": "application/json", **self.auth_headers})
        except httpx.HTTPError as exc:
            raise SourceError(f"TMDB request failed: {exc}") from exc
        if resp.status_code == 401:
            raise SourceError("TMDB rejected the API key")
        if resp.status_code == 404:
            raise SourceError(f"TMDB could not find '{path}'")
        if resp.status_code >= 400:
            raise SourceError(f"TMDB error {resp.status_code} for '{path}'")
        return resp.json()

    def paged(self, path: str, limit: int, key: str = "results", **params) -> list[dict]:
        results: list[dict] = []
        page = 1
        while len(results) < limit:
            data = self.get(path, page=page, **params)
            batch = data.get(key) or []
            results.extend(batch)
            if not batch or page >= int(data.get("total_pages") or 1):
                break
            page += 1
        return results[:limit]

    def external_ids(self, media_type: str, tmdb_id: int) -> dict:
        kind = "tv" if media_type == "show" else "movie"
        return self.get(f"{kind}/{tmdb_id}/external_ids")

    def find(self, external_id: str, source: str) -> dict:
        return self.get(f"find/{external_id}", external_source=source)

    def poster_choices(self, query: str = "", collection_ids: list[int] = (), limit: int = 40) -> list[dict]:
        """Posters to choose from: a franchise's own posters first, then search matches.

        Each is {url (full size), thumb, label}.
        """
        found: dict[str, str] = {}

        def add_images(cid: int, label: str) -> None:
            data = self.get(f"collection/{cid}/images", include_image_language="en,null")
            for poster in data.get("posters") or []:
                found.setdefault(poster["file_path"], label)

        for cid in collection_ids:
            add_images(cid, "TMDB collection")
        if query.strip():
            results = self.get("search/collection", query=query.strip()).get("results") or []
            for result in results[:6]:
                if result.get("poster_path"):
                    found.setdefault(result["poster_path"], result.get("name") or "")
            if results and not collection_ids:
                add_images(results[0]["id"], results[0].get("name") or "")
        return [{"url": IMAGE_BASE + path, "thumb": THUMB_BASE + path, "label": label}
                for path, label in list(found.items())[:limit]]

    def collection_poster(self, collection_id: int) -> str | None:
        data = self.get(f"collection/{collection_id}")
        return IMAGE_BASE + data["poster_path"] if data.get("poster_path") else None


def _ref(item: dict, default_type: str | None) -> MediaRef | None:
    kind = item.get("media_type") or default_type
    if kind in ("tv", "show"):
        return MediaRef("show", item.get("name") or item.get("title") or "",
                        year_of(item.get("first_air_date")), tmdb=to_int(item.get("id")))
    if kind == "movie":
        return MediaRef("movie", item.get("title") or item.get("name") or "",
                        year_of(item.get("release_date")), tmdb=to_int(item.get("id")))
    return None   # people and other media types are ignored


def _first_number(value: str, pattern: str) -> int:
    match = re.search(pattern, value) or re.fullmatch(r"\s*(\d+)\S*\s*", value)
    if not match:
        raise SourceError(f"Could not find a TMDB id in '{value}'")
    return int(match.group(1))


# TMDB pages that map onto a discover query: (url pattern, discover filter).
PAGE_FILTERS = [
    (r"/company/(\d+)", "with_companies"),
    (r"/keyword/(\d+)", "with_keywords"),
    (r"/network/(\d+)", "with_networks"),
    (r"/person/(\d+)", "with_people"),
]
PAGE_LIMIT = 500


def _page_query(value: str, media_type: str) -> tuple[str, dict] | None:
    """Turn a studio/keyword/network/person page URL into a discover query."""
    for pattern, param in PAGE_FILTERS:
        match = re.search(pattern, value)
        if match:
            if param == "with_networks" or re.search(r"/tv\b", value):
                kind = "tv"
            elif re.search(r"/movie\b", value):
                kind = "movie"
            else:
                kind = "tv" if media_type == "show" else "movie"
            date_field = "first_air_date" if kind == "tv" else "primary_release_date"
            return kind, {param: match.group(1), "sort_by": f"{date_field}.desc"}
    return None


def fetch_list(value: str, ctx: SourceContext, limit: int | None) -> list[MediaRef]:
    """A TMDB list, or any TMDB collection / studio / keyword / network / person page."""
    if "/collection/" in value:
        return fetch_collection(value, ctx, limit)
    page = _page_query(value, ctx.media_type)
    if page:
        kind, params = page
        items = TMDB(ctx.settings.get("tmdb_api_key", ""), ctx.http).paged(
            f"discover/{kind}", limit or PAGE_LIMIT, **params)
        return [r for r in (_ref(i, kind) for i in items) if r]
    if not re.search(r"/list/\d+", value) and not value.strip().isdigit():
        raise SourceError(
            f"'{value}' is not a TMDB list. Use a themoviedb.org list, collection, company, "
            "keyword, network or person link (or a list id)")
    list_id = _first_number(value, r"/list/(\d+)")
    items = TMDB(ctx.settings.get("tmdb_api_key", ""), ctx.http).paged(
        f"list/{list_id}", limit or 10000, key="items")
    return [r for r in (_ref(i, None) for i in items) if r]


def fetch_collection(value: str, ctx: SourceContext, limit: int | None) -> list[MediaRef]:
    coll_id = _first_number(value, r"/collection/(\d+)")
    data = TMDB(ctx.settings.get("tmdb_api_key", ""), ctx.http).get(f"collection/{coll_id}")
    parts = sorted(data.get("parts") or [], key=lambda p: p.get("release_date") or "9999")
    refs = [r for r in (_ref(p, "movie") for p in parts) if r]
    return refs[:limit] if limit else refs


def fetch_chart(value: str, ctx: SourceContext, limit: int | None) -> list[MediaRef]:
    chart = value.strip("/ ").lower()
    if chart not in CHARTS:
        raise SourceError(f"Unknown TMDB chart '{value}'. Use one of: {', '.join(CHARTS)}")
    default_type = "tv" if "tv" in chart.split("/") else "movie"
    items = TMDB(ctx.settings.get("tmdb_api_key", ""), ctx.http).paged(chart, limit or DEFAULT_LIMIT)
    return [r for r in (_ref(i, default_type) for i in items) if r]


def fetch_discover(value: str, ctx: SourceContext, limit: int | None) -> list[MediaRef]:
    """value looks like ``movie?with_genres=27&sort_by=vote_average.desc``."""
    kind, _, query = value.partition("?")
    kind = kind.strip("/ ").lower().replace("discover/", "")
    if kind not in ("movie", "tv"):
        raise SourceError("TMDB discover must start with 'movie?' or 'tv?'")
    params = dict(parse_qsl(query))
    items = TMDB(ctx.settings.get("tmdb_api_key", ""), ctx.http).paged(
        f"discover/{kind}", limit or DEFAULT_LIMIT, **params)
    return [r for r in (_ref(i, kind) for i in items) if r]
