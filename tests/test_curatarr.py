import json
import os
import tempfile

os.environ["CURATARR_CONFIG_DIR"] = tempfile.mkdtemp(prefix="curatarr-test-")

import httpx  # noqa: E402
import pytest  # noqa: E402

from app import api, db  # noqa: E402
from app.models import CollectionConfig, Source  # noqa: E402
from app.plex import LibraryIndex, Plex, parse_guid  # noqa: E402
from app.sources import SourceContext, SourceError, fetch_static, imdb, resolve, trakt  # noqa: E402
from app.sources.base import MediaRef  # noqa: E402
from app.sync import reorder_moves, sync_collection  # noqa: E402


# --- guid parsing & matching ---------------------------------------------------

@pytest.mark.parametrize("guid,expected", [
    ("imdb://tt0111161", ("imdb", "tt0111161")),
    ("tmdb://278", ("tmdb", "278")),
    ("tvdb://81189", ("tvdb", "81189")),
    ("com.plexapp.agents.imdb://tt0111161?lang=en", ("imdb", "tt0111161")),
    ("com.plexapp.agents.themoviedb://278?lang=en", ("tmdb", "278")),
    ("com.plexapp.agents.thetvdb://81189/1/1?lang=en", ("tvdb", "81189")),
    ("plex://movie/5d776825880197001ec967c8", None),
    ("local://123", None),
])
def test_parse_guid(guid, expected):
    assert parse_guid(guid) == expected


def test_library_index_matches_ids_then_title():
    index = LibraryIndex([
        {"ratingKey": 1, "title": "The Matrix", "year": 1999,
         "Guid": [{"id": "imdb://tt0133093"}, {"id": "tmdb://603"}]},
        {"ratingKey": 2, "title": "Heat", "year": 1995, "guid": "com.plexapp.agents.imdb://tt0113277"},
        {"ratingKey": 3, "title": "Amélie!", "year": 2001},
    ])
    assert index.match(MediaRef("movie", tmdb=603)) == "1"
    assert index.match(MediaRef("movie", imdb="tt0113277")) == "2"
    assert index.match(MediaRef("movie", title="amelie", year=2001)) is None  # accents differ
    assert index.match(MediaRef("movie", title="Amélie", year=2001)) == "3"
    assert index.match(MediaRef("movie", imdb="tt9999999")) is None


# --- sources ---------------------------------------------------------------------

def ctx(handler=None, media_type="movie", **settings):
    transport = httpx.MockTransport(handler or (lambda r: httpx.Response(404)))
    return SourceContext(settings, httpx.Client(transport=transport), media_type)


def test_static_source():
    refs = fetch_static("tt0133093, tmdb:604\nimdb:tt0234215 tvdb:81189", ctx(), None)
    assert [r.key() for r in refs] == ["imdb:tt0133093", "tmdb::604", "imdb:tt0234215", "tvdb:81189"]
    with pytest.raises(SourceError):
        fetch_static("nonsense", ctx(), None)


def test_static_source_accepts_imdb_csv_export():
    csv = ("Position,Const,Created,Modified,Description,Title,URL\n"
           "1,tt0111161,2024-01-01,,,The Shawshank Redemption,https://www.imdb.com/title/tt0111161/\n"
           "2,tt0068646,2024-01-01,,,The Godfather,https://www.imdb.com/title/tt0068646/\n")
    assert [r.imdb for r in fetch_static(csv, ctx(), None)] == ["tt0111161", "tt0068646"]


def test_imdb_bot_challenge_gives_guidance():
    challenge = lambda r: httpx.Response(202, text="<script>window.awsWafCookieDomainList=[]</script>")  # noqa: E731
    with pytest.raises(SourceError, match="MDBList"):
        imdb.fetch_chart("top", ctx(challenge), None)


def test_imdb_parse_jsonld_and_fallback():
    ld = {"@type": "ItemList", "itemListElement": [
        {"@type": "ListItem", "item": {"@type": "Movie", "url": "https://www.imdb.com/title/tt0111161/", "name": "The Shawshank Redemption"}},
        {"@type": "ListItem", "item": {"@type": "TVSeries", "url": "https://www.imdb.com/title/tt0903747/", "name": "Breaking Bad"}},
    ]}
    html = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    refs = imdb.parse_page(html)
    assert [(r.imdb, r.media_type) for r in refs] == [("tt0111161", "movie"), ("tt0903747", "show")]
    fallback = imdb.parse_page('<a href="/title/tt0068646/">x</a><a href="/title/tt0068646/?ref">y</a><a href="/title/tt0071562/">')
    assert [r.imdb for r in fallback] == ["tt0068646", "tt0071562"]


