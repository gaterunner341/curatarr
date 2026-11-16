"""Original-language filter: keep only list titles made in the user's language (Settings > General).

A title's language is TMDB's ``original_language``. Lists from TMDB carry it already; others are
looked up once by TMDB, IMDb or TVDB id and remembered (setting ``language_cache``). A title
whose language can't be found (no TMDB key, not on TMDB) is kept.
"""
import json
import logging

import httpx

from . import db
from .sources.base import MediaRef, SourceError
from .sources.tmdb import TMDB

log = logging.getLogger(__name__)

LANGUAGES = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian",
    "pt": "Portuguese", "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "hi": "Hindi",
}


def name(code: str) -> str:
    return LANGUAGES.get(code, code)


def _lookup(tmdb: TMDB, ref: MediaRef) -> str | None:
    if ref.tmdb:
        kind = "tv" if ref.media_type == "show" else "movie"
        return tmdb.get(f"{kind}/{ref.tmdb}").get("original_language")
    for value, source in ((ref.imdb, "imdb_id"), (ref.tvdb, "tvdb_id")):
        if value:
            found = tmdb.find(str(value), source)
            hits = found.get("tv_results" if ref.media_type == "show" else "movie_results") \
                or found.get("movie_results") or found.get("tv_results") or []
            if hits:
                return hits[0].get("original_language")
    return None


def filter_refs(refs: list[MediaRef], settings: dict, http: httpx.Client) -> tuple[list[MediaRef], int]:
    """(the refs in ``settings["language"]`` or of unknown language, how many were left out)."""
    want = settings.get("language") or "en"
    try:
        cache: dict[str, str] = json.loads(settings.get("language_cache") or "{}")
    except ValueError:
        cache = {}
    try:
        tmdb = TMDB(settings.get("tmdb_api_key", ""), http)
    except SourceError:
        tmdb = None
    learned = False
    kept: list[MediaRef] = []
    for ref in refs:
        lang = ref.language or cache.get(ref.key())
        if lang is None and tmdb:
            try:
                lang = _lookup(tmdb, ref)
            except SourceError as exc:
                log.debug("No language for %s: %s", ref.key(), exc)
            if lang:
                cache[ref.key()] = lang
                learned = True
        if not lang or lang == want:
            kept.append(ref)
    if learned:
        db.save_settings({"language_cache": json.dumps(cache)})
    return kept, len(refs) - len(kept)
