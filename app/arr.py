"""Send titles missing from Plex to Radarr (movies) or Sonarr (shows)."""
import json
import logging

import httpx

from .sources.base import MediaRef, SourceError
from .sources.tmdb import TMDB

log = logging.getLogger(__name__)


class ArrError(Exception):
    pass


class Arr:
    def __init__(self, kind: str, settings: dict, http: httpx.Client, root_folder: str | None = None):
        self.kind = kind   # "radarr" or "sonarr"
        self.url = settings.get(f"{kind}_url", "").rstrip("/")
        self.api_key = settings.get(f"{kind}_api_key", "")
        # A Plex library's own root folder (see sync.arr_root_folder), else the default one.
        self.root_folder = root_folder or settings.get(f"{kind}_root_folder", "")
        self.quality_profile = settings.get(f"{kind}_quality_profile", "")
        self.search = settings.get(f"{kind}_search", "true") != "false"
        self.http = http
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.url and self.api_key and self.root_folder and self.quality_profile)

    def _request(self, method: str, path: str, **kwargs):
        if not (self.url and self.api_key):
            raise ArrError(f"{self.kind.title()} URL and API key are not configured")
        try:
            resp = self.http.request(method, f"{self.url}/api/v3{path}",
                                     headers={"X-Api-Key": self.api_key}, **kwargs)
        except httpx.HTTPError as exc:
            raise ArrError(f"Could not reach {self.kind.title()}: {exc}") from exc
        if resp.status_code == 401:
            raise ArrError(f"{self.kind.title()} rejected the API key")
        return resp

    def status(self) -> dict:
        resp = self._request("GET", "/system/status")
        if resp.status_code >= 400:
            raise ArrError(f"{self.kind.title()} returned HTTP {resp.status_code}")
        return resp.json()

    def options(self) -> dict:
        profiles = self._request("GET", "/qualityprofile").json()
        folders = self._request("GET", "/rootfolder").json()
        return {
            "quality_profiles": [{"id": p["id"], "name": p["name"]} for p in profiles],
            "root_folders": [f["path"] for f in folders],
        }

    def library_ids(self) -> dict[str, set]:
        """External ids of everything already in Radarr/Sonarr, fetched in one call."""
        resp = self._request("GET", "/series" if self.kind == "sonarr" else "/movie")
        if resp.status_code >= 400:
            raise ArrError(f"{self.kind.title()} returned HTTP {resp.status_code}")
        have: dict[str, set] = {"tmdb": set(), "tvdb": set(), "imdb": set()}
        for item in resp.json():
            for key, field in (("tmdb", "tmdbId"), ("tvdb", "tvdbId"), ("imdb", "imdbId")):
                if item.get(field):
                    have[key].add(str(item[field]))
        return have

    def item_folders(self) -> list[tuple[set, str]]:
        """Every movie/show in Radarr/Sonarr as ({(provider, id)}, root folder it's in)."""
        roots = [f["path"] for f in self._request("GET", "/rootfolder").json()]
        resp = self._request("GET", "/series" if self.kind == "sonarr" else "/movie")
        if resp.status_code >= 400:
            raise ArrError(f"{self.kind.title()} returned HTTP {resp.status_code}")
        trim = lambda p: (p or "").replace("\\", "/").rstrip("/")  # noqa: E731
        out = []
        for item in resp.json():
            where = trim(item.get("rootFolderPath")) or trim(item.get("path"))
            # Report it as one of Radarr/Sonarr's root folders (the longest one the path is under).
            root = max((r for r in roots if where == trim(r) or where.startswith(trim(r) + "/")),
                       key=len, default=None)
            if not root:
                continue
            ids = {(key, str(item[field])) for key, field in (("tmdb", "tmdbId"), ("tvdb", "tvdbId"),
                                                             ("imdb", "imdbId")) if item.get(field)}
            out.append((ids, root))
        return out

    def _json(self, path: str, **params):
        resp = self._request("GET", path, params=params or None)
        if resp.status_code >= 400:
            raise ArrError(f"{self.kind.title()} returned HTTP {resp.status_code} for {path}")
        return resp.json()

    def naming(self) -> dict:
        """The naming settings (Settings → Media Management): whether renaming is on, and the formats."""
        cfg = self._json("/config/naming")
        keys = (("renameMovies", "standardMovieFormat", "movieFolderFormat") if self.kind == "radarr" else
                ("renameEpisodes", "standardEpisodeFormat", "dailyEpisodeFormat", "animeEpisodeFormat",
                 "seriesFolderFormat", "seasonFolderFormat"))
        return {k: cfg.get(k) for k in keys if k in cfg}

    def titles_with_files(self) -> list[dict]:
        """Movies (Radarr) or series (Sonarr) that have files: [{id, title, year, path}]."""
        if self.kind == "radarr":
            items = [m for m in self._json("/movie") if m.get("hasFile")]
        else:
            items = [s for s in self._json("/series") if (s.get("statistics") or {}).get("episodeFileCount")]
        return sorted(({"id": i["id"], "title": i.get("title") or "", "year": i.get("year"), "path": i.get("path") or ""}
                       for i in items), key=lambda t: t["title"].lower())

    def rename_preview(self, item_id: int) -> list[dict]:
        """Files Radarr/Sonarr would rename to follow its naming format: [{existing, new, season, episodes}]."""
        key = "movieId" if self.kind == "radarr" else "seriesId"
        return [{"existing": f.get("existingPath") or "", "new": f.get("newPath") or "",
                 "season": f.get("seasonNumber"), "episodes": f.get("episodeNumbers") or []}
                for f in self._json("/rename", **{key: item_id})]

    @staticmethod
    def already_has(ref: MediaRef, have: dict[str, set]) -> bool:
        return any(getattr(ref, key) and str(getattr(ref, key)) in have[key]
                   for key in ("tmdb", "tvdb", "imdb"))

    def _tmdb(self) -> TMDB | None:
        try:
            return TMDB(self.settings.get("tmdb_api_key", ""), self.http)
        except SourceError:
            return None

    def _lookup_movie(self, ref: MediaRef) -> dict | None:
        if ref.tmdb:
            resp = self._request("GET", "/movie/lookup/tmdb", params={"tmdbId": ref.tmdb})
        elif ref.imdb:
            resp = self._request("GET", "/movie/lookup/imdb", params={"imdbId": ref.imdb})
        else:
            return None
        if resp.status_code >= 400:
            return None
        data = resp.json()
        return data[0] if isinstance(data, list) and data else (data or None)

    def _tvdb_id(self, ref: MediaRef) -> int | None:
        if ref.tvdb:
            return ref.tvdb
        tmdb = self._tmdb()
        if not tmdb:
            return None
        try:
            if ref.tmdb:
                return tmdb.external_ids("show", ref.tmdb).get("tvdb_id")
            if ref.imdb:
                results = tmdb.find(ref.imdb, "imdb_id").get("tv_results") or []
                if results:
                    return tmdb.external_ids("show", results[0]["id"]).get("tvdb_id")
        except SourceError:
            return None
        return None

    def _series_search(self, term: str) -> list[dict]:
        resp = self._request("GET", "/series/lookup", params={"term": term})
        data = resp.json() if resp.status_code < 400 else []
        return data if isinstance(data, list) else []

    def _lookup_series(self, ref: MediaRef) -> dict | None:
        """Sonarr's entry for a show. Sonarr keys shows on TVDB ids, but TMDB often has no TVDB
        link yet for new shows, so Sonarr is also asked by TMDB/IMDb id and by title; those
        results only count when their TMDB or IMDb id is the show's own."""
        tvdb = self._tvdb_id(ref)
        if tvdb:
            data = self._series_search(f"tvdb:{tvdb}")
            if data:
                return data[0]

        def same(s: dict) -> bool:
            return bool((ref.tmdb and str(s.get("tmdbId") or "") == str(ref.tmdb))
                        or (ref.imdb and s.get("imdbId") == ref.imdb))

        terms = [f"tmdb:{ref.tmdb}" if ref.tmdb else "", f"imdb:{ref.imdb}" if ref.imdb else "", ref.title or ""]
        for term in filter(None, terms):
            found = next((s for s in self._series_search(term) if same(s)), None)
            if found:
                return found
        log.info("Sonarr: no show with %s found (TVDB id %s)", ", ".join(
            f"{k} {getattr(ref, k)}" for k in ("tmdb", "imdb") if getattr(ref, k)) or ref.title, tvdb or "unknown")
        return None

    def add(self, ref: MediaRef, tags: list[int] | None = None) -> str:
        """Returns 'added', 'exists' or 'not_found'."""
        if self.kind == "radarr":
            found = self._lookup_movie(ref)
            if not found:
                return "not_found"
            if found.get("id"):
                return "exists"
            body = {**found, "qualityProfileId": int(self.quality_profile),
                    "rootFolderPath": self.root_folder, "monitored": True,
                    "minimumAvailability": "released",
                    "addOptions": {"searchForMovie": self.search}}
            resp = self._request("POST", "/movie", json=body)
        else:
            found = self._lookup_series(ref)
            if not found:
                return "not_found"
            if found.get("id"):
                return "exists"
            body = {**found, "qualityProfileId": int(self.quality_profile),
                    "rootFolderPath": self.root_folder, "monitored": True,
                    "seasonFolder": True,
                    "addOptions": {"monitor": "all",
                                   "searchForMissingEpisodes": self.search}}
            resp = self._request("POST", "/series", json=body)
        if resp.status_code < 300:
            return "added"
        if resp.status_code == 400 and "already" in resp.text.lower():
            return "exists"
        raise ArrError(f"{self.kind.title()} add failed: HTTP {resp.status_code} {resp.text[:200]}")


