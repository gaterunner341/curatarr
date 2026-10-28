"""Thin client for the Plex Media Server HTTP API (JSON responses)."""
import logging
import re
from urllib.parse import quote

import httpx

from . import config

log = logging.getLogger(__name__)

# Plex metadata type numbers.
TYPE_MOVIE = 1
TYPE_SHOW = 2
TYPE_COLLECTION = 18
SECTION_TYPES = {"movie": TYPE_MOVIE, "show": TYPE_SHOW}

# collectionMode pref: how the collection appears inside the library.
COLLECTION_MODES = {"default": -1, "hide": 0, "hideItems": 1, "showItems": 2}
# collectionSort pref: 0 = release date, 1 = alphabetical, 2 = custom.
COLLECTION_ORDERS = {"release": 0, "alpha": 1, "custom": 2}

PAGE_SIZE = 500
MAX_PAGES = 400        # 200,000 items; a safety stop, not a real limit
BATCH_SIZE = 100

_LEGACY_AGENTS = {
    "com.plexapp.agents.imdb": "imdb",
    "com.plexapp.agents.themoviedb": "tmdb",
    "com.plexapp.agents.thetvdb": "tvdb",
    "com.plexapp.agents.tmdb": "tmdb",
    "com.plexapp.agents.tvdb": "tvdb",
}


class PlexError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def parse_guid(guid: str) -> tuple[str, str] | None:
    """Turn a Plex guid into (provider, id).

    Handles new-agent guids (``imdb://tt0111161``) and legacy agent guids
    (``com.plexapp.agents.thetvdb://81189/1/1?lang=en``).
    """
    if not guid or "://" not in guid:
        return None
    scheme, rest = guid.split("://", 1)
    provider = scheme if scheme in ("imdb", "tmdb", "tvdb") else _LEGACY_AGENTS.get(scheme)
    if not provider:
        return None
    ident = re.split(r"[/?]", rest, maxsplit=1)[0]
    if not ident:
        return None
    if provider == "imdb" and not ident.startswith("tt"):
        return None
    return provider, ident


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())


class LibraryIndex:
    """Lookup table from external ids (and title/year) to Plex rating keys."""

    def __init__(self, items: list[dict]):
        self.by_id: dict[tuple[str, str], str] = {}
        self.by_title: dict[str, str] = {}
        self.titles: dict[str, str] = {}
        self.ratings: dict[str, str] = {}
        for item in items:
            rk = str(item.get("ratingKey"))
            self.titles[rk] = item.get("title", "")
            if item.get("contentRating"):
                self.ratings[rk] = item["contentRating"]
            guids = [g.get("id", "") for g in item.get("Guid") or []]
            guids.append(item.get("guid", ""))
            for guid in guids:
                parsed = parse_guid(guid)
                if parsed:
                    self.by_id.setdefault(parsed, rk)
            if item.get("title") and item.get("year"):
                key = f"{normalize_title(item['title'])}|{item['year']}"
                self.by_title.setdefault(key, rk)

    def __len__(self) -> int:
        return len(self.titles)

    def lookup(self, ident: str) -> str | None:
        """Rating key for an exclusion id: ``plex:<rk>``, ``tt…``, ``tmdb:…`` or ``tvdb:…``."""
        ident = ident.strip()
        if ident.startswith("plex:"):
            return ident[5:] or None
        if ident.startswith("tt"):
            return self.by_id.get(("imdb", ident))
        provider, _, value = ident.partition(":")
        return self.by_id.get((provider, value)) if provider in ("tmdb", "tvdb") else None

    def match(self, ref) -> str | None:
        for provider in ("imdb", "tmdb", "tvdb"):
            value = getattr(ref, provider, None)
            if value:
                rk = self.by_id.get((provider, str(value)))
                if rk:
                    return rk
        if ref.title and ref.year:
            return self.by_title.get(f"{normalize_title(ref.title)}|{ref.year}")
        return None


