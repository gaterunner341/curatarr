"""IMDb lists and charts.

IMDb has no public API. Pages are requested with an honest user agent and
parsed from their structured data (JSON-LD), falling back to a scan for title
ids. IMDb may answer automated requests with a bot-protection challenge; in
that case the source fails with instructions for the supported alternatives
rather than trying to get around the check.
"""
import json
import re

import httpx

from .base import USER_AGENT, MediaRef, SourceContext, SourceError

BASE = "https://www.imdb.com"
MAX_PAGES = 40

CHARTS = {
    "top": "Top 250 movies",
    "moviemeter": "Most popular movies",
    "toptv": "Top 250 TV shows",
    "tvmeter": "Most popular TV shows",
    "boxoffice": "Box office (this weekend)",
    "bottom": "Lowest rated movies",
}

BLOCKED_HELP = (
    "IMDb refused the automated request (bot protection). Alternatives: add the IMDb list "
    "URL to an MDBList list and use an 'MDBList list' source, or use the Export button on "
    "the IMDb list page and paste the CSV into a 'Static ids' source."
)

_LD_JSON =re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_TITLE_ID = re.compile(r"/title/(tt\d{7,})")
_SHOW_TYPES = {"TVSeries", "TVMiniSeries", "TVSeason", "TVEpisode"}


def _get(http: httpx.Client, url: str, params: dict | None = None) -> str:
    try:
        resp = http.get(url, params=params, follow_redirects=True, headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        })
    except httpx.HTTPError as exc:
        raise SourceError(f"IMDb request failed: {exc}") from exc
    if resp.status_code == 202 or "awsWafCookie" in resp.text[:4000]:
        raise SourceError(BLOCKED_HELP)
    if resp.status_code == 404:
        raise SourceError(f"IMDb page not found: {url}")
    if resp.status_code >= 400:
        raise SourceError(f"IMDb returned HTTP {resp.status_code} for {url}")
    return resp.text


def parse_page(html: str) -> list[MediaRef]:
    """Extract titles in page order from an IMDb list/chart page."""
    refs: list[MediaRef] = []
    for block in _LD_JSON.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for element in data.get("itemListElement") or []:
            item = element.get("item", element) if isinstance(element, dict) else {}
            match = _TITLE_ID.search(item.get("url", "") or "")
            if not match:
                continue
            kind = item.get("@type")
            media_type = "show" if kind in _SHOW_TYPES else ("movie" if kind == "Movie" else None)
            refs.append(MediaRef(media_type, item.get("name") or "", imdb=match.group(1)))
    if refs:
        return refs
    seen: set[str] = set()
    for tt in _TITLE_ID.findall(html):
        if tt not in seen:
            seen.add(tt)
            refs.append(MediaRef(None, imdb=tt))
    return refs


def list_url(value: str) -> str:
    value = value.strip()
    if value.startswith("http"):
        return value.split("#")[0]
    if re.fullmatch(r"ls\d+", value):
        return f"{BASE}/list/{value}/"
    if re.fullmatch(r"ur\d+", value):
        return f"{BASE}/user/{value}/watchlist/"
    raise SourceError("IMDb list must be a list id (ls...), user id (ur...) or an imdb.com URL")


def fetch_list(value: str, ctx: SourceContext, limit: int | None) -> list[MediaRef]:
    url = list_url(value)
    refs: list[MediaRef] = []
    seen: set[str] = set()
    paginate = "/list/" in url and "page=" not in url
    for page in range(1, MAX_PAGES + 1):
        html = _get(ctx.http, url, params={"page": page} if paginate and page > 1 else None)
        new = [r for r in parse_page(html) if r.imdb not in seen]
        for ref in new:
            seen.add(ref.imdb)
            refs.append(ref)
        if not new or not paginate or (limit and len(refs) >= limit):
            break
    if not refs:
        raise SourceError(f"No titles found at {url} (is the list public?)")
    return refs[:limit] if limit else refs


def fetch_chart(value: str, ctx: SourceContext, limit: int | None) -> list[MediaRef]:
    chart = value.strip("/ ").lower()
    if chart not in CHARTS:
        raise SourceError(f"Unknown IMDb chart '{value}'. Use one of: {', '.join(CHARTS)}")
    refs = parse_page(_get(ctx.http, f"{BASE}/chart/{chart}/"))
    if chart in ("toptv", "tvmeter"):
        for ref in refs:
            ref.media_type = ref.media_type or "show"
    else:
        for ref in refs:
            ref.media_type = ref.media_type or "movie"
    return refs[:limit] if limit else refs