def detect_folder(items: list[tuple[set, str]], library_ids: set) -> dict:
    """Which root folder a Plex library's titles are in: {folder, matched, total}.

    ``library_ids`` are the (provider, id) pairs of the library's titles. Each Radarr/Sonarr
    title that is also in the library counts for the folder it's in; the most common wins.
    """
    votes: dict[str, int] = {}
    for ids, root in items:
        if ids & library_ids:
            votes[root] = votes.get(root, 0) + 1
    if not votes:
        return {"folder": "", "matched": 0, "total": 0}
    folder = max(votes, key=votes.get)
    return {"folder": folder, "matched": votes[folder], "total": sum(votes.values())}


def library_folder(kind: str, settings: dict, section_id: str | None) -> str:
    """The root folder set for one Plex library ("" when none is set)."""
    try:
        folders = json.loads(settings.get(f"{kind}_library_folders") or "{}")
    except ValueError:
        return ""
    return str(folders.get(str(section_id)) or "") if section_id and isinstance(folders, dict) else ""


def request_missing(media_type: str, refs: list[MediaRef], settings: dict,
                    http: httpx.Client, root_folder: str | None = None) -> tuple[int, list[str], bool]:
    """Add missing refs to Radarr/Sonarr.

    At most ``arr_max_requests`` titles are added per call (0 = no limit), and
    titles Radarr/Sonarr already has are skipped without a lookup each.
    Returns (added count, error messages, whether the limit was reached).
    """
    arr = Arr("sonarr" if media_type == "show" else "radarr", settings, http, root_folder)
    if not arr.configured:
        return 0, [f"{arr.kind.title()} is not fully configured; missing titles were not requested"], False
    try:
        limit = max(int(settings.get("arr_max_requests") or 0), 0)
    except ValueError:
        limit = 25
    try:
        have = arr.library_ids()
    except (ArrError, httpx.HTTPError, ValueError) as exc:
        return 0, [f"Could not read the {arr.kind.title()} library: {exc}"], False
    added, errors = 0, []
    for ref in refs:
        if limit and added >= limit:
            log.info("%s: request limit of %d reached; the rest wait for the next sync",
                     arr.kind.title(), limit)
            return added, errors, True
        if arr.already_has(ref, have):
            continue
        try:
            if arr.add(ref) == "added":
                added += 1
                log.info("%s: added %s", arr.kind.title(), ref.title or ref.imdb or ref.tmdb or ref.tvdb)
        except ArrError as exc:
            errors.append(str(exc))
            if len(errors) >= 5:
                break
    return added, errors, False
