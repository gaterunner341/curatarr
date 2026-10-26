"""MDBList lists (needs an MDBList API key)."""
import re

import httpx

from .base import MediaRef, SourceContext, SourceError, to_int

API = "https://api.mdblist.com"


def list_path(value: str) -> str:
    value = value.strip()
    match = re.search(r"mdblist\.com/lists/([^/]+)/([^/?#]+)", value)
    if match:
        return f"/lists/{match.group(1)}/{match.group(2)}/items"
    if value.isdigit():
        return f"/lists/{value}/items"
    parts = value.strip("/").split("/")
    if len(parts) == 2:
        return f"/lists/{parts[0]}/{parts[1]}/items"
    raise SourceError("MDBList list must be an mdblist.com URL, 'username/list-slug' or a list id")


def _ref(item: dict) -> MediaRef:
    kind = item.get("mediatype") or item.get("media_type")
    media_type = "show" if kind in ("show", "tv") else ("movie" if kind == "movie" else None)
    return MediaRef(media_type, item.get("title") or "",
                    to_int(item.get("release_year") or item.get("year")),
                    imdb=item.get("imdb_id") or None,
                    tmdb=to_int(item.get("tmdb_id") or item.get("id")),
                    tvdb=to_int(item.get("tvdb_id")))


def fetch_list(value: str, ctx: SourceContext, limit: int | None) -> list[MediaRef]:
    api_key = ctx.settings.get("mdblist_api_key", "")
    if not api_key:
        raise SourceError("MDBList API key is not configured (Settings > MDBList)")
    path = list_path(value)
    try:
        resp = ctx.http.get(f"{API}{path}", params={"apikey": api_key})
    except httpx.HTTPError as exc:
        raise SourceError(f"MDBList request failed: {exc}") from exc
    if resp.status_code >= 400:
        raise SourceError(f"MDBList error {resp.status_code} for '{path}'")
    data = resp.json()
    if isinstance(data, dict):
        if data.get("error"):
            raise SourceError(f"MDBList: {data['error']}")
        items = [*(data.get("movies") or []), *(data.get("shows") or [])]
        items.sort(key=lambda i: i.get("rank") or 0)
    else:
        items = data
    refs = [_ref(i) for i in items]
    return refs[:limit] if limit else refs