def test_imdb_list_url():
    assert imdb.list_url("ls055592025") == "https://www.imdb.com/list/ls055592025/"
    assert imdb.list_url("ur1234567") == "https://www.imdb.com/user/ur1234567/watchlist/"
    with pytest.raises(SourceError):
        imdb.list_url("bogus")


def test_trakt_parse_list():
    assert trakt.parse_list("https://trakt.tv/users/alice/lists/best-of") == ("alice", "best-of")
    assert trakt.parse_list("alice/watchlist") == ("alice", "watchlist")


def test_resolve_merges_filters_and_reports_errors():
    def handler(request):
        if request.url.path == "/3/collection/10":
            return httpx.Response(200, json={"parts": [
                {"id": 11, "title": "Star Wars", "release_date": "1977-05-25"},
                {"id": 1891, "title": "Empire", "release_date": "1980-05-20"},
            ]})
        return httpx.Response(404)

    sources = [
        Source(type="tmdb_collection", value="https://www.themoviedb.org/collection/10-star-wars"),
        Source(type="static", value="tmdb:11, tt0076759"),
        Source(type="tmdb_list", value="999"),
    ]
    refs, errors = resolve(sources, ctx(handler, tmdb_api_key="k"), item_limit=0)
    assert [r.key() for r in refs] == ["tmdb:movie:11", "tmdb:movie:1891", "imdb:tt0076759"]
    assert len(errors) == 1 and "tmdb_list" in errors[0]

    tv_refs, _ = resolve(sources[:1], ctx(handler, media_type="show", tmdb_api_key="k"))
    assert tv_refs == []   # movies are dropped for a TV library


# --- sync engine ------------------------------------------------------------------

class FakePlex(httpx.BaseTransport):
    """Enough of PMS to exercise collection create/add/remove/reorder."""

    def __init__(self):
        self.library = {str(i): f"imdb://tt000000{i}" for i in range(1, 7)}
        self.collections: dict[str, list[str]] = {}
        self.calls: list[str] = []

    def handle_request(self, request):
        path, method, q = request.url.path, request.method, request.url.params
        self.calls.append(f"{method} {path}")
        mc = lambda body: httpx.Response(200, json={"MediaContainer": body})  # noqa: E731
        if path == "/identity":
            return mc({"machineIdentifier": "abc"})
        if path == "/library/sections/1/all" and method == "GET":
            items = [{"ratingKey": rk, "title": f"T{rk}", "Guid": [{"id": g}]} for rk, g in self.library.items()]
            return mc({"Metadata": items, "totalSize": len(items)})
        if path == "/library/sections/1/collections":
            return mc({"Metadata": [{"ratingKey": k, "title": "Best", "smart": 0} for k in self.collections]})
        if path == "/library/collections" and method == "POST":
            rks = q["uri"].rsplit("/", 1)[1].split(",")
            self.collections["100"] = rks
            return mc({"Metadata": [{"ratingKey": "100"}]})
        if path.startswith("/library/metadata/100") and method == "GET":
            return mc({"Metadata": [{"type": "collection"}]} if "100" in self.collections else {})
        parts = path.split("/")
        if path.startswith("/library/collections/100/items"):
            items = self.collections["100"]
            if method == "GET":
                return mc({"Metadata": [{"ratingKey": rk} for rk in items], "totalSize": len(items)})
            if len(parts) == 5:   # add
                items.extend(q["uri"].rsplit("/", 1)[1].split(","))
            elif len(parts) == 6:   # remove
                items.remove(parts[5])
            elif parts[-1] == "move":
                rk = parts[5]
                items.remove(rk)
                items.insert(items.index(q["after"]) + 1 if "after" in q else 0, rk)
            return mc({})
        if path == "/hubs/sections/1/manage":
            return mc({"Hub": []})
        return mc({})


SECTION = {"id": "1", "title": "Movies", "type": "movie"}


def plex_with(fake):
    return Plex("http://plex", "token", client=httpx.Client(transport=fake))


def refs_for(*ids):
    return [MediaRef("movie", imdb=f"tt000000{i}") for i in ids]


def test_sync_creates_then_updates_with_order():
    fake = FakePlex()
    plex = plex_with(fake)
    cfg = CollectionConfig(name="Best", library="Movies", sources=[Source(type="static", value="x")])

    first = sync_collection(cfg, {}, plex, SECTION, refs_for(3, 1, 2, 9), {"managed_label": "Curatarr"})
    assert fake.collections["100"] == ["3", "1", "2"]
    assert (first.added, first.removed, first.matched) == (3, 0, 3)
    assert [m["imdb"] for m in first.missing] == ["tt0000009"]
    assert first.state["plex_rating_key"] == "100"

    second = sync_collection(cfg, first.state, plex, SECTION, refs_for(4, 2, 3), {})
    assert fake.collections["100"] == ["4", "2", "3"]
    assert (second.added, second.removed) == (1, 1)


