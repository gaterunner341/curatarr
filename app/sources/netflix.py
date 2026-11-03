"""Netflix Top 10 (netflix.com/tudum/top10): the latest week's global lists.

Netflix publishes the lists as a TSV with titles and ranks but no ids, so each title is
looked up on TMDB (a TMDB API key is needed). A title counts only when TMDB has one with
the same name; otherwise it's left out rather than guessed.
"""
import csv
import io

import httpx

from ..plex import normalize_title
from .base import MediaRef, SourceContext, SourceError
from .tmdb import TMDB, _ref

DATA_URL = "https://www.netflix.com/tudum/top10/data/all-weeks-global.tsv"

CHARTS = {
    "films": "Top 10 films (English)",
    "films-non-english": "Top 10 films (non-English)",
    "tv": "Top 10 TV (English)",
    "tv-non-english": "Top 10 TV (non-English)",
}
CATEGORIES = {"films": "Films (English)", "films-non-english": "Films (Non-English)",
              "tv": "TV (English)", "tv-non-english": "TV (Non-English)"}


def chart_for_link(url: str) -> str | None:
    """The chart a netflix.com/tudum/top10 link shows (its default page is English films)."""
    if "netflix.com" not in url or "/top10" not in url:
        return None
    tv, non_english = "/tv" in url, "non-english" in url
    return ("tv" if tv else "films") + ("-non-english" if non_english else "")


def latest_week(rows: list[dict], category: str) -> list[str]:
    """The newest week's titles in ``category``, in rank order."""
    rows = [r for r in rows if r.get("category") == category]
    if not rows:
        return []
    week = max(r["week"] for r in rows)
    ranked = sorted((r for r in rows if r["week"] == week), key=lambda r: int(r.get("weekly_rank") or 99))
    titles: list[str] = []
    for r in ranked:
        if r["show_title"] not in titles:      # a show can appear with two seasons
            titles.append(r["show_title"])
    return titles


def fetch_chart(value: str, ctx: SourceContext, limit: int | None) -> list[MediaRef]:
    if value not in CATEGORIES:
        raise SourceError(f"Unknown Netflix chart '{value}'. Use one of: {', '.join(CHARTS)}")
    try:
        resp = ctx.http.get(DATA_URL, timeout=60, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise SourceError(f"Netflix Top 10 request failed: {exc}") from exc
    if resp.status_code >= 400:
        raise SourceError(f"Netflix Top 10 returned HTTP {resp.status_code}")
    rows = list(csv.DictReader(io.StringIO(resp.text), delimiter="\t"))
    titles = latest_week(rows, CATEGORIES[value])
    if not titles:
        raise SourceError("Netflix's Top 10 data had no titles for that list")
    tmdb = TMDB(ctx.settings.get("tmdb_api_key", ""), ctx.http)    # raises when there's no key
    kind = "tv" if value.startswith("tv") else "movie"
    refs = []
    for title in titles[:limit or 10]:
        results = tmdb.get(f"search/{kind}", query=title).get("results") or []
        wanted = normalize_title(title)
        match = next((r for r in results
                      if normalize_title(r.get("title") or r.get("name") or "") == wanted), None)
        ref = _ref(match, kind) if match else None
        if ref:
            refs.append(ref)
    return refs