class Plex:
    def __init__(self, url: str, token: str, verify_ssl: bool = True,
                 client: httpx.Client | None = None, timeout: float = 60):
        if not url or not token:
            raise PlexError("Plex URL and token are required")
        self.url = url.rstrip("/")
        self.http = client or httpx.Client(timeout=timeout, verify=verify_ssl)
        self.headers = {
            "Accept": "application/json",
            "X-Plex-Token": token,
            "X-Plex-Product": config.APP_NAME,
            "X-Plex-Version": config.VERSION,
            "X-Plex-Client-Identifier": "curatarr",
        }
        self._machine_id: str | None = None

    def close(self) -> None:
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _request(self, method: str, path: str, params=None, content: bytes | None = None,
                 headers: dict | None = None) -> dict:
        try:
            resp = self.http.request(
                method, self.url + path, params=params, content=content,
                headers={**self.headers, **(headers or {})},
            )
        except httpx.HTTPError as exc:
            raise PlexError(f"Could not reach Plex at {self.url}: {exc}") from exc
        if resp.status_code == 401:
            raise PlexError("Plex rejected the token (401 Unauthorized)", 401)
        if resp.status_code >= 400:
            raise PlexError(f"Plex {method} {path} failed: HTTP {resp.status_code} {resp.text[:200]}",
                            resp.status_code)
        if not resp.content or "json" not in resp.headers.get("content-type", ""):
            return {}
        return resp.json().get("MediaContainer", {})

    # --- server -------------------------------------------------------------

    def identity(self) -> dict:
        return self._request("GET", "/identity")

    @property
    def machine_id(self) -> str:
        if not self._machine_id:
            self._machine_id = self.identity().get("machineIdentifier")
            if not self._machine_id:
                raise PlexError("Plex did not return a machineIdentifier")
        return self._machine_id

    def server_info(self) -> dict:
        root = self._request("GET", "/")
        return {
            "name": root.get("friendlyName"),
            "version": root.get("version"),
            "platform": root.get("platform"),
            "machine_id": root.get("machineIdentifier"),
        }

    def items_uri(self, rating_keys: list[str]) -> str:
        return (f"server://{self.machine_id}/com.plexapp.plugins.library/library/metadata/"
                + ",".join(rating_keys))

    # --- libraries ----------------------------------------------------------

    def sections(self) -> list[dict]:
        data = self._request("GET", "/library/sections")
        return [
            {"id": str(d["key"]), "title": d.get("title"), "type": d.get("type"),
             "agent": d.get("agent")}
            for d in data.get("Directory", [])
            if d.get("type") in SECTION_TYPES
        ]

    def _paged(self, path: str, params: dict | None = None) -> list[dict]:
        items: list[dict] = []
        seen: set[str] = set()
        start = 0
        for _ in range(MAX_PAGES):
            page = self._request("GET", path, params={
                **(params or {}),
                "X-Plex-Container-Start": start,
                "X-Plex-Container-Size": PAGE_SIZE,
            })
            batch = page.get("Metadata", [])
            # Some endpoints ignore paging and return everything (or the same page)
            # every time; stop as soon as a page brings nothing new.
            new = [m for m in batch if str(m.get("ratingKey")) not in seen]
            seen.update(str(m.get("ratingKey")) for m in new)
            items.extend(new)
            total = int(page.get("totalSize", len(items)))
            start += len(batch)
            if not new or start >= total:
                return items
        log.warning("Stopped paging %s after %d pages", path, MAX_PAGES)
        return items

    def filter_values(self, section_id: str, field: str) -> list[dict]:
        """Values Plex offers for a library filter, e.g. genres: [{id, title}]."""
        data = self._request("GET", f"/library/sections/{section_id}/{field}")
        return [{"id": str(d.get("key")), "title": d.get("title")}
                for d in data.get("Directory", []) if d.get("key") and d.get("title")]

    def section_items(self, section_id: str, section_type: str) -> list[dict]:
        return self._paged(f"/library/sections/{section_id}/all", {
            "type": SECTION_TYPES.get(section_type, TYPE_MOVIE),
            "includeGuids": 1,
        })

    def library_index(self, section_id: str, section_type: str) -> LibraryIndex:
        return LibraryIndex(self.section_items(section_id, section_type))

    # --- collections --------------------------------------------------------

    def collections(self, section_id: str) -> list[dict]:
        data = self._request("GET", f"/library/sections/{section_id}/collections")
        return [
            {"ratingKey": str(m["ratingKey"]), "title": m.get("title"),
             "childCount": int(m.get("childCount", 0)), "thumb": m.get("thumb"),
             "smart": bool(int(m.get("smart", 0) or 0)),
             "labels": [t.get("tag") for t in m.get("Label") or []]}
            for m in data.get("Metadata", [])
        ]

    def image(self, path: str) -> tuple[bytes, str]:
        """Fetch artwork (e.g. a collection thumb) so the browser never needs the token."""
        if not path.startswith(("/library/", "/playlists/")):
            raise PlexError("Only library artwork can be fetched")
        try:
            resp = self.http.get(self.url + path, headers={**self.headers, "Accept": "image/*"})
        except httpx.HTTPError as exc:
            raise PlexError(f"Could not reach Plex at {self.url}: {exc}") from exc
        if resp.status_code >= 400:
            raise PlexError(f"Plex returned HTTP {resp.status_code} for artwork")
        return resp.content, resp.headers.get("content-type", "image/jpeg")

    def find_collection(self, section_id: str, title: str) -> str | None:
        wanted = title.strip().lower()
        for coll in self.collections(section_id):
            if (coll["title"] or "").strip().lower() == wanted and not coll["smart"]:
                return coll["ratingKey"]
        return None

    def collection_section(self, rating_key: str) -> str | None:
        """Library section id of a collection, or None if it no longer exists."""
        try:
            data = self._request("GET", f"/library/metadata/{rating_key}")
        except PlexError:
            return None
        meta = data.get("Metadata") or []
        if not meta or meta[0].get("type") != "collection":
            return None
        return str(meta[0].get("librarySectionID") or data.get("librarySectionID") or "")

    def collection_exists(self, rating_key: str) -> bool:
        return self.collection_section(rating_key) is not None

    def collection_items(self, rating_key: str) -> list[str]:
        items = self._paged(f"/library/collections/{rating_key}/items")
        return [str(m["ratingKey"]) for m in items]

    def collection_contents(self, rating_key: str) -> list[dict]:
        """The titles in a collection, in collection order, for display."""
        result = []
        for m in self._paged(f"/library/collections/{rating_key}/items"):
            episodes = int(m.get("leafCount") or 0)
            # Shows are watched when every episode is; movies when played at least once.
            watched = (int(m.get("viewedLeafCount") or 0) >= episodes) if episodes else bool(m.get("viewCount"))
            result.append({"ratingKey": str(m["ratingKey"]), "title": m.get("title"),
                           "year": m.get("year"), "type": m.get("type"), "thumb": m.get("thumb"),
                           "episodes": episodes or None, "watched": watched})
        return result

    # --- playlists ------------------------------------------------------------
    # A show added to a playlist becomes all of its episodes, so playlist contents
    # are handled as "units": a movie, or a show with its episodes.

    def playlists(self) -> list[dict]:
        data = self._request("GET", "/playlists", params={"playlistType": "video"})
        return [{"ratingKey": str(m["ratingKey"]), "title": m.get("title"),
                 "childCount": int(m.get("leafCount", 0) or 0), "smart": bool(int(m.get("smart", 0) or 0)),
                 "thumb": m.get("composite") or m.get("thumb")}
                for m in data.get("Metadata", [])]

    def find_playlist(self, title: str) -> str | None:
        wanted = title.strip().lower()
        for p in self.playlists():
            if (p["title"] or "").strip().lower() == wanted and not p["smart"]:
                return p["ratingKey"]
        return None

    def playlist_exists(self, rating_key: str) -> bool:
        try:
            return bool(self._request("GET", f"/playlists/{rating_key}").get("Metadata"))
        except PlexError as exc:
            if exc.status == 404:
                return False
            raise

    def _playlist_raw(self, rating_key: str) -> list[dict]:
        return self._paged(f"/playlists/{rating_key}/items")

    @staticmethod
    def _unit_key(m: dict) -> str:
        return str(m.get("grandparentRatingKey") or m["ratingKey"]) if m.get("type") == "episode" \
            else str(m["ratingKey"])

    def playlist_units(self, rating_key: str) -> list[tuple[str, list[str]]]:
        """[(movie or show ratingKey, [playlistItemIDs])] in playlist order."""
        units: dict[str, list[str]] = {}
        for m in self._playlist_raw(rating_key):
            units.setdefault(self._unit_key(m), []).append(str(m.get("playlistItemID")))
        return list(units.items())

    def playlist_contents(self, rating_key: str) -> list[dict]:
        """Playlist titles for display, with a show's episodes grouped under the show."""
        units: dict[str, dict] = {}
        for m in self._playlist_raw(rating_key):
            key = self._unit_key(m)
            if m.get("type") == "episode":
                unit = units.setdefault(key, {
                    "ratingKey": key, "title": m.get("grandparentTitle"), "year": None, "type": "show",
                    "thumb": m.get("grandparentThumb"), "episodes": 0, "watched": True})
                unit["episodes"] += 1
                unit["watched"] = unit["watched"] and bool(m.get("viewCount"))
            else:
                units[key] = {"ratingKey": key, "title": m.get("title"), "year": m.get("year"),
                              "type": m.get("type"), "thumb": m.get("thumb"), "episodes": None,
                              "watched": bool(m.get("viewCount"))}
        return list(units.values())

    def create_playlist(self, title: str, rating_keys: list[str]) -> str:
        first, rest = rating_keys[:BATCH_SIZE], rating_keys[BATCH_SIZE:]
        data = self._request("POST", "/playlists", params={
            "type": "video", "title": title, "smart": 0, "uri": self.items_uri(first)})
        meta = data.get("Metadata") or []
        if not meta:
            raise PlexError(f"Plex did not return the new playlist '{title}'")
        rk = str(meta[0]["ratingKey"])
        if rest:
            self.add_playlist_items(rk, rest)
        return rk

    def add_playlist_items(self, rating_key: str, rating_keys: list[str]) -> None:
        for i in range(0, len(rating_keys), BATCH_SIZE):
            self._request("PUT", f"/playlists/{rating_key}/items",
                          params={"uri": self.items_uri(rating_keys[i:i + BATCH_SIZE])})

    def remove_playlist_items(self, rating_key: str, playlist_item_ids: list[str]) -> None:
        for item_id in playlist_item_ids:
            self._request("DELETE", f"/playlists/{rating_key}/items/{item_id}")

    def clear_playlist(self, rating_key: str) -> None:
        self._request("DELETE", f"/playlists/{rating_key}/items")

    def edit_playlist(self, rating_key: str, title: str | None = None, summary: str | None = None) -> None:
        params = {k: v for k, v in (("title", title), ("summary", summary)) if v is not None}
        if params:
            self._request("PUT", f"/playlists/{rating_key}", params=params)

    def delete_playlist(self, rating_key: str) -> None:
        self._request("DELETE", f"/playlists/{rating_key}")

    def create_collection(self, section_id: str, section_type: str, title: str,
                          rating_keys: list[str]) -> str:
        first, rest = rating_keys[:BATCH_SIZE], rating_keys[BATCH_SIZE:]
        data = self._request("POST", "/library/collections", params={
            "type": SECTION_TYPES.get(section_type, TYPE_MOVIE),
            "title": title,
            "smart": 0,
            "sectionId": section_id,
            "uri": self.items_uri(first),
        })
        meta = data.get("Metadata") or []
        if not meta:
            raise PlexError(f"Plex did not return the new collection '{title}'")
        rk = str(meta[0]["ratingKey"])
        if rest:
            self.add_items(rk, rest)
        return rk

    def add_items(self, collection_key: str, rating_keys: list[str]) -> None:
        for i in range(0, len(rating_keys), BATCH_SIZE):
            self._request("PUT", f"/library/collections/{collection_key}/items",
                          params={"uri": self.items_uri(rating_keys[i:i + BATCH_SIZE])})

    def remove_item(self, collection_key: str, rating_key: str) -> None:
        # Plex servers remove with DELETE (the published reference says PUT, which
        # real servers answer with 404), so PUT is only a fallback.
        path = f"/library/collections/{collection_key}/items/{rating_key}"
        try:
            self._request("DELETE", path)
        except PlexError as exc:
            if exc.status not in (404, 405):
                raise
            self._request("PUT", path)

    def move_item(self, collection_key: str, rating_key: str, after: str | None) -> None:
        params = {"after": after} if after else None
        self._request("PUT", f"/library/collections/{collection_key}/items/{rating_key}/move",
                      params=params)

    def delete_collection(self, section_id: str, collection_key: str) -> None:
        # Real servers delete a collection via its metadata item; the section path from
        # the published API reference returns 404, so it is only a fallback.
        try:
            self._request("DELETE", f"/library/metadata/{collection_key}")
        except PlexError as exc:
            if exc.status not in (404, 405):
                raise
            self._request("DELETE", f"/library/sections/{section_id}/collection/{collection_key}")

    def set_prefs(self, rating_key: str, **prefs) -> None:
        self._request("PUT", f"/library/metadata/{rating_key}/prefs", params=prefs)

    def edit_collection(self, section_id: str, collection_key: str, title: str | None = None,
                        summary: str | None = None, sort_title: str | None = None,
                        labels: list[str] | None = None) -> None:
        params: dict = {"type": TYPE_COLLECTION, "id": collection_key}
        if title is not None:
            params.update({"title.value": title, "title.locked": 1})
        if summary is not None:
            params.update({"summary.value": summary, "summary.locked": 1})
        if sort_title:
            params.update({"titleSort.value": sort_title, "titleSort.locked": 1})
        for i, label in enumerate(labels or []):
            params[f"label[{i}].tag.tag"] = label
        if labels:
            params["label.locked"] = 1
        self._request("PUT", f"/library/sections/{section_id}/all", params=params)

    def upload_image(self, rating_key: str, kind: str, data: bytes | None = None,
                     url: str | None = None) -> None:
        """Upload a poster (kind='poster') or background (kind='art')."""
        element = "posters" if kind == "poster" else "arts"
        path = f"/library/metadata/{rating_key}/{element}"
        if url:
            self._request("POST", path, params={"url": url})
        elif data:
            self._request("POST", path, content=data,
                          headers={"Content-Type": "application/octet-stream"})

    # --- home screen hubs ---------------------------------------------------

    def hubs(self, section_id: str) -> list[dict]:
        data = self._request("GET", f"/hubs/sections/{section_id}/manage")
        return data.get("Hub", [])

    @staticmethod
    def _hub_for(hubs: list[dict], collection_key: str) -> str | None:
        for hub in hubs:
            ident = hub.get("identifier", "")
            if str(hub.get("ratingKey", "")) == collection_key or ident.endswith(f".{collection_key}"):
                return ident
        return None

    def pin_hub(self, section_id: str, collection_key: str) -> str | None:
        """Move a collection's hub to the top of the library's hubs.

        Returns the identifier of the hub that was first before (so it can be put
        back), "" when the collection was already first, or None without a hub.
        """
        hubs = self.hubs(section_id)
        ident = self._hub_for(hubs, collection_key)
        if not ident:
            return None
        first = hubs[0].get("identifier", "") if hubs else ""
        if first == ident:
            return ""
        self._request("PUT", f"/hubs/sections/{section_id}/manage/move", params={"identifier": ident})
        return first

    def unpin_hub(self, section_id: str, collection_key: str, after: str) -> None:
        """Put a pinned hub back behind ``after`` (the hub that was first before)."""
        ident = self._hub_for(self.hubs(section_id), collection_key)
        if ident and after:
            self._request("PUT", f"/hubs/sections/{section_id}/manage/move",
                          params={"identifier": ident, "after": after})

    def set_hub_visibility(self, section_id: str, collection_key: str, recommended: bool,
                           home: bool, shared: bool) -> None:
        flags = {
            "promotedToRecommended": int(recommended),
            "promotedToOwnHome": int(home),
            "promotedToSharedHome": int(shared),
        }
        existing = self._hub_for(self.hubs(section_id), collection_key)
        if existing:
            self._request("PUT", f"/hubs/sections/{section_id}/manage/{quote(existing, safe='')}",
                          params=flags)
        elif any(flags.values()):
            self._request("POST", f"/hubs/sections/{section_id}/manage",
                          params={"metadataItemId": collection_key, **flags})


def from_settings(settings: dict, timeout: float = 60) -> Plex:
    return Plex(
        settings.get("plex_url", ""),
        settings.get("plex_token", ""),
        verify_ssl=settings.get("plex_verify_ssl", "true") != "false",
        timeout=timeout,
    )