def test_sync_append_mode_and_minimum():
    fake = FakePlex()
    plex = plex_with(fake)
    cfg = CollectionConfig(name="Best", library="Movies", sync_mode="append", min_items=2,
                           sources=[Source(type="static", value="x")])
    skipped = sync_collection(cfg, {}, plex, SECTION, refs_for(1), {})
    assert skipped.status == "skipped" and not fake.collections

    sync_collection(cfg, {}, plex, SECTION, refs_for(1, 2), {})
    result = sync_collection(cfg, {"plex_rating_key": "100"}, plex, SECTION, refs_for(3, 2), {})
    assert set(fake.collections["100"]) == {"1", "2", "3"} and result.removed == 0


def test_reorder_moves():
    assert reorder_moves(["a", "b", "c"], ["a", "b", "c"]) == []
    current = ["c", "a", "b", "x"]
    moves = reorder_moves(current, ["a", "b", "c"])
    for item, after in moves:
        current.remove(item)
        current.insert(current.index(after) + 1 if after else 0, item)
    assert current == ["a", "b", "c", "x"]


# --- YAML round trip ----------------------------------------------------------------

def test_yaml_import_export_roundtrip():
    text = """
collections:
  - name: Top 250
    library: Movies
    sources: [{type: imdb_chart, value: top}]
    promote_home: true
  - name: Broken
    sources: []
"""
    result = api.import_yaml(text)
    assert result["created"] == 1 and len(result["errors"]) == 1
    exported = api.export_yaml()
    assert "Top 250" in exported and "promote_home: true" in exported and "section_id" not in exported
    again = api.import_yaml(exported)
    assert again == {"created": 0, "updated": 1, "errors": []}
    assert len(db.list_collections()) == 1


# --- logging ------------------------------------------------------------------------

def test_redact_hides_tokens_and_keys():
    from app.logs import redact
    text = ("GET https://api.themoviedb.org/3/list/1?api_key=abc123&page=2 "
            "http://plex:32400/identity?X-Plex-Token=SECRET "
            "headers={'X-Plex-Token': 'SECRET2', 'Authorization': 'Bearer eyJhbGci'}")
    out = redact(text)
    for secret in ("abc123", "SECRET", "SECRET2", "eyJhbGci"):
        assert secret not in out
    assert "page=2" in out and "[REDACTED]" in out


def test_log_tail_filters_and_bundle(tmp_path, monkeypatch):
    import zipfile
    from app import logs
    monkeypatch.setattr(logs, "LOG_DIR", tmp_path)
    monkeypatch.setattr(logs, "LOG_FILE", tmp_path / "curatarr.log")
    (tmp_path / "curatarr.log").write_text(
        "2026-10-26 10:00:00,000 INFO    app.sync: Syncing collection 'A' (manual)\n"
        "2026-10-26 10:00:01,000 ERROR   app.sync: Sync of 'A' crashed\n"
        "Traceback (most recent call last):\n"
        "  boom api_key=leaked\n"
        "2026-10-26 10:00:02,000 WARNING app.sync: 'B': source failed\n", encoding="utf-8")
    assert len(logs.tail(100)) == 3
    errors = logs.tail(100, level="ERROR")
    assert len(errors) == 1 and "Traceback" in errors[0]["message"]
    assert [e["message"] for e in logs.tail(100, search="'b'")] == ["'B': source failed"]

    data = logs.bundle({"plex_url": "http://plex", "plex_token": "tok"}, [])
    with zipfile.ZipFile(__import__("io").BytesIO(data)) as zf:
        assert set(zf.namelist()) == {"diagnostics.txt", "curatarr.log"}
        assert "leaked" not in zf.read("curatarr.log").decode()
        diag = zf.read("diagnostics.txt").decode()
        assert "tok" not in diag.replace("token", "") and "plex_token=set" in diag


def test_tmdb_page_links_become_discover_queries():
    seen = []

    def handler(request):
        seen.append((request.url.path, dict(request.url.params)))
        if request.url.path == "/3/discover/movie":
            return httpx.Response(200, json={"total_pages": 1, "results": [
                {"id": 1, "title": "The Chosen", "release_date": "2024-01-01"}]})
        return httpx.Response(404)

    from app.sources import tmdb
    refs = tmdb.fetch_list("https://www.themoviedb.org/company/165435-angel-studios/movie",
                           ctx(handler, tmdb_api_key="k"), None)
    assert [r.tmdb for r in refs] == [1]
    path, params = seen[0]
    assert path == "/3/discover/movie" and params["with_companies"] == "165435"
    assert tmdb._page_query("https://www.themoviedb.org/network/213-netflix", "movie")[0] == "tv"
    with pytest.raises(SourceError, match="not a TMDB list"):
        tmdb.fetch_list("https://www.themoviedb.org/movie/603", ctx(handler, tmdb_api_key="k"), None)


def test_linking_existing_collection_in_append_mode_keeps_its_items():
    fake = FakePlex()
    fake.collections["100"] = ["5", "6"]          # made in Plex, not by Curatarr
    plex = plex_with(fake)
    cfg = CollectionConfig(name="Best", library="Movies", sync_mode="append",
                           sources=[Source(type="static", value="x")])
    result = sync_collection(cfg, {"plex_rating_key": "100"}, plex, SECTION, refs_for(1, 5), {})
    assert set(fake.collections["100"]) == {"1", "5", "6"}
    assert (result.added, result.removed) == (1, 0)
    assert not any(c.startswith("POST /library/collections") for c in fake.calls)


def test_old_default_schedule_is_migrated():
    from app import main
    db.save_settings({"default_schedule": "0 3 * * *"})
    main.migrate_default_schedule()
    assert db.get_settings()["default_schedule"] == "0 */6 * * *"
    db.save_settings({"default_schedule": "30 1 * * *"})   # a user's own choice is kept
    main.migrate_default_schedule()
    assert db.get_settings()["default_schedule"] == "30 1 * * *"


def test_reorder_moves_is_correct_and_minimal():
    import random

    def apply(current, moves):
        current = list(current)
        for item, after in moves:
            current.remove(item)
            current.insert(current.index(after) + 1 if after else 0, item)
        return current

    rng = random.Random(7)
    for _ in range(200):
        items = [str(i) for i in range(rng.randint(0, 40))]
        current = items[:]
        rng.shuffle(current)
        desired = rng.sample(items, k=len(items) - rng.randint(0, min(5, len(items))))
        moves = reorder_moves(current, desired)
        result = apply(current, moves)
        assert result[:len(desired)] == desired
        assert sorted(result) == sorted(current)
    # One item out of place needs exactly one move, however long the list.
    long = [str(i) for i in range(500)]
    assert len(reorder_moves(long[1:] + long[:1], long)) == 1


def test_paging_stops_when_endpoint_ignores_offsets():
    calls = []

    def handler(request):
        calls.append(1)   # always the same page, with a misleading totalSize
        return httpx.Response(200, json={"MediaContainer": {
            "totalSize": 9999, "Metadata": [{"ratingKey": "1"}, {"ratingKey": "2"}]}})

    plex = Plex("http://plex", "t", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert [m["ratingKey"] for m in plex._paged("/x")] == ["1", "2"]
    assert len(calls) == 2


def test_index_html_versions_assets():
    from app import config, main
    html = main._index_html()
    assert f"/static/app.js?v={config.VERSION}" in html
    assert f"/static/style.css?v={config.VERSION}" in html


# --- home screen calendar ------------------------------------------------------------

def _cal(**kw):
    base = dict(name="Halloween", library="Movies", sources=[Source(type="static", value="x")],
                promote_home=True, promote_shared=True, promote_recommended=True,
                promote_window=True, promote_start="2026-10-01", promote_end="2026-10-31")
    return CollectionConfig(**{**base, **kw})


def test_calendar_window_yearly_and_one_off():
    from datetime import date
    cfg = _cal()
    assert cfg.promotion_active(date(2031, 10, 15))           # yearly ignores the year
    assert not cfg.promotion_active(date(2031, 11, 1))
    assert cfg.promotion_flags(date(2026, 10, 31)) == (True, True, True)
    assert cfg.promotion_flags(date(2026, 9, 30)) == (False, False, False)

    xmas = _cal(promote_start="2026-12-15", promote_end="2027-01-05")   # wraps New Year
    assert xmas.promotion_active(date(2027, 12, 20)) and xmas.promotion_active(date(2028, 1, 3))
    assert not xmas.promotion_active(date(2028, 1, 6))

    once = _cal(promote_yearly=False)
    assert once.promotion_active(date(2026, 10, 10)) and not once.promotion_active(date(2027, 10, 10))

    assert _cal(promote_window=False).promotion_active(date(2026, 1, 1))
    with pytest.raises(ValueError, match="start and end"):
        _cal(promote_end="")
    with pytest.raises(ValueError, match="ends before"):
        _cal(promote_yearly=False, promote_start="2026-10-31", promote_end="2026-10-01")


def test_sync_applies_calendar_to_home_screen():
    from datetime import date
    for today, expect_hub in ((date(2026, 10, 10), True), (date(2026, 12, 1), False)):
        fake = FakePlex()
        sync_collection(_cal(), {}, plex_with(fake), SECTION, refs_for(1, 2), {}, today=today)
        assert any(c == "POST /hubs/sections/1/manage" for c in fake.calls) is expect_hub


# --- holidays -------------------------------------------------------------------------

def test_holiday_windows_and_config():
    from datetime import date
    from app import holidays
    wrap = {"start": "12-26", "end": "01-02"}
    assert holidays.window_dates(wrap, 2026) == ("2026-12-26", "2027-01-02")
    assert [h["key"] for h in holidays.HOLIDAYS] == [
        "valentines", "st-patricks", "easter", "independence-day", "halloween", "veterans-day",
        "thanksgiving", "christmas"]
    assert all(holidays.available(h) and h["link"].startswith("https://www.themoviedb.org/keyword/")
               for h in holidays.HOLIDAYS)
    for h in holidays.HOLIDAYS:
        cfg = CollectionConfig(**holidays.collection_config(
            {**h, "sources": [{"type": "static", "value": "tt0000001"}]},
            {"id": "1", "title": "Movies"}))
        assert cfg.holiday == h["key"] and cfg.promote_window and cfg.promote_yearly
        assert cfg.promote_home and cfg.promote_shared and cfg.promote_recommended
    hw = CollectionConfig(**holidays.collection_config(
        {**holidays.get("halloween"), "sources": [{"type": "static", "value": "tt1"}]},
        {"id": "1", "title": "Movies"}))
    assert hw.promotion_active(date(2030, 10, 15)) and not hw.promotion_active(date(2030, 11, 2))


def test_enable_holiday_endpoint(monkeypatch):
    from contextlib import nullcontext
    from fastapi.testclient import TestClient
    from app import api as api_mod, holidays, scheduler, sync as sync_mod
    from app.main import app

    monkeypatch.setattr(api_mod, "_plex", lambda: nullcontext(object()))
    monkeypatch.setattr(sync_mod, "resolve_section",
                        lambda plex, sid, lib: {"id": "1", "title": "Movies", "type": "movie"})
    monkeypatch.setattr(scheduler, "run_now", lambda *a, **k: None)
    client = TestClient(app)

    assert client.post("/api/holidays/new-years/enable", json={"section_id": "1"}).status_code == 404
    r = client.post("/api/holidays/halloween/enable", json={"section_id": "1", "request_missing": True})
    assert r.status_code == 201
    cfg = r.json()["config"]
    assert cfg["holiday"] == "halloween" and cfg["request_missing"] is True
    assert cfg["sources"][0]["value"] == "movie?with_keywords=3335&sort_by=popularity.desc"
    assert cfg["sources"][0]["limit"] == 100
    assert cfg["poster_file"].endswith("-poster.jpg")
    assert client.get(f"/api/collections/{r.json()['id']}/image/poster").status_code == 200
    assert client.post("/api/holidays/halloween/enable", json={"section_id": "1"}).status_code == 409
    listed = {h["key"]: h for h in client.get("/api/holidays").json()}
    assert listed["halloween"]["available"] and len(listed["halloween"]["collections"]) == 1
    assert listed["christmas"]["collections"] == [] and "radarr" in listed["christmas"]["arr_ready"]


def test_backfill_updates_old_holiday_collections():
    from app import holidays
    cfg = CollectionConfig(**holidays.collection_config(holidays.get("christmas"),
                                                        {"id": "9", "title": "Movies"})).model_dump()
    assert cfg["sort_title"] == "!01_Christmas Collection"
    cid = db.create_collection({**cfg, "sort_title": ""})        # as created by v0.5.0
    assert holidays.backfill() >= 1
    updated = db.get_collection(cid)["config"]
    assert updated["poster_file"] == f"{cid}-poster.jpg"
    assert updated["sort_title"] == "!01_Christmas Collection"
    assert holidays.backfill() == 0      # nothing left to do

    custom = db.create_collection({**cfg, "sort_title": "zz mine", "poster_url": "http://x/p.jpg"})
    holidays.backfill()
    kept = db.get_collection(custom)["config"]
    assert kept["sort_title"] == "zz mine" and kept["poster_file"] == ""
