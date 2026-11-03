import json
import os
import tempfile

os.environ["CURATARR_CONFIG_DIR"] = tempfile.mkdtemp(prefix="curatarr-test-")

import httpx  # noqa: E402
import pytest  # noqa: E402

from app import api, db  # noqa: E402
from app.models import CollectionConfig, Source  # noqa: E402
from app.plex import LibraryIndex, Plex, PlexError, parse_guid  # noqa: E402
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
        self.collection_title = "Best"          # every fake collection has this title
        self.sections: dict[str, str] = {}        # collection key -> library section id
        self.calls: list[str] = []

    def handle_request(self, request):
        path, method, q = request.url.path, request.method, request.url.params
        self.calls.append(f"{method} {path}")
        mc = lambda body: httpx.Response(200, json={"MediaContainer": body})  # noqa: E731
        if path == "/identity":
            return mc({"machineIdentifier": "abc"})
        if path == "/library/sections/1/all" and method == "GET":
            items = [{"ratingKey": rk, "title": f"T{rk}", "Guid": [{"id": g}],
                      "contentRating": {"5": "R", "6": "gb/18"}.get(rk, "PG")} for rk, g in self.library.items()]
            return mc({"Metadata": items, "totalSize": len(items)})
        if path == "/library/sections/1/collections":
            return mc({"Metadata": [{"ratingKey": k, "title": self.collection_title, "smart": 0}
                                    for k in self.collections]})
        if path == "/library/collections" and method == "POST":
            rks = q["uri"].rsplit("/", 1)[1].split(",")
            self.collections["100"] = rks
            return mc({"Metadata": [{"ratingKey": "100"}]})
        if path.startswith("/library/sections/") and "/collection/" in path and method == "DELETE":
            return httpx.Response(404, text="Not Found")      # documented, but real Plex says 404
        if path.startswith("/library/metadata/") and method == "DELETE":
            key = path.split("/")[3]
            if key not in self.collections:
                return httpx.Response(404, text="Not Found")
            del self.collections[key]
            return mc({})
        if path.startswith("/library/metadata/") and method == "GET":
            key = path.split("/")[3]
            return mc({"Metadata": [{"type": "collection", "librarySectionID": self.sections.get(key, "1")}]}
                      if key in self.collections else {})
        parts = path.split("/")
        if path.startswith("/library/collections/100/items"):
            items = self.collections["100"]
            if method == "GET":
                return mc({"Metadata": [{"ratingKey": rk} for rk in items], "totalSize": len(items)})
            if len(parts) == 5:   # add
                items.extend(q["uri"].rsplit("/", 1)[1].split(","))
            elif len(parts) == 6 and method == "DELETE":   # remove (real Plex uses DELETE)
                items.remove(parts[5])
            elif len(parts) == 6:
                return httpx.Response(404, text="Not Found")
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
        "new-years", "lunar-new-year", "football", "valentines", "st-patricks", "easter", "mothers-day",
        "fathers-day", "independence-day", "back-to-school", "halloween", "veterans-day", "thanksgiving",
        "christmas", "hanukkah"]
    assert all(holidays.poster_path(h) for h in holidays.HOLIDAYS)
    assert holidays.get("hanukkah")["sources"][0]["value"] == "movie?with_keywords=7328|272884&sort_by=popularity.desc"
    assert all(holidays.available(h) and h["link"].startswith("https://www.themoviedb.org/keyword/")
               for h in holidays.HOLIDAYS)
    for h in holidays.HOLIDAYS:
        cfg = CollectionConfig(**holidays.collection_config(
            {**h, "sources": [{"type": "static", "value": "tt0000001"}]},
            {"id": "1", "title": "Movies"}))
        assert cfg.holiday == h["key"] and cfg.promote_window and cfg.promote_yearly
        assert cfg.promote_home and cfg.promote_shared and cfg.promote_recommended and cfg.pin_top
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

    assert client.post("/api/holidays/flag-day/enable", json={"section_id": "1"}).status_code == 404
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


def test_existing_same_named_collection_is_never_stripped():
    fake = FakePlex()
    db.save_settings({"made_by_curatarr": "[]"})  # fake keys repeat across tests
    fake.collections["100"] = ["5", "6"]          # the user's own "Users Best" collection
    fake.collection_title = "Users Best"
    plex = plex_with(fake)
    cfg = CollectionConfig(name="Users Best", library="Movies", sources=[Source(type="static", value="x")])
    result = sync_collection(cfg, {}, plex, SECTION, refs_for(1, 2), {})
    assert set(fake.collections["100"]) == {"1", "2", "5", "6"}
    assert result.removed == 0 and result.state["plex_owned"] == 0
    assert "only adds" in " ".join(result.messages)
    # once the user allows it, removals happen
    owned = sync_collection(cfg, {**result.state, "plex_owned": 1}, plex, SECTION, refs_for(1, 2), {})
    assert set(fake.collections["100"]) == {"1", "2"} and owned.removed == 2


def test_collection_in_another_library_is_replaced_not_reused():
    fake = FakePlex()
    fake.collections["100"] = ["5"]
    fake.sections["100"] = "3"                     # lives in a different library
    plex = plex_with(fake)
    cfg = CollectionConfig(name="Fresh", library="Movies", sources=[Source(type="static", value="x")])
    result = sync_collection(cfg, {"plex_rating_key": "100", "plex_owned": 1}, plex, SECTION,
                             refs_for(1), {})
    # a new collection is created instead of adding these titles to the other library's one
    assert any(c == "POST /library/collections" for c in fake.calls)
    assert not any(c == "PUT /library/collections/100/items" for c in fake.calls)
    assert "Library changed" in " ".join(result.messages)


def test_arr_requests_skip_existing_and_respect_limit():
    from app import arr as arrmod
    added = []

    def radarr(request):
        p = request.url.path
        if p == "/api/v3/movie" and request.method == "GET":
            return httpx.Response(200, json=[{"tmdbId": 1}])
        if p == "/api/v3/movie/lookup/tmdb":
            return httpx.Response(200, json=[{"title": "x", "tmdbId": int(request.url.params["tmdbId"])}])
        if p == "/api/v3/movie" and request.method == "POST":
            added.append(1)
            return httpx.Response(201, json={})
        return httpx.Response(404)

    settings = {"radarr_url": "http://radarr", "radarr_api_key": "k", "radarr_root_folder": "/m",
                "radarr_quality_profile": "1", "arr_max_requests": "5"}
    refs = [MediaRef("movie", tmdb=i) for i in range(1, 41)]
    http = httpx.Client(transport=httpx.MockTransport(radarr))
    count, errors, limited = arrmod.request_missing("movie", refs, settings, http)
    assert (count, errors, limited) == (5, [], True) and len(added) == 5
    count, _, limited = arrmod.request_missing("movie", refs[:3], {**settings, "arr_max_requests": "0"}, http)
    assert (count, limited) == (2, False)          # tmdb 1 is already in Radarr


# --- seasonal-only collections ---------------------------------------------------------

def test_off_season_and_next_start():
    from datetime import date
    from app.sync import next_start
    cfg = _cal(seasonal_only=True)
    assert cfg.off_season(date(2026, 11, 2)) and not cfg.off_season(date(2026, 10, 2))
    assert not _cal().off_season(date(2026, 11, 2))          # option off: never off season
    assert next_start(cfg, date(2026, 11, 2)) == date(2027, 10, 1)
    assert next_start(cfg, date(2026, 9, 2)) == date(2026, 10, 1)


def test_remove_off_season_deletes_only_owned_collections():
    from datetime import date
    from app.sync import remove_off_season
    cfg = _cal(seasonal_only=True, name="Someone Elses Halloween")
    db.save_settings({"made_by_curatarr": "[]"})  # fake keys repeat across tests
    fake = FakePlex()
    fake.collections["100"] = ["1", "2"]
    plex = plex_with(fake)
    kept = remove_off_season(cfg, {"plex_rating_key": "100", "plex_owned": 0}, plex, SECTION,
                             today=date(2026, 11, 2))
    assert "left in place" in kept.messages[0] and kept.state["plex_rating_key"] == "100"
    assert not any(c.startswith("DELETE") for c in fake.calls)

    gone = remove_off_season(cfg, {"plex_rating_key": "100", "plex_owned": 1, "poster_applied": "x"},
                             plex, SECTION, today=date(2026, 11, 2))
    assert "DELETE /library/metadata/100" in fake.calls and "100" not in fake.collections
    assert gone.status == "skipped" and "until Oct 1" in gone.messages[0]
    assert gone.state["plex_rating_key"] is None and gone.state["poster_applied"] is None


def test_calendar_job_creates_and_removes_seasonal_collections(monkeypatch):
    from datetime import date
    from app import sync as sync_mod
    for row in db.list_collections():
        db.delete_collection(row["id"])
    base = _cal(seasonal_only=True).model_dump()
    in_season_missing = db.create_collection({**base, "name": "A"})
    off_season_present = db.create_collection({**base, "name": "B"})
    db.update_collection_state(off_season_present, plex_rating_key="200")
    db.create_collection({**base, "name": "C", "seasonal_only": False})
    calls = []
    monkeypatch.setattr(sync_mod, "run_collection", lambda cid, trigger: calls.append((cid, trigger)))
    monkeypatch.setattr(sync_mod.plexmod, "from_settings",
                        lambda s: (_ for _ in ()).throw(sync_mod.PlexError("no plex")))
    sync_mod.apply_home_calendars(date(2026, 10, 5))     # in season
    assert calls == [(in_season_missing, "calendar")]
    calls.clear()
    sync_mod.apply_home_calendars(date(2026, 11, 5))     # out of season
    assert calls == [(off_season_present, "calendar")]


def test_collection_contents_and_items_endpoint(monkeypatch):
    from contextlib import nullcontext
    from fastapi.testclient import TestClient
    from app import api as api_mod, db
    from app.main import app

    def handler(request):
        assert request.url.path == "/library/collections/7/items"
        return httpx.Response(200, json={"MediaContainer": {"totalSize": 3, "Metadata": [
            {"ratingKey": 1, "title": "Seen", "year": 1999, "type": "movie", "viewCount": 2, "thumb": "/library/metadata/1/thumb/1"},
            {"ratingKey": 2, "title": "Unseen", "year": 2001, "type": "movie"},
            {"ratingKey": 3, "title": "Show", "type": "show", "leafCount": 10, "viewedLeafCount": 4},
        ]}})
    plex = Plex("http://plex", "token", client=httpx.Client(transport=httpx.MockTransport(handler)))
    items = plex.collection_contents("7")
    assert [(i["title"], i["watched"], i["episodes"]) for i in items] == [
        ("Seen", True, None), ("Unseen", False, None), ("Show", False, 10)]

    monkeypatch.setattr(api_mod, "_plex", lambda: nullcontext(plex))
    client = TestClient(app)
    cid = db.create_collection({"name": "View me", "library": "Movies", "section_id": "1",
                                "sources": [{"type": "static", "value": "tt0000001"}]})
    assert client.get(f"/api/collections/{cid}/items").json() == {"in_plex": False, "items": []}
    db.update_collection_state(cid, plex_rating_key="7")
    r = client.get(f"/api/collections/{cid}/items").json()
    assert r["in_plex"] and len(r["items"]) == 3
    assert len(client.get("/api/plex/collections/7/items").json()) == 3


def test_exclusions_and_rating_cap():
    from app import sync as sync_mod
    sync_mod.clear_index_cache()
    fake = FakePlex()
    plex = plex_with(fake)
    cfg = CollectionConfig(name="Best", library="Movies", sources=[Source(type="static", value="x")],
                           exclude=[{"id": "plex:2"}, {"id": "tt0000009", "title": "Not owned"}],
                           max_rating="PG-13")
    result = sync_collection(cfg, {}, plex, SECTION, refs_for(1, 2, 3, 5, 6, 9), {})
    # 2 is excluded by rating key, 5 is R, 6 is unrated (non-US) and kept; 9 is excluded, not "missing"
    assert fake.collections["100"] == ["1", "3", "6"]
    assert result.missing == []
    assert any("rating cap" in m for m in result.messages)
    cfg.drop_unrated = True
    sync_collection(cfg, result.state, plex, SECTION, refs_for(1, 2, 3, 5, 6), {})
    assert fake.collections["100"] == ["1", "3"]
    with pytest.raises(ValueError):
        CollectionConfig(name="x", sources=[Source(type="static", value="x")], max_rating="PG-15")


def test_run_diffs_and_undo(monkeypatch):
    from app import plex as plexmod, sync as sync_mod
    sync_mod.clear_index_cache()
    fake = FakePlex()
    monkeypatch.setattr(plexmod, "from_settings", lambda *a, **k: plex_with(fake))
    cfg = CollectionConfig(name="Undo me", library="Movies", section_id="1",
                           sources=[Source(type="static", value="x")])
    cid = db.create_collection(cfg.model_dump())
    first = sync_collection(cfg, {}, plex_with(fake), SECTION, refs_for(1, 2), {})
    second = sync_collection(cfg, first.state, plex_with(fake), SECTION, refs_for(2, 3), {})
    assert [i["rk"] for i in second.added_items] == ["3"] and second.added_items[0]["title"] == "T3"
    assert [i["rk"] for i in second.removed_items] == ["1"]
    db.update_collection_state(cid, plex_rating_key="100", plex_owned=1)
    db.record_run({"collection_id": cid, "collection_name": "Undo me", "status": "success",
                   "added": 1, "removed": 1, "added_items": second.added_items,
                   "removed_items": second.removed_items})
    assert db.list_runs(cid)[0]["added_items"][0]["rk"] == "3"

    run = sync_mod.undo_last_sync(cid)
    assert sorted(fake.collections["100"]) == ["1", "2"]
    assert run["trigger"] == "undo" and not db.get_collection(cid)["config"]["enabled"]
    sync_mod.undo_last_sync(cid)          # undoing the undo redoes the change
    assert sorted(fake.collections["100"]) == ["2", "3"]


def test_exclude_and_request_endpoints(monkeypatch):
    from contextlib import nullcontext
    from fastapi.testclient import TestClient
    from app import api as api_mod, arr as arr_mod
    from app.main import app

    fake = FakePlex()
    fake.collections["100"] = ["1", "2"]
    monkeypatch.setattr(api_mod, "_plex", lambda: nullcontext(plex_with(fake)))
    client = TestClient(app)
    cid = db.create_collection({"name": "Ex", "library": "Movies", "section_id": "1",
                                "sources": [{"type": "static", "value": "tt0000001"}]})
    db.update_collection_state(cid, plex_rating_key="100")
    r = client.post(f"/api/collections/{cid}/exclude", json={"id": "plex:2", "title": "T2"})
    assert r.status_code == 200 and r.json()["config"]["exclude"] == [{"id": "plex:2", "title": "T2"}]
    assert fake.collections["100"] == ["1"]
    client.post(f"/api/collections/{cid}/exclude", json={"id": "plex:2"})       # no duplicate
    assert len(db.get_collection(cid)["config"]["exclude"]) == 1

    assert client.post(f"/api/collections/{cid}/request", json={"imdb": "tt1"}).status_code == 400
    added = []
    monkeypatch.setattr(arr_mod.Arr, "configured", property(lambda self: True))
    monkeypatch.setattr(arr_mod.Arr, "add", lambda self, ref: added.append((self.kind, ref.imdb)) or "added")
    r = client.post(f"/api/collections/{cid}/request", json={"imdb": "tt7", "media_type": "show"})
    assert r.json() == {"status": "added", "service": "sonarr"} and added == [("sonarr", "tt7")]


def test_plex_filter_source():
    from app.sources import plexfilter
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, json={"MediaContainer": {"totalSize": 2, "Metadata": [
            {"ratingKey": 1, "title": "Halloween", "year": 1978,
             "Guid": [{"id": "imdb://tt0077651"}, {"id": "tmdb://948"}]},
            {"ratingKey": 2, "title": "No Guids", "year": 1981},
        ]}})
    plex = Plex("http://plex", "token", client=httpx.Client(transport=httpx.MockTransport(handler)))
    ctx = SourceContext({}, None, "movie", plex, {"id": "1", "title": "Movies", "type": "movie"})
    refs = plexfilter.fetch("genre=12&year>>=1970&year<<=1989&X-Plex-Token=evil", ctx, None)
    assert [(r.imdb, r.tmdb, r.title, r.year) for r in refs] == [
        ("tt0077651", 948, "Halloween", 1978), (None, None, "No Guids", 1981)]
    params = seen[0].params
    assert seen[0].path == "/library/sections/1/all"
    assert params["genre"] == "12" and params["year>>"] == "1970" and params["year<<"] == "1989"
    assert "X-Plex-Token" not in params                 # dropped from the filter; the real token is a header
    with pytest.raises(SourceError):
        plexfilter.fetch("X-Plex-Token=x", ctx, None)
    with pytest.raises(SourceError):
        plexfilter.fetch("genre=1", SourceContext({}, None, "movie"), None)


def test_starter_packs(monkeypatch):
    from contextlib import nullcontext
    from fastapi.testclient import TestClient
    from app import api as api_mod, packs, scheduler, sync as sync_mod
    from app.main import app

    assert len({i for i in packs.ITEMS}) == sum(len(p["items"]) for p in packs.PACKS)
    for pack in packs.PACKS:
        for item in pack["items"]:
            Source(**item["source"])                          # every pack item is a valid source
            assert item["source"]["value"].startswith("movie?" if pack["media"] == "movie" else "tv?")
    monkeypatch.setattr(api_mod, "_plex", lambda: nullcontext(object()))
    monkeypatch.setattr(sync_mod, "resolve_section",
                        lambda plex, sid, lib: {"id": "7", "title": "Films", "type": "movie"})
    queued = []
    monkeypatch.setattr(scheduler, "run_now", lambda cid: queued.append(cid))
    client = TestClient(app)
    listed = client.get("/api/packs?media=movie").json()
    assert {p["key"] for p in listed} == {"studios", "movie-decades", "movie-genres"}
    r = client.post("/api/packs", json={"section_id": "7", "keys": ["studios.pixar-collection", "movie-genres.top-horror"],
                                        "sync_mode": "append", "sync_now": True})
    assert r.status_code == 201 and r.json() == {"created": 2, "skipped": []} and len(queued) == 2
    again = client.post("/api/packs", json={"section_id": "7", "keys": ["studios.pixar-collection"]})
    assert again.json() == {"created": 0, "skipped": ["Pixar Collection"]}
    assert client.post("/api/packs", json={"section_id": "7", "keys": ["networks.hbo-originals"]}).status_code == 422
    pixar = next(r for r in db.list_collections() if r["config"]["name"] == "Pixar Collection")["config"]
    assert pixar["sync_mode"] == "append" and pixar["order"] == "release" and pixar["section_id"] == "7"


class FakePlaylistPlex(httpx.BaseTransport):
    """Plex playlists: a show added to a playlist becomes its episodes."""

    def __init__(self):
        self.movies = {"1": "imdb://tt0000001", "2": "imdb://tt0000002", "3": "imdb://tt0000003"}
        self.shows = {"10": "tvdb://100", "20": "tvdb://200"}
        self.episodes = {"10": ["101", "102"], "20": ["201"]}
        self.playlists: dict[str, list[tuple[str, str]]] = {}     # id -> [(itemID, ratingKey)]
        self.next_item = 1
        self.calls: list[str] = []

    def _expand(self, rks):
        out = []
        for rk in rks:
            for real in self.episodes.get(rk, [rk]):
                out.append((str(self.next_item), real))
                self.next_item += 1
        return out

    def handle_request(self, request):
        path, method, q = request.url.path, request.method, request.url.params
        self.calls.append(f"{method} {path}")
        mc = lambda body: httpx.Response(200, json={"MediaContainer": body})  # noqa: E731
        parts = path.strip("/").split("/")
        if path == "/identity":
            return mc({"machineIdentifier": "abc"})
        if path in ("/library/sections/1/all", "/library/sections/2/all"):
            lib = self.movies if path == "/library/sections/1/all" else self.shows
            items = [{"ratingKey": rk, "title": f"T{rk}", "Guid": [{"id": g}]} for rk, g in lib.items()]
            return mc({"Metadata": items, "totalSize": len(items)})
        if path == "/playlists" and method == "GET":
            return mc({"Metadata": [{"ratingKey": k, "title": "Watch order", "leafCount": len(v)}
                                    for k, v in self.playlists.items()]})
        if path == "/playlists" and method == "POST":
            self.playlists["900"] = self._expand(q["uri"].rsplit("/", 1)[1].split(","))
            return mc({"Metadata": [{"ratingKey": "900"}]})
        if parts[0] == "playlists" and len(parts) >= 2:
            pid = parts[1]
            if pid not in self.playlists:
                return httpx.Response(404, text="Not Found")
            items = self.playlists[pid]
            if len(parts) == 2:
                if method == "DELETE":
                    del self.playlists[pid]
                return mc({"Metadata": [{"ratingKey": pid}]})
            if len(parts) == 3 and method == "GET":
                meta = []
                for item_id, rk in items:
                    show = next((s for s, eps in self.episodes.items() if rk in eps), None)
                    meta.append({"ratingKey": rk, "playlistItemID": item_id, "title": f"T{rk}",
                                 **({"type": "episode", "grandparentRatingKey": show, "grandparentTitle": f"T{show}"}
                                    if show else {"type": "movie"})})
                return mc({"Metadata": meta, "totalSize": len(meta)})
            if len(parts) == 3 and method == "PUT":
                items.extend(self._expand(q["uri"].rsplit("/", 1)[1].split(",")))
            elif len(parts) == 3 and method == "DELETE":
                items.clear()
            elif len(parts) == 4 and method == "DELETE":
                self.playlists[pid] = [i for i in items if i[0] != parts[3]]
            return mc({})
        return mc({})


def test_playlist_sync_across_libraries():
    from app import sync as sync_mod
    sync_mod.clear_index_cache()
    fake = FakePlaylistPlex()
    plex = Plex("http://plexpl", "token", client=httpx.Client(transport=fake))
    movies, shows = {"id": "1", "title": "Movies", "type": "movie"}, {"id": "2", "title": "TV", "type": "show"}
    cfg = CollectionConfig(name="Watch order", kind="playlist", section_ids=["1", "2"], libraries=["Movies", "TV"],
                           sources=[Source(type="static", value="x")])
    assert cfg.section_id == "1" and cfg.library == "Movies" and not cfg.promote_window
    refs = [MediaRef("movie", imdb="tt0000002"), MediaRef("show", tvdb=10 * 10), MediaRef("movie", imdb="tt0000001"),
            MediaRef("movie", imdb="tt0000009")]
    first = sync_mod.sync_playlist(cfg, {}, plex, [movies, shows], refs, {})
    assert [rk for _, rk in fake.playlists["900"]] == ["2", "101", "102", "1"]
    assert first.added == 3 and len(first.missing) == 1 and first.state["plex_owned"] == 1
    assert plex.playlist_units("900") == [("2", ["1"]), ("10", ["2", "3"]), ("1", ["4"])]
    view = plex.playlist_contents("900")
    assert [(v["title"], v["type"], v["episodes"]) for v in view] == [("T2", "movie", None), ("T10", "show", 2), ("T1", "movie", None)]

    # Appending at the end only adds; no rebuild.
    fake.calls.clear()
    second = sync_mod.sync_playlist(cfg, first.state, plex, [movies, shows], refs[:3] + [MediaRef("show", tvdb=200)], {})
    assert second.added == 1 and "DELETE /playlists/900/items" not in fake.calls
    assert [rk for _, rk in fake.playlists["900"]][-1] == "201"

    # A new order or a removal rebuilds the playlist in list order.
    third = sync_mod.sync_playlist(cfg, second.state, plex, [movies, shows],
                                   [MediaRef("movie", imdb="tt0000001"), MediaRef("show", tvdb=100)], {})
    assert [rk for _, rk in fake.playlists["900"]] == ["1", "101", "102"]
    assert third.removed == 2 and {i["rk"] for i in third.removed_items} == {"2", "20"}

    # Removing one show takes out all of its episodes.
    sync_mod.remove_titles(plex, cfg, "900", ["10"])
    assert [rk for _, rk in fake.playlists["900"]] == ["1"]


def test_manual_order_and_calendar_changes(monkeypatch):
    from datetime import date
    from app import plex as plexmod, sync as sync_mod
    cfg = CollectionConfig(name="M", sources=[Source(type="static", value="x")], manual_order=["3", "9", "1"])
    assert sync_mod.desired_order(cfg, ["1", "2", "3"]) == ["3", "1", "2"]

    sync_mod.clear_index_cache()
    fake = FakePlex()
    fake.collections["100"] = ["1", "2", "3"]
    monkeypatch.setattr(plexmod, "from_settings", lambda *a, **k: plex_with(fake))
    cid = db.create_collection({"name": "Arrange", "library": "Movies", "section_id": "1",
                                "sources": [{"type": "static", "value": "tt0000001"}]})
    db.update_collection_state(cid, plex_rating_key="100")
    sync_mod.apply_manual_order(cid, ["3", "1"])
    assert fake.collections["100"] == ["3", "1", "2"]
    assert db.get_collection(cid)["config"]["manual_order"] == ["3", "1"]
    # The next sync keeps the hand-made order and puts new titles after it.
    cfg = CollectionConfig(**db.get_collection(cid)["config"])
    sync_collection(cfg, {"plex_rating_key": "100", "plex_owned": 1}, plex_with(fake), SECTION, refs_for(1, 2, 3, 4), {})
    assert fake.collections["100"] == ["3", "1", "2", "4"]

    xmas = CollectionConfig(name="X", sources=[Source(type="static", value="x")], promote_window=True,
                            promote_start="2000-11-25", promote_end="2000-12-26", promote_recommended=True)
    assert sync_mod.next_calendar_change(xmas, date(2026, 10, 27)) == (date(2026, 11, 25), True)
    assert sync_mod.next_calendar_change(xmas, date(2026, 12, 1)) == (date(2026, 12, 26), False)
    once = CollectionConfig(name="O", sources=[Source(type="static", value="x")], promote_window=True,
                            promote_yearly=False, promote_start="2020-01-01", promote_end="2020-01-05")
    assert sync_mod.next_calendar_change(once, date(2026, 1, 1)) is None


def test_collection_curatarr_made_is_not_disowned():
    from datetime import date
    from app.sync import remove_off_season
    db.save_settings({"made_by_curatarr": "[]"})
    fake = FakePlex()
    fake.collection_title = "Lost Track"
    plex = plex_with(fake)
    cfg = CollectionConfig(name="Lost Track", library="Movies", sync_mode="sync",
                           sources=[Source(type="static", value="x")])
    made = sync_collection(cfg, {}, plex, SECTION, refs_for(1, 2), {})
    rk = made.state["plex_rating_key"]
    # Curatarr loses the key (e.g. the row was re-added): found by name, it's still Curatarr's
    again = sync_collection(cfg, {}, plex, SECTION, refs_for(1), {})
    assert again.state["plex_rating_key"] == rk and again.state["plex_owned"] == 1 and again.removed == 1
    # a row wrongly marked as someone else's is healed, so off season removes it
    gone = remove_off_season(_cal(seasonal_only=True, name="Lost Track"), {"plex_rating_key": rk, "plex_owned": 0},
                             plex, SECTION, today=date(2026, 11, 2))
    assert "removed from Plex" in gone.messages[0] and rk not in fake.collections


def test_collection_made_before_key_tracking_is_recognised_by_history():
    db.save_settings({"made_by_curatarr": "[]"})
    fake = FakePlex()
    fake.collections["100"] = ["1", "2", "3"]
    fake.collection_title = "Old Holiday"
    cfg = CollectionConfig(name="Old Holiday", library="Movies", sync_mode="sync", sources=[Source(type="static", value="x")])
    db.record_run({"collection_name": "Old Holiday", "status": "success", "message": "Created with 3 item(s): +3 / -0"})
    result = sync_collection(cfg, {"plex_rating_key": "100", "plex_owned": 0}, plex_with(fake), SECTION,
                             refs_for(1, 2), {})
    assert result.state["plex_owned"] == 1 and result.removed == 1


def test_dashboard_merges_coming_up_across_libraries():
    from datetime import date, timedelta
    from fastapi.testclient import TestClient
    from app.main import app
    start, end = date.today() + timedelta(days=3), date.today() + timedelta(days=9)
    for lib in ("Movies", "Movies 4K"):
        db.create_collection({"name": "Merge Day", "library": lib, "section_id": "1", "promote_home": True,
                              "promote_window": True, "promote_start": start.isoformat(),
                              "promote_end": end.isoformat(), "sources": [{"type": "static", "value": "tt1"}]})
    d = TestClient(app).get("/api/dashboard").json()
    merged = [c for c in d["coming"] if c["name"] == "Merge Day"]
    assert len(merged) == 1 and merged[0]["libraries"] == ["Movies", "Movies 4K"]


def test_dashboard_endpoint():
    from fastapi.testclient import TestClient
    from app.main import app
    cid = db.create_collection({"name": "Dash", "library": "Movies", "section_id": "1", "enabled": False,
                                "sources": [{"type": "static", "value": "tt0000001"}]})
    db.record_run({"collection_id": cid, "collection_name": "Dash", "status": "warning", "matched": 7,
                   "missing": [{"imdb": "tt1"}, {"imdb": "tt2"}]})
    db.update_collection_state(cid, last_status="warning", last_message="one source failed")
    d = TestClient(app).get("/api/dashboard").json()
    assert d["counts"]["titles"] >= 7 and d["counts"]["missing"] >= 2
    assert any(a["id"] == cid and a["status"] == "paused" for a in d["attention"])
    assert any(m["id"] == cid and m["missing"] == 2 for m in d["most_missing"])
    assert isinstance(d["recent"][0]["missing"], int)


def test_tmdb_poster_choices():
    from app.sources.tmdb import TMDB

    def handler(request):
        if request.url.path == "/3/collection/10/images":
            return httpx.Response(200, json={"posters": [{"file_path": "/a.jpg"}, {"file_path": "/b.jpg"}]})
        if request.url.path == "/3/search/collection":
            assert request.url.params["query"] == "Star Wars"
            return httpx.Response(200, json={"results": [{"id": 10, "name": "Star Wars", "poster_path": "/b.jpg"},
                                                         {"id": 11, "name": "Other", "poster_path": "/c.jpg"}]})
        return httpx.Response(404)
    tmdb = TMDB("k" * 32, httpx.Client(transport=httpx.MockTransport(handler)))
    choices = tmdb.poster_choices("Star Wars", [10])
    assert [c["url"].rsplit("/", 1)[1] for c in choices] == ["a.jpg", "b.jpg", "c.jpg"]
    assert choices[0]["thumb"].startswith("https://image.tmdb.org/t/p/w342/")
    assert [c["url"].rsplit("/", 1)[1] for c in tmdb.poster_choices("Star Wars")] == ["b.jpg", "c.jpg", "a.jpg"]


def test_custom_holidays(monkeypatch):
    from contextlib import nullcontext
    from fastapi.testclient import TestClient
    from app import api as api_mod, holidays, scheduler, sync as sync_mod
    from app.main import app

    monkeypatch.setattr(api_mod, "_plex", lambda: nullcontext(object()))
    monkeypatch.setattr(sync_mod, "resolve_section",
                        lambda plex, sid, lib: {"id": "1", "title": "Movies", "type": "movie"})
    monkeypatch.setattr(scheduler, "run_now", lambda *a, **k: None)
    client = TestClient(app)
    bad = client.post("/api/holidays/custom", json={"name": "Pi Day", "start": "3-14", "end": "03-14",
                                                     "link": "https://www.themoviedb.org/keyword/9840"})
    assert bad.status_code == 422
    r = client.post("/api/holidays/custom", json={"name": "Pi Day", "start": "03-10", "end": "03-14",
                                                   "link": "https://www.themoviedb.org/keyword/9840-pi/movie",
                                                   "scheme": "plum"})
    assert r.status_code == 201 and r.json()["key"] == "custom-pi-day"
    assert client.post("/api/holidays/custom", json={"name": "Pi Day", "start": "03-10", "end": "03-14",
                                                      "link": "https://www.themoviedb.org/keyword/9840"}).status_code == 422
    listed = {h["key"]: h for h in client.get("/api/holidays").json()}
    assert listed["custom-pi-day"]["custom"] and listed["custom-pi-day"]["available"]
    poster = client.get(listed["custom-pi-day"]["poster"])
    assert poster.status_code == 200 and poster.content[:2] == b"\xff\xd8"          # a JPEG

    made = client.post("/api/holidays/custom-pi-day/enable", json={"section_id": "1"}).json()
    assert made["config"]["holiday"] == "custom-pi-day" and made["config"]["pin_top"]
    assert made["config"]["sources"][0]["value"] == "movie?with_keywords=9840&sort_by=popularity.desc"
    client.put("/api/holidays/custom/custom-pi-day", json={"name": "Pi Day", "start": "03-01", "end": "03-14",
                                                           "link": "https://www.themoviedb.org/keyword/9840"})
    assert db.get_collection(made["id"])["config"]["promote_start"].endswith("-03-01")
    assert client.delete("/api/holidays/custom/custom-pi-day").json()["deleted"]
    assert db.get_collection(made["id"]) is None and not holidays.get("custom-pi-day")
    assert client.delete("/api/holidays/custom/christmas").status_code == 404


def test_pin_to_top_while_showing():
    from datetime import date
    from app import sync as sync_mod

    hubs = [{"identifier": "movie.recent"}, {"identifier": "custom.collection.1.100"}]
    moves = []

    def handler(request):
        if request.url.path.endswith("/manage/move"):
            moves.append(dict(request.url.params))
            ident = request.url.params["identifier"]
            hub = next(h for h in hubs if h["identifier"] == ident)
            hubs.remove(hub)
            after = request.url.params.get("after")
            hubs.insert(next(i for i, h in enumerate(hubs) if h["identifier"] == after) + 1 if after else 0, hub)
            return httpx.Response(200)
        return httpx.Response(200, json={"MediaContainer": {"Hub": hubs}})
    plex = Plex("http://plex", "token", client=httpx.Client(transport=httpx.MockTransport(handler)))
    cfg = CollectionConfig(name="X", sources=[Source(type="static", value="x")], promote_window=True,
                           promote_start="2000-12-01", promote_end="2000-12-26", promote_recommended=True,
                           pin_top=True)
    state = {}
    sync_mod.apply_pin(plex, "1", "100", cfg, date(2026, 12, 5), state)
    assert hubs[0]["identifier"] == "custom.collection.1.100" and state["hub_pinned"] == "movie.recent"
    sync_mod.apply_pin(plex, "1", "100", cfg, date(2026, 12, 6), state)       # already pinned: no move
    assert len(moves) == 1
    sync_mod.apply_pin(plex, "1", "100", cfg, date(2026, 12, 27), state)      # dates over: put back
    assert hubs[0]["identifier"] == "movie.recent" and state["hub_pinned"] is None


def test_arr_have_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    from app import arr as arr_mod
    from app.main import app

    monkeypatch.setattr(arr_mod.Arr, "configured", property(lambda self: self.kind == "radarr"))
    monkeypatch.setattr(arr_mod.Arr, "library_ids",
                        lambda self: {"tmdb": {"1760170"}, "imdb": {"tt0000002"}, "tvdb": set()})
    r = TestClient(app).post("/api/arr/have", json={"items": [
        {"tmdb": 1760170, "media_type": "movie"}, {"tmdb": 5, "media_type": "movie"},
        {"imdb": "tt0000002"}, {"tvdb": 7, "media_type": "show"}]})
    assert r.json() == {"have": [True, False, True, None]}      # Sonarr isn't set up


class FakeOverlayPlex(httpx.BaseTransport):
    """Posters for a two-title collection: uploads become the current poster."""

    def __init__(self):
        from app import overlays
        self.version = {"1": 1, "2": 1}
        self.posters = {rk: overlays.sample_poster() for rk in self.version}
        self.original = dict(self.posters)
        self.uploads: list[str] = []
        self.labels: dict[str, list[str]] = {"1": ["Kids"], "2": []}
        self.members = list(self.version)        # what's in collection 100

    def thumb(self, rk):
        return f"/library/metadata/{rk}/thumb/{self.version[rk]}"

    def handle_request(self, request):
        path, method, q = request.url.path, request.method, request.url.params
        mc = lambda body: httpx.Response(200, json={"MediaContainer": body})  # noqa: E731
        parts = path.strip("/").split("/")
        if path == "/library/collections/100/items":
            return mc({"totalSize": 2, "Metadata": [{"ratingKey": rk, "title": f"T{rk}", "type": "movie",
                                                     "thumb": self.thumb(rk), "audienceRating": 8.4 if rk == "1" else 6.1,
                                                     "audienceRatingImage": "imdb://image.rating",
                                                     "Media": [{"id": 50 + int(rk), "videoResolution": "4k"}]}
                                                    for rk in self.members]})
        if path.startswith("/library/metadata/") and "thumb" in parts:
            return httpx.Response(200, content=self.posters[parts[2]], headers={"content-type": "image/jpeg"})
        if path.endswith("/posters") and method == "POST":
            rk = parts[2]
            self.posters[rk] = request.content
            self.version[rk] += 1
            self.uploads.append(rk)
            return mc({})
        if len(parts) == 3 and parts[1] == "metadata":
            rk = parts[2]
            self.details = getattr(self, "details", 0) + 1
            return mc({"Metadata": [{"ratingKey": rk, "thumb": self.thumb(rk),
                                     "Label": [{"tag": t} for t in self.labels[rk]],
                                     "Media": [{"id": 50 + int(rk), "videoResolution": "4k", "Part": [{"Stream": [
                                         {"streamType": 1, "DOVIPresent": rk == "1", "colorTrc": "smpte2084"},
                                         {"streamType": 2, "displayTitle": "English (TrueHD Atmos 7.1)"}]}]}]}]})
        if path == "/library/sections/1/all" and method == "PUT":
            rk = q["id"]
            if "label[].tag.tag-" in q:
                self.labels[rk] = [t for t in self.labels[rk] if t != q["label[].tag.tag-"]]
            else:
                self.labels[rk] = [v for k, v in q.items() if k.startswith("label[")]
            return mc({})
        return mc({})


def test_overlays_draw_skip_redraw_and_restore(monkeypatch):
    from app import overlays, plex as plexmod
    for row in db.list_collections():           # earlier tests' collections aren't part of this
        db.delete_collection(row["id"])
    fake = FakeOverlayPlex()
    monkeypatch.setattr(plexmod, "from_settings", lambda *a, **k: Plex("http://plex", "t", client=httpx.Client(transport=fake)))
    cfg = CollectionConfig(name="Best", library="Movies", section_id="1", sources=[Source(type="static", value="x")],
                           ribbon={"enabled": True, "text": "TOP 250"})
    cid = db.create_collection(cfg.model_dump())
    db.update_collection_state(cid, plex_rating_key="100")

    assert overlays.needed()
    assert overlays.apply_all()["drawn"] == 2
    assert fake.posters["1"] != fake.original["1"] and overlays._original_path("1").read_bytes() == fake.original["1"]
    assert fake.labels["1"] == ["Kids", overlays.LABEL]                    # other labels kept
    assert overlays.apply_all() == {"drawn": 0, "restored": 0, "unchanged": 2, "nothing": 0, "errors": 0}

    cfg.ribbon.text = "BEST"                                              # a change redraws both
    db.update_collection_config(cid, cfg.model_dump())
    assert overlays.apply_all()["drawn"] == 2
    assert overlays._original_path("1").read_bytes() == fake.original["1"]     # still the real original

    fake.posters["2"] = overlays.render(fake.original["2"], [])            # Plex replaces item 2's poster
    fake.version["2"] += 1
    replaced = fake.posters["2"]
    assert overlays.apply_all()["drawn"] == 1
    assert overlays._original_path("2").read_bytes() == replaced           # that is the new original

    cfg.ribbon.enabled = False
    db.update_collection_config(cid, cfg.model_dump())
    assert overlays.apply_all()["restored"] == 2
    assert fake.posters["1"] == fake.original["1"] and fake.posters["2"] == replaced
    assert db.overlay_rows() == {} and fake.labels["1"] == ["Kids"]
    assert not overlays.needed()


def test_quality_and_rating_badges(monkeypatch):
    from app import overlays, plex as plexmod
    detail = {"Media": [
        {"id": 1, "videoResolution": "1080", "Part": [{"Stream": [{"streamType": 1}]}]},
        {"id": 2, "videoResolution": "4k", "Part": [{"Stream": [
            {"streamType": 1, "colorTrc": "smpte2084", "displayTitle": "4K HDR10"},
            {"streamType": 2, "displayTitle": "English (EAC3 Atmos 5.1)"}]}]}]}
    assert overlays.quality_labels(detail) == ["4K", "HDR"]  + ["ATMOS"]
    assert overlays.quality_labels({"Media": [{"videoResolution": "720"}]}) == ["720P"]
    rt = {"rating": 9.1, "ratingImage": "rottentomatoes://image.rating.ripe"}
    assert overlays.rating_badge(rt, "critic") == {"source": "rottentomatoes", "value": "91%"}
    assert overlays.rating_badge({"audienceRating": 6.1, "audienceRatingImage": "imdb://image.rating"},
                                 "audience", 7) is None
    drawn = overlays.render(overlays.sample_poster(), [{"kind": "badges", "quality": ["4K", "DV"],
                                                        "rating": {"source": "imdb", "value": "8.4"}}])
    assert drawn.startswith(bytes([0xFF, 0xD8]))          # a JPEG

    for row in db.list_collections():
        db.delete_collection(row["id"])
    fake = FakeOverlayPlex()
    monkeypatch.setattr(plexmod, "from_settings", lambda *a, **k: Plex("http://plex", "t", client=httpx.Client(transport=fake)))
    cfg = CollectionConfig(name="Top", library="Movies", section_id="1", sources=[Source(type="static", value="x")],
                           badges={"quality": True, "rating": "audience", "rating_min": 7})
    cid = db.create_collection(cfg.model_dump())
    db.update_collection_state(cid, plex_rating_key="100")
    first = overlays.apply_all()
    assert first["drawn"] == 2, first
    rows = db.overlay_rows()
    assert json.loads(rows["1"]["media"]) == ["4K", "DV", "ATMOS"] and json.loads(rows["2"]["media"]) == ["4K", "HDR", "ATMOS"]
    fake.details = 0
    assert overlays.apply_all()["unchanged"] == 2 and fake.details == 0      # cached: no detail calls
    cfg.badges.quality, cfg.badges.rating = False, ""
    db.update_collection_config(cid, cfg.model_dump())
    assert overlays.apply_all()["restored"] == 2 and db.overlay_rows() == {}


def test_planned_contents_for_off_season_collection(monkeypatch):
    from app import plex as plexmod, sync as sync_mod
    sync_mod.clear_index_cache()
    fake = FakePlex()
    monkeypatch.setattr(plexmod, "from_settings", lambda *a, **k: plex_with(fake))
    monkeypatch.setattr(sync_mod, "resolve_sections", lambda plex, cfg: [SECTION])
    cid = db.create_collection({"name": "Xmas", "library": "Movies", "section_id": "1",
                                "sources": [{"type": "static", "value": "tt0000003, tt0000001, tt0000002, tt0000009"}],
                                "exclude": [{"id": "plex:2"}], "promote_window": True, "seasonal_only": True,
                                "promote_start": "2000-11-25", "promote_end": "2000-12-26",
                                "promote_recommended": True})
    planned = sync_mod.planned_contents(cid)
    assert [(i["ratingKey"], i["title"]) for i in planned["items"]] == [("3", "T3"), ("1", "T1")]
    assert planned["missing"] == 1 and not fake.collections          # nothing was created in Plex


def test_rating_badge_falls_back_to_detail_metadata():
    from app import overlays

    def handler(request):
        return httpx.Response(200, json={"MediaContainer": {"Metadata": [
            {"ratingKey": "7", "audienceRating": 8.8, "audienceRatingImage": "imdb://image.rating"}]}})
    plex = Plex("http://plex", "t", client=httpx.Client(transport=httpx.MockTransport(handler)))
    entry = {"ribbons": [], "badges": {"quality": False, "rating": "audience", "rating_min": 0},
             "item": {"ratingKey": "7", "title": "Inception"}, "type": "movie"}
    specs, _, _ = overlays._specs(plex, "7", entry, None)
    assert specs == [{"kind": "badges", "quality": [], "rating": {"source": "imdb", "value": "8.8"}, "size": "medium"}]


def test_ribbons_in_every_corner():
    from app import overlays
    from app.models import Ribbon
    for corner in ("top-right", "top-left", "bottom-right", "bottom-left"):
        Ribbon(enabled=True, text="X", corner=corner)
        out = overlays.render(overlays.sample_poster(), [
            {"kind": "ribbon", "text": "TOP 250", "color": "#f5c518", "text_color": "#000000", "corner": corner},
            {"kind": "badges", "quality": ["4K", "DV", "ATMOS"], "rating": {"source": "imdb", "value": "8.4"}}])
        assert out.startswith(bytes([0xFF, 0xD8]))
    with pytest.raises(ValueError):
        Ribbon(corner="middle")


class FakePosterPlex(httpx.BaseTransport):
    """A library of three movies with different poster choices."""

    def __init__(self):
        self.posters = {
            "1": [{"ratingKey": "upload://posters/abc", "key": "/library/metadata/1/file?url=upload", "selected": 1},
                  {"ratingKey": "metadata://posters/frame", "key": "https://image.tmdb.org/t/p/original/wide.jpg",
                   "provider": "tmdb", "selected": 0},          # a video frame offered as a poster: skipped
                  {"ratingKey": "metadata://posters/tmdb_1", "key": "https://image.tmdb.org/t/p/original/one.jpg",
                   "thumb": "https://image.tmdb.org/t/p/w300/one.jpg", "provider": "tmdb", "selected": 0}],
            "2": [{"ratingKey": "metadata://posters/tmdb_2", "key": "https://image.tmdb.org/t/p/original/two.jpg",
                   "provider": "tmdb", "selected": True}],
            "3": [{"ratingKey": "media://local", "key": "/library/metadata/3/file?url=local", "provider": "local",
                   "selected": True}],
        }
        self.selected: dict[str, str] = {}

    def handle_request(self, request):
        path, method, q = request.url.path, request.method, request.url.params
        mc = lambda body: httpx.Response(200, json={"MediaContainer": body})  # noqa: E731
        if request.url.host == "image.tmdb.org":          # wide.jpg is landscape, the rest are posters
            import io
            from PIL import Image
            out = io.BytesIO()
            Image.new("RGB", (300, 169) if "wide" in path else (200, 300)).save(out, "JPEG")
            return httpx.Response(200, content=out.getvalue(), headers={"content-type": "image/jpeg"})
        if path == "/library/sections":
            return mc({"Directory": [{"key": "1", "title": "Movies", "type": "movie"}]})
        if path == "/library/sections/1/all":
            return mc({"totalSize": 3, "Metadata": [{"ratingKey": rk, "title": f"T{rk}", "thumb": f"/library/metadata/{rk}/thumb/1"}
                                                    for rk in self.posters]})
        parts = path.strip("/").split("/")
        if path.endswith("/posters") and method == "GET":
            return mc({"Metadata": self.posters[parts[2]]})
        if path.endswith("/poster") and method == "PUT":
            self.selected[parts[2]] = q["url"]
            return mc({})
        return mc({})


def test_napalm_refreshes_posters(monkeypatch):
    from app import napalm, plex as plexmod, sync as sync_mod
    fake = FakePosterPlex()
    monkeypatch.setattr(plexmod, "from_settings", lambda *a, **k: Plex("http://plex", "t", client=httpx.Client(transport=fake)))
    monkeypatch.setattr(sync_mod, "run_overlays", lambda *a: None)
    plex = Plex("http://plex", "t", client=httpx.Client(transport=fake))
    assert Plex.fresh_poster(fake.posters["1"])["ratingKey"] == "metadata://posters/frame"   # first from a source
    assert plex.fresh_choice("1")["ratingKey"] == "metadata://posters/tmdb_1"               # first poster-shaped one
    assert Plex.fresh_poster(fake.posters["3"]) is None
    assert napalm.counts(["1"]) == [{"id": "1", "title": "Movies", "type": "movie", "agent": None, "count": 3}]
    result = napalm.run(["1"])
    assert fake.selected == {"1": "metadata://posters/tmdb_1"}                  # only the one that needed it
    assert (result["changed"], result["unchanged"], result["no_poster"], result["errors"]) == (1, 1, 1, 0)
    assert not napalm.progress["running"] and result["done"] == 3

    sync_mod.clear_index_cache()
    fake.selected.clear()
    fake.posters["1"][0]["selected"], fake.posters["1"][2]["selected"] = 1, 0
    ordered = napalm.preview(["1"])
    assert ordered[0]["ratingKey"] == "1" and ordered[0]["status"] == "changes"     # changes come first
    assert len(napalm.preview(["1"], count=1)) == 1
    sample = {s["ratingKey"]: s for s in ordered}
    assert sample["1"]["status"] == "changes" and sample["1"]["fresh"] == "https://image.tmdb.org/t/p/w300/one.jpg"
    assert sample["1"]["current"].startswith("/api/plex/image?path=")
    assert sample["2"]["status"] == "already using it" and "no poster" in sample["3"]["status"]
    with pytest.raises(PlexError):
        napalm.preview(["99"])


def test_napalm_endpoint_needs_confirmation():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    assert client.post("/api/napalm/run", json={"section_ids": ["1"]}).status_code == 422
    assert client.post("/api/napalm/run", json={"confirm": "napalm"}).status_code == 422


def test_content_rating_badge_and_fresh_spec():
    from app import overlays
    assert overlays.content_rating_label("gb/12A") == "12A" and overlays.content_rating_label("PG-13") == "PG-13"
    entry = {"ribbons": [], "fresh": True, "type": "movie",
             "badges": {"quality": False, "content_rating": True, "rating": "", "rating_min": 0},
             "item": {"ratingKey": "5", "contentRating": "TV-MA"}}
    specs, _, _ = overlays._specs(None, "5", entry, None)
    assert specs == [{"kind": "fresh"}, {"kind": "badges", "quality": [], "rating": None, "size": "medium",
                                         "content_rating": "TV-MA"}]
    drawn = overlays.render(overlays.sample_poster(), specs)
    assert drawn.startswith(bytes([0xFF, 0xD8]))


def test_ribbon_sizes_and_fonts():
    from app import overlays
    from app.models import Ribbon
    fonts = {f["key"] for f in overlays.available_fonts()}
    assert "sans" in fonts
    for size in ("small", "medium", "large", "xlarge"):
        Ribbon(size=size)
        out = overlays.render(overlays.sample_poster(), [{"kind": "ribbon", "text": "IMDb TOP 250", "color": "#f5c518",
                                                          "text_color": "#000000", "corner": "top-left", "size": size,
                                                          "font": "lato"}])      # falls back when not installed
        assert out.startswith(bytes([0xFF, 0xD8]))
    with pytest.raises(ValueError):
        Ribbon(font="comic-sans")


def test_napalm_turns_off_overlays_and_keeps_fresh_posters(monkeypatch):
    from app import napalm, overlays, plex as plexmod, sync as sync_mod
    for row in db.list_collections():
        db.delete_collection(row["id"])
    fake = FakePosterPlex()
    monkeypatch.setattr(plexmod, "from_settings", lambda *a, **k: Plex("http://plex", "t", client=httpx.Client(transport=fake)))
    monkeypatch.setattr(sync_mod, "run_overlays", lambda *a: None)
    cid = db.create_collection({"name": "Halloween Collection", "library": "Movies", "section_id": "1",
                                "sources": [{"type": "static", "value": "tt1"}], "ribbon": {"enabled": True, "text": "BOO"},
                                "badges": {"quality": True, "rating": "audience"}})
    other = db.create_collection({"name": "Elsewhere", "library": "TV", "section_id": "2",
                                  "sources": [{"type": "static", "value": "tt1"}], "ribbon": {"enabled": True}})
    assert [c["id"] for c in napalm.affected(["1"])] == [cid]
    overlays.ORIGINALS.mkdir(parents=True, exist_ok=True)
    for rk in ("1", "3"):
        overlays._original_path(rk).write_bytes(b"old")
        db.save_overlay(rk, "1", "movie", "sig", f"/library/metadata/{rk}/thumb/9")

    result = napalm.run(["1"])
    assert [c["name"] for c in result["overlays_off"]] == ["Halloween Collection"]
    cfg = db.get_collection(cid)["config"]
    assert not cfg["ribbon"]["enabled"] and not cfg["badges"]["quality"] and cfg["badges"]["rating"] == ""
    assert db.get_collection(other)["config"]["ribbon"]["enabled"]          # other libraries are left alone
    rows = db.overlay_rows()
    assert "1" not in rows and not overlays._original_path("1").exists()    # refreshed: the fresh poster stays
    assert "3" in rows                  # no source poster: left for the overlay pass to restore its original
    db.delete_overlay("3")
    overlays._original_path("3").unlink(missing_ok=True)


class FakeLibraryOverlayPlex(FakeOverlayPlex):
    """FakeOverlayPlex plus a Movies library listing with content ratings."""

    def handle_request(self, request):
        path, method = request.url.path, request.method
        mc = lambda body: httpx.Response(200, json={"MediaContainer": body})  # noqa: E731
        if path == "/library/sections":
            return mc({"Directory": [{"key": "1", "title": "Movies", "type": "movie"}]})
        if path == "/library/sections/1/all" and method == "GET":
            return mc({"totalSize": 2, "Metadata": [{"ratingKey": rk, "title": f"T{rk}", "type": "movie",
                                                     "contentRating": "PG-13" if rk == "1" else "R",
                                                     "thumb": self.thumb(rk)} for rk in self.version]})
        return super().handle_request(request)


def test_library_wide_badges(monkeypatch):
    from app import overlays, plex as plexmod
    for row in db.list_collections():
        db.delete_collection(row["id"])
    fake = FakeLibraryOverlayPlex()
    monkeypatch.setattr(plexmod, "from_settings", lambda *a, **k: Plex("http://plex", "t", client=httpx.Client(transport=fake)))
    assert not overlays.needed()
    overlays.save_library_settings({"1": {"content_rating": True}, "9": {}})
    assert overlays.library_settings() == {"1": {"size": "medium", "quality": False, "content_rating": True,
                                                 "tv_icon": False, "icon_style": "white", "rating": "", "rating_min": 0}}
    assert overlays.apply_all()["drawn"] == 2
    assert fake.posters["1"] != fake.original["1"] and len(db.overlay_rows()) == 2

    # A collection with a ribbon on title 1: combined with the library badge, one redraw.
    cid = db.create_collection({"name": "Mix", "library": "Movies", "section_id": "1",
                                "sources": [{"type": "static", "value": "x"}], "ribbon": {"enabled": True, "text": "MIX"}})
    db.update_collection_state(cid, plex_rating_key="100")
    assert overlays.apply_all()["drawn"] == 2          # the fake collection holds both titles

    db.delete_collection(cid)
    overlays.save_library_settings({})
    assert overlays.apply_all()["restored"] == 2
    assert fake.posters["1"] == fake.original["1"] and db.overlay_rows() == {}


def test_unmatched_titles_and_keep_label(monkeypatch):
    from app import napalm, plex as plexmod, sync as sync_mod, unmatched

    assert unmatched.classify({"guid": "local://123"}) == "unmatched"
    assert unmatched.classify({"guid": "com.plexapp.agents.none://abc"}) == "unmatched"
    assert unmatched.classify({"guid": "plex://movie/5d77", "Guid": []}) == "no_ids"
    assert unmatched.classify({"guid": "plex://movie/5d77", "Guid": [{"id": "tmdb://11"}]}) is None
    assert unmatched.classify({"guid": "com.plexapp.agents.imdb://tt0076759?lang=en"}) is None

    class Fake(FakePosterPlex):
        labels: dict = {}

        def handle_request(self, request):
            path, method, q = request.url.path, request.method, request.url.params
            mc = lambda body: httpx.Response(200, json={"MediaContainer": body})  # noqa: E731
            if path == "/library/sections/1/label":
                return mc({"Directory": [{"key": "77", "title": unmatched.KEEP_LABEL}, {"key": "88", "title": "FanEdit"},
                                         {"key": "99", "title": "Family"}]})
            if path == "/library/sections/1/all" and method == "GET" and q.get("label") == "77":
                return mc({"totalSize": 1, "Metadata": [{"ratingKey": "1"}]})
            if path == "/library/sections/1/all" and method == "GET" and q.get("label") == "88":
                return mc({"totalSize": 1, "Metadata": [{"ratingKey": "3"}]})
            if path == "/library/sections/1/all" and method == "GET":
                return mc({"totalSize": 3, "Metadata": [
                    {"ratingKey": "1", "title": "Ahsoka: The Patterson Cut", "guid": "local://1",
                     "Media": [{"Part": [{"file": "/movies/Fan Edits/Ahsoka (2024).mkv"}]}]},
                    {"ratingKey": "2", "title": "Odd Match", "guid": "plex://movie/x", "Guid": []},
                    {"ratingKey": "3", "title": "Normal", "guid": "plex://movie/y", "Guid": [{"id": "imdb://tt1"}]}]})
            if path == "/library/sections/1/all" and method == "PUT":
                self.labels[q["id"]] = dict(q)
                return mc({})
            return super().handle_request(request)

    fake = Fake()
    monkeypatch.setattr(plexmod, "from_settings", lambda *a, **k: Plex("http://plex", "t", client=httpx.Client(transport=fake)))
    monkeypatch.setattr(sync_mod, "run_overlays", lambda *a: None)
    result = unmatched.scan(refresh=True)
    found = {t["ratingKey"]: t for t in result["titles"]}
    assert set(found) == {"1", "2", "3"} and found["1"]["kind"] == "unmatched" and found["2"]["kind"] == "no_ids"
    assert found["3"]["kind"] == "matched" and found["3"]["fan_edit"] and not found["1"]["fan_edit"]
    assert all(unmatched.is_fan_edit_label(n) for n in ("Fan Edit", "FanEdit", "fan-edit", "Fan Edits", "FAN_EDIT"))
    assert not unmatched.is_fan_edit_label("Fanatic Edition")
    assert found["1"]["file"] == "Ahsoka (2024).mkv" and found["1"]["keep"] and not found["2"]["keep"]
    assert result["libraries"] == [{"id": "1", "title": "Movies", "type": "movie", "total": 3, "found": 3}]

    unmatched.set_keep([{"ratingKey": "2", "section_id": "1", "type": "movie"}], True)
    assert fake.labels["2"]["label[0].tag.tag"] == unmatched.KEEP_LABEL

    # Napalm leaves the kept title (1) alone, even though it has a fresh poster waiting.
    progress = napalm.run(["1"])
    assert "1" not in fake.selected and progress["kept"] == 1


def test_upload_title_poster(monkeypatch):
    from contextlib import nullcontext
    from fastapi.testclient import TestClient
    from app import api as api_mod, overlays, unmatched
    from app.main import app

    fake = FakeOverlayPlex()
    monkeypatch.setattr(api_mod, "_plex", lambda: nullcontext(Plex("http://plex", "t", client=httpx.Client(transport=fake))))
    client = TestClient(app)
    image = overlays.sample_poster()
    r = client.post("/api/titles/1/poster", files={"file": ("p.jpg", image, "image/jpeg")},
                    data={"keep": "true", "section_id": "1", "type": "movie"})
    assert r.status_code == 200 and r.json()["keep"] and r.json()["thumb"] == "/library/metadata/1/thumb/2"
    assert fake.posters["1"] == image and unmatched.KEEP_LABEL in fake.labels["1"]
    r = client.post("/api/titles/2/poster", data={"url": "https://example.com/p.jpg", "keep": "false", "section_id": "1"})
    assert r.status_code == 200 and not r.json()["keep"] and unmatched.KEEP_LABEL not in fake.labels["2"]
    assert client.post("/api/titles/1/poster", files={"file": ("p.gif", b"GIF89a", "image/gif")}).status_code == 415
    assert client.post("/api/titles/1/poster", data={"url": "ftp://x"}).status_code == 422


class FakePrerollPlex(httpx.BaseTransport):
    """A PreRolls library of three clips and the server's preroll setting."""

    def __init__(self, current=""):
        self.pref = current
        self.puts: list[str] = []

    def handle_request(self, request):
        path, method, q = request.url.path, request.method, request.url.params
        mc = lambda body: httpx.Response(200, json={"MediaContainer": body})  # noqa: E731
        if path == "/library/sections":
            return mc({"Directory": [{"key": "1", "title": "Movies", "type": "movie"},
                                     {"key": "5", "title": "PreRolls", "type": "movie"}]})
        if path == "/library/sections/5/all":
            return mc({"totalSize": 3, "Metadata": [
                {"ratingKey": str(n), "title": name, "duration": 15000,
                 "Media": [{"Part": [{"file": f"/data/prerolls/{name}.mp4"}]}]}
                for n, name in ((51, "Classic"), (52, "Pumpkin"), (53, "Snow"))]})
        if path == "/:/prefs" and method == "GET":
            return mc({"Setting": [{"id": "FriendlyName", "value": "PhillFlix"},
                                   {"id": "CinemaTrailersPrerollID", "value": self.pref}]})
        if path == "/:/prefs" and method == "PUT":
            self.pref = q["CinemaTrailersPrerollID"]
            self.puts.append(self.pref)
            return mc({})
        return mc({})


def test_preroll_manager(monkeypatch):
    from datetime import date
    from app import plex as plexmod, prerolls

    db.save_settings({"prerolls": ""})
    fake = FakePrerollPlex("/data/prerolls/Classic.mp4,/data/prerolls/Old.mp4")
    monkeypatch.setattr(plexmod, "from_settings", lambda *a, **k: Plex("http://plex", "t", client=httpx.Client(transport=fake)))
    view = prerolls.overview()
    assert view["settings"]["section_id"] == "5"                      # found "PreRolls" by name
    assert [c["title"] for c in view["clips"]] == ["Classic", "Pumpkin", "Snow"]
    assert view["current"]["matched"] == ["51"] and view["current"]["unmatched"] == ["/data/prerolls/Old.mp4"]
    assert view["current"]["mode"] == "sequence"                      # commas: all, in order
    assert view["settings"]["default"] == ["51"] and view["settings"]["mode"] == "sequence"   # taken from Plex
    assert view["from_plex"]

    with pytest.raises(prerolls.PrerollError):
        prerolls.save({"sets": [{"name": "Bad", "start": "13-01", "end": "10-31", "items": []}]})
    prerolls.save({"enabled": True, "section_id": "5", "mode": "random", "default": ["51", "53"],
                   "sets": [{"name": "Halloween", "start": "10-01", "end": "10-31", "items": ["52"]}]})
    assert prerolls.apply(date(2026, 6, 1))["set"] == "Default"
    assert fake.pref == "/data/prerolls/Classic.mp4;/data/prerolls/Snow.mp4"
    assert prerolls.load()["backup"] == "/data/prerolls/Classic.mp4,/data/prerolls/Old.mp4"   # the original, kept
    prerolls.apply(date(2026, 10, 5))
    assert fake.pref == "/data/prerolls/Pumpkin.mp4"
    assert prerolls.next_change(prerolls.load(), date(2026, 10, 5)) == {"date": "2026-11-01", "set": "Default"}

    prerolls.save({"mode": "sequence"})
    prerolls.apply(date(2026, 6, 1))
    assert fake.pref == "/data/prerolls/Classic.mp4,/data/prerolls/Snow.mp4"
    prerolls.save({"mode": "daily", "daily_count": 1})
    prerolls.apply(date(2026, 6, 1))
    first = fake.pref
    prerolls.apply(date(2026, 6, 1))
    assert fake.pref == first and "," not in first                        # one clip, the same all day

    prerolls.restore()
    assert fake.pref == "/data/prerolls/Classic.mp4,/data/prerolls/Old.mp4" and not prerolls.load()["enabled"]
    assert prerolls.parse_value("a;b") == (["a", "b"], "random")
    assert prerolls.parse_value("a,b") == (["a", "b"], "sequence")
    assert not prerolls.overview()["from_plex"]                         # set up already: nothing taken
    assert prerolls.build_value({"mode": "random"}, []) == ""
    db.save_settings({"prerolls": ""})



def test_badge_sizes_merge_to_the_largest():
    from app import overlays
    entry = {"badges": None}
    overlays._merge_badges(entry, {"quality": True, "content_rating": False, "rating": "", "rating_min": 0, "size": "small"})
    overlays._merge_badges(entry, {"quality": False, "content_rating": True, "rating": "", "rating_min": 0, "size": "large"})
    assert entry["badges"]["size"] == "large" and entry["badges"]["quality"] and entry["badges"]["content_rating"]
    for size in overlays.BADGE_SIZES:
        out = overlays.render(overlays.sample_poster(), [{"kind": "badges", "quality": ["4K", "DV"], "content_rating": "R",
                                                          "rating": {"source": "rottentomatoes", "value": "63%"}, "size": size}])
        assert out.startswith(bytes([0xFF, 0xD8]))


def test_list_overlay(monkeypatch):
    from app import overlays, plex as plexmod, sync as sync_mod

    # Sync finds the list's titles in the library; nothing is created in Plex.
    sync_mod.clear_index_cache()
    fake = FakePlex()
    cfg = CollectionConfig(name="Oscar Best Picture", kind="overlay", library="Movies", section_id="1",
                           sources=[Source(type="static", value="x")], ribbon={"enabled": True, "text": "OSCAR"},
                           promote_home=True)
    assert not cfg.promote_home                                         # no home screen for list overlays
    result = sync_mod.sync_overlay_list(cfg, ["1", "4"], plex_with(fake), [SECTION], refs_for(1, 2, 9))
    assert result.state["members"] == ["1", "2"] and (result.added, result.removed) == (1, 1)
    assert not fake.collections and len(result.missing) == 1

    # The overlay pass draws on the stored titles, fetched in one batch.
    for row in db.list_collections():
        db.delete_collection(row["id"])

    class Batch(FakeOverlayPlex):
        def handle_request(self, request):
            parts = request.url.path.strip("/").split("/")
            if len(parts) == 3 and parts[1] == "metadata" and "," in parts[2]:
                return httpx.Response(200, json={"MediaContainer": {"Metadata": [
                    {"ratingKey": rk, "title": f"T{rk}", "type": "movie", "thumb": self.thumb(rk)}
                    for rk in parts[2].split(",") if rk in self.version]}})
            return super().handle_request(request)

    oplex = Batch()
    monkeypatch.setattr(plexmod, "from_settings", lambda *a, **k: Plex("http://plex", "t", client=httpx.Client(transport=oplex)))
    cid = db.create_collection(cfg.model_dump())
    db.update_collection_state(cid, members=["1", "2", "77"])
    assert db.get_collection(cid)["members"] == ["1", "2", "77"]
    assert overlays.apply_all()["drawn"] == 2 and set(db.overlay_rows()) == {"1", "2"}
    db.update_collection_state(cid, members=["1"])                      # title 2 left the list
    assert overlays.apply_all()["restored"] == 1 and set(db.overlay_rows()) == {"1"}
    db.delete_collection(cid)
    overlays.apply_all()
    assert db.overlay_rows() == {}


def test_primary_libraries_come_first():
    from app import api as api_mod
    libs = [{"id": "1", "title": "Movies", "type": "movie"}, {"id": "2", "title": "TV", "type": "show"},
            {"id": "3", "title": "Movies 4K", "type": "movie"}, {"id": "4", "title": "Kids TV", "type": "show"}]
    db.save_settings({"primary_movie_library": "3", "primary_tv_library": "4"})
    ordered = api_mod._primary_first(libs)
    assert [s["id"] for s in ordered] == ["3", "4", "1", "2"] and ordered[0]["primary"] and not ordered[2]["primary"]
    db.save_settings({"primary_movie_library": "", "primary_tv_library": ""})
    assert [s["id"] for s in api_mod._primary_first(libs)] == ["1", "2", "3", "4"]


def test_arr_root_folder_per_library():
    import time
    from app import arr as arr_mod, sync as sync_mod
    settings = {"radarr_url": "http://r", "radarr_api_key": "k", "radarr_root_folder": "/movies",
                "radarr_quality_profile": "1"}

    def radarr(request):
        if request.url.path == "/api/v3/rootfolder":
            return httpx.Response(200, json=[{"path": "/movies"}, {"path": "/Movies_Special/"}])
        if request.url.path == "/api/v3/movie":
            return httpx.Response(200, json=[
                {"tmdbId": 1, "imdbId": "tt0133093", "rootFolderPath": "/Movies_Special/"},
                {"tmdbId": 2, "path": "/Movies_Special/Heat (1995)"},          # no rootFolderPath: from its path
                {"tmdbId": 3, "rootFolderPath": "/movies"},
                {"tmdbId": 9, "rootFolderPath": "/movies"}])                   # not in this library
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(radarr)) as http:
        items = arr_mod.Arr("radarr", settings, http).item_folders()
        found = arr_mod.detect_folder(items, {("tmdb", "1"), ("tmdb", "2"), ("tmdb", "3")})
        assert found == {"folder": "/Movies_Special/", "matched": 2, "total": 3}
        assert arr_mod.detect_folder(items, {("tmdb", "77")})["folder"] == ""
        assert arr_mod.Arr("radarr", settings, http, "/Movies_Special/").root_folder == "/Movies_Special/"
        assert arr_mod.Arr("radarr", settings, http).root_folder == "/movies"

        # A folder chosen in Settings wins over the one found from Radarr's data
        sync_mod._folder_cache[("radarr", "7")] = (time.monotonic(), found)
        section = {"id": "7", "title": "MoviesSpecial", "type": "movie"}
        assert sync_mod.arr_root_folder("radarr", settings, http, None, section) == "/Movies_Special/"
        chosen = {**settings, "radarr_library_folders": '{"7": "/movies"}'}
        assert sync_mod.arr_root_folder("radarr", chosen, http, None, section) == "/movies"
        assert sync_mod.arr_root_folder("radarr", settings, http, None, None) == ""
        sync_mod._folder_cache.clear()


def test_rogue_filenames_scan(monkeypatch):
    from app import naming

    def radarr(request):
        path, q = request.url.path, request.url.params
        if path == "/api/v3/config/naming":
            return httpx.Response(200, json={"renameMovies": True, "standardMovieFormat": "{Movie Title} ({Release Year})"})
        if path == "/api/v3/movie":
            return httpx.Response(200, json=[{"id": 1, "title": "Heat", "year": 1995, "hasFile": True, "path": "/m/Heat"},
                                             {"id": 2, "title": "Alien", "year": 1979, "hasFile": True, "path": "/m/Alien"},
                                             {"id": 3, "title": "Wanted", "hasFile": False}])
        if path == "/api/v3/rename":
            assert q["movieId"] in ("1", "2")
            return httpx.Response(200, json=[{"existingPath": "heat.1995.mkv", "newPath": "Heat (1995).mkv"}]
                                  if q["movieId"] == "1" else [])
        return httpx.Response(404)

    real_client = httpx.Client
    monkeypatch.setattr(naming.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(radarr)))
    db.save_settings({"radarr_url": "http://r", "radarr_api_key": "k", "sonarr_url": "", "naming_scan": ""})
    result = naming.scan()
    s = result["services"]["radarr"]
    assert "sonarr" not in result["services"]
    assert s["checked"] == 2 and s["formats"]["standardMovieFormat"] == "{Movie Title} ({Release Year})"
    assert [i["title"] for i in s["items"]] == ["Heat"]
    assert s["items"][0]["files"][0]["existing"] == "heat.1995.mkv" and s["items"][0]["files"][0]["new"] == "Heat (1995).mkv"
    assert naming.last()["services"]["radarr"]["items"][0]["id"] == 1 and not naming.progress["running"]
    db.save_settings({"radarr_url": "", "radarr_api_key": "", "naming_scan": ""})


def test_sonarr_finds_show_without_tvdb_link_on_tmdb():
    from app import arr as arr_mod
    from app.sources import MediaRef
    added = {}

    def sonarr(request):
        path, term = request.url.path, request.url.params.get("term", "")
        if path == "/api/v3/series/lookup":
            if term == "tmdb:303726":                      # old Sonarr: a name search, no tmdbId
                return httpx.Response(200, json=[{"title": "Quokka", "tvdbId": 1}])
            if term == "Quokka's Wild Life":
                return httpx.Response(200, json=[{"title": "Quokka's Wild Life (Other)", "tvdbId": 2, "tmdbId": 999},
                                                 {"title": "Quokka's Wild Life", "tvdbId": 455000, "tmdbId": 303726}])
            return httpx.Response(200, json=[])
        if path == "/api/v3/series" and request.method == "POST":
            added.update(json.loads(request.content))
            return httpx.Response(201, json={})
        return httpx.Response(404)

    settings = {"sonarr_url": "http://s", "sonarr_api_key": "k", "sonarr_root_folder": "/tv",
                "sonarr_quality_profile": "1", "tmdb_api_key": ""}      # no TMDB key: no TVDB id from TMDB
    with httpx.Client(transport=httpx.MockTransport(sonarr)) as http:
        client = arr_mod.Arr("sonarr", settings, http)
        ref = MediaRef(media_type="show", title="Quokka's Wild Life", year=2025, tmdb=303726)
        assert client.add(ref) == "added" and added["tvdbId"] == 455000
        assert client.add(MediaRef(media_type="show", title="Nothing", tmdb=1)) == "not_found"


def test_dashboard_rogue_filenames_count():
    from fastapi.testclient import TestClient
    from app.main import app
    db.save_settings({"naming_scan": ""})
    assert TestClient(app).get("/api/dashboard").json()["rogue"] is None          # no scan yet
    db.save_settings({"naming_scan": json.dumps({"finished": "2026-11-02T10:00:00+00:00", "services": {
        "radarr": {"items": [{"files": [{}, {}]}, {"files": [{}]}]},
        "sonarr": {"items": [{"files": [{}] * 9}]},
        "broken": {"error": "unreachable", "items": []}}})})
    rogue = TestClient(app).get("/api/dashboard").json()["rogue"]
    assert rogue["files"] == 12 and rogue["titles"] == 3
    assert rogue["services"]["radarr"] == {"titles": 2, "files": 3} and "broken" not in rogue["services"]
    db.save_settings({"naming_scan": ""})


def test_source_link_detection():
    from app.sources import detect
    assert detect("https://www.themoviedb.org/company/165435-angel-studios")["type"] == "tmdb_list"
    assert detect("https://www.themoviedb.org/company/165435-angel-studios")["label"] == "TMDB studio"
    assert detect("https://www.themoviedb.org/collection/10-star-wars-collection")["type"] == "tmdb_collection"
    assert detect("https://www.imdb.com/list/ls055592025/")["type"] == "imdb_list"
    assert detect("https://www.imdb.com/user/ur12345678/watchlist")["label"] == "IMDb watchlist"
    assert detect("https://www.imdb.com/chart/top/") == {"type": "imdb_chart", "value": "top",
                                                          "label": "IMDb chart: Top 250 movies"}
    assert detect("https://trakt.tv/users/bob/lists/oscars?sort=rank")["type"] == "trakt_list"
    assert detect("https://trakt.tv/movies/trending")["value"] == "movies/trending"
    assert detect("https://mdblist.com/lists/linaspurinis/top-watched-movies-of-the-week")["type"] == "mdblist"
    assert detect("ls055592025")["type"] == "imdb_list"
    assert detect("https://example.com/my-list") == {"link": True}
    assert detect("tt0133093, tmdb:604")["type"] == "static"
    assert detect("tt0133093, tmdb:604")["label"] == "2 title ids"
    assert detect("Position,Const,Title\n1,tt0133093,The Matrix")["type"] == "static"
    assert detect("movie?with_genres=27&sort_by=vote_average.desc") == {
        "type": "tmdb_discover", "value": "movie?with_genres=27&sort_by=vote_average.desc", "label": "TMDB discover query"}
    assert detect("https://www.themoviedb.org/discover/tv?with_networks=213")["value"] == "tv?with_networks=213"
    assert detect("hello world") == {}


def test_source_test_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    from app import sync as sync_mod
    from app.main import app
    items = [{"title": f"T{i}", "plex_title": f"P{i}" if i < 2 else None, "in_plex": i < 2} for i in range(7)]
    monkeypatch.setattr(sync_mod, "preview", lambda *a, **k: {"items": items, "errors": [], "matched": 2})
    body = {"section_id": "1", "library": "Movies",
            "sources": [{"type": "tmdb_list", "value": "https://www.themoviedb.org/company/165435"}]}
    r = TestClient(app).post("/api/sources/test", json=body).json()
    assert r["ok"] and r["total"] == 7 and r["matched"] == 2 and r["sample"] == ["P0", "P1", "T2", "T3", "T4"]
    assert r["label"] == "TMDB studio"
    monkeypatch.setattr(sync_mod, "preview", lambda *a, **k: {"items": [], "errors": ["tmdb_list: TMDB 404"], "matched": 0})
    r = TestClient(app).post("/api/sources/test", json=body).json()
    assert not r["ok"] and "404" in r["error"]


def test_hall_of_fame_builtin(monkeypatch):
    from contextlib import nullcontext
    from fastapi.testclient import TestClient
    from app import api as api_mod, scheduler, sync as sync_mod
    from app.main import app

    class P:
        renamed = []

        def edit_collection(self, section, rk, title=None, **kw):
            self.renamed.append((rk, title))
    plex = P()
    monkeypatch.setattr(api_mod, "_plex", lambda: nullcontext(plex))
    monkeypatch.setattr(sync_mod, "resolve_section",
                        lambda p, sid, lib: {"id": sid, "title": f"Lib {sid}", "type": "movie"})
    monkeypatch.setattr(scheduler, "run_now", lambda *a, **k: None)
    client = TestClient(app)
    # an existing collection of the same name in library 31 is taken over, keeping its feed
    old = db.create_collection({"name": "IMDB Top 250", "library": "Lib 31", "section_id": "31", "sync_mode": "append",
                                "sources": [{"type": "mdblist", "value": "https://mdblist.com/lists/a/top250"}]})
    db.update_collection_state(old, plex_rating_key="555")
    listed = {b["key"]: b for b in client.get("/api/builtins").json()}
    assert listed["imdb_top_250"]["takeover"][0]["id"] == old
    r = client.post("/api/builtins/imdb_top_250/enable", json={"section_id": "31"})
    assert r.status_code == 201 and r.json()["id"] == old
    cfg = r.json()["config"]
    assert cfg["builtin"] == "imdb_top_250" and cfg["name"] == "IMDb Top 250" and cfg["sync_mode"] == "sync"
    assert cfg["sources"][0]["type"] == "mdblist" and cfg["ribbon"]["text"] == "IMDb TOP 250"
    assert cfg["poster_file"].endswith("-poster.jpg") and plex.renamed == [("555", "IMDb Top 250")]
    assert client.post("/api/builtins/imdb_top_250/enable", json={"section_id": "31"}).status_code == 409
    # a new library gets the default feed
    r2 = client.post("/api/builtins/imdb_top_250/enable", json={"section_id": "32"}).json()
    assert r2["config"]["sources"][0] == {"type": "tmdb_list", "value": "https://www.themoviedb.org/list/634-top-250-imdb",
                                          "limit": None}
    # saving can change only the feed (and schedule etc.); the look stays fixed
    edited = {**cfg, "name": "Mine", "ribbon": {**cfg["ribbon"], "text": "NOPE"}, "order": "alpha",
              "schedule": "0 3 * * *", "sources": [{"type": "imdb_chart", "value": "top"}]}
    saved = client.put(f"/api/collections/{old}", json=edited).json()["config"]
    assert saved["name"] == "IMDb Top 250" and saved["ribbon"]["text"] == "IMDb TOP 250" and saved["order"] == "custom"
    assert saved["schedule"] == "0 3 * * *" and saved["sources"][0]["type"] == "imdb_chart"
    assert saved["poster_file"] == cfg["poster_file"]
    assert client.get("/api/builtins/imdb_top_250/poster").headers["content-type"] == "image/jpeg"
    for cid in (old, r2["id"]):
        db.delete_collection(cid)


def test_netflix_top10_source():
    from app.sources import detect, netflix
    from app.sources.base import SourceContext
    assert detect("https://www.netflix.com/tudum/top10")["value"] == "films"
    assert detect("https://www.netflix.com/tudum/top10/tv/non-english")["value"] == "tv-non-english"
    tsv = ("week\tcategory\tweekly_rank\tshow_title\tseason_title\n"
           "2026-10-11\tFilms (English)\t1\tOld Film\tN/A\n"
           "2026-10-18\tFilms (English)\t2\tDoing Life\tN/A\n"
           "2026-10-18\tFilms (English)\t1\tAnimals\tN/A\n"
           "2026-10-18\tTV (English)\t1\tBelow\tBelow: Limited Series\n")

    def handler(request):
        if request.url.host == "www.netflix.com":
            return httpx.Response(200, text=tsv)
        if request.url.path == "/3/search/movie":
            q = request.url.params["query"]
            return httpx.Response(200, json={"results": [{"id": 7, "title": "Animals", "release_date": "2026-09-01"}]
                                             if q == "Animals" else [{"id": 9, "title": "Doing Life Again"}]})
        return httpx.Response(404)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        ctx = SourceContext({"tmdb_api_key": "k" * 32}, http, "movie")
        refs = netflix.fetch_chart("films", ctx, None)
    # newest week only, in rank order; a title TMDB has no same-named match for is left out
    assert [(r.title, r.tmdb) for r in refs] == [("Animals", 7)]


def test_ribbon_picture_bottom_right(monkeypatch, tmp_path):
    import io
    from PIL import Image
    from app import overlays
    pic = Image.new("RGB", (100, 100), (255, 255, 255))
    for x in range(100):
        for y in range(100 - x, 100):
            pic.putpixel((x, y), (245, 197, 24))         # yellow lower-right triangle on white
    pic.save(tmp_path / "test_pic.png")
    monkeypatch.setattr(overlays, "RIBBON_IMAGES", tmp_path)
    base = Image.new("RGB", (1000, 1500), (0, 0, 255))
    buf = io.BytesIO(); base.save(buf, "JPEG")
    spec = {"kind": "ribbon", "text": "X", "color": "#f5c518", "text_color": "#000000", "corner": "top-right",
            "size": "medium", "font": "sans", "image": "test_pic"}
    out = Image.open(io.BytesIO(overlays.render(buf.getvalue(), [spec]))).convert("RGB")
    assert out.getpixel((990, 1490))[2] < 100                # yellow in the bottom-right corner
    assert out.getpixel((600, 1100))[2] > 200                # the white part stayed see-through
    assert out.getpixel((990, 10))[2] > 200                  # nothing at the top right


def test_builtin_refresh_moves_old_default_feed():
    from app import builtins
    cid = db.create_collection({"name": "IMDb Top 250", "library": "Movies", "section_id": "1", "builtin": "imdb_top_250",
                                "sources": [{"type": "imdb_chart", "value": "top"}]})
    mine = db.create_collection({"name": "IMDb Top 250", "library": "M2", "section_id": "2", "builtin": "imdb_top_250",
                                 "sources": [{"type": "mdblist", "value": "https://mdblist.com/lists/a/b"}]})
    builtins.refresh_all()
    cfg = db.get_collection(cid)["config"]
    assert cfg["sources"][0]["value"] == "https://www.themoviedb.org/list/634-top-250-imdb"
    assert cfg["ribbon"]["image"] == "imdb_top_250" and cfg["ribbon"]["corner"] == "bottom-right"
    assert db.get_collection(mine)["config"]["sources"][0]["type"] == "mdblist"      # a chosen feed stays
    db.delete_collection(cid); db.delete_collection(mine)


def test_us_rating_icons():
    import io
    from PIL import Image
    from app import overlays
    name = overlays.rating_icon_name
    assert name("TV-14") == "ustv-14" and name("us/TV-MA") == "ustv-ma" and name("PG-13") == "uspg-13"
    assert name("Not Rated") == "usnr" and name("R", "color") == "usrc"
    assert name("gb/PG") == "" and name("TV-Y7") == "" and name("") == ""      # not US, or no icon for it
    for stem in overlays.US_ICONS.values():
        assert (overlays.RATING_ICONS / f"{stem}.png").is_file() and (overlays.RATING_ICONS / f"{stem}c.png").is_file()
    base = Image.new("RGB", (1000, 1500), (250, 250, 250))
    buf = io.BytesIO(); base.save(buf, "JPEG")
    out = Image.open(io.BytesIO(overlays.render(buf.getvalue(), [
        {"kind": "badges", "quality": [], "rating": None, "content_rating": "TV-14", "tv_icon": "ustv-14"}]))).convert("RGB")
    assert out.getpixel((45, 45))[0] < 170                  # darker backing in the top-left corner
    assert out.getpixel((60, 1440))[0] > 230                 # no text rating badge as well


def test_title_leaving_a_list_loses_its_ribbon(monkeypatch):
    from app import overlays, plex as plexmod
    for row in db.list_collections():
        db.delete_collection(row["id"])
    fake = FakeOverlayPlex()
    monkeypatch.setattr(plexmod, "from_settings", lambda *a, **k: Plex("http://plex", "t", client=httpx.Client(transport=fake)))
    cfg = CollectionConfig(name="Netflix Top 10", library="Movies", section_id="1", builtin="netflix_top_10",
                           sources=[Source(type="static", value="x")],
                           ribbon={"enabled": True, "text": "TOP 10", "corner": "bottom-right", "image": "netflix_top_10"})
    cid = db.create_collection(cfg.model_dump())
    db.update_collection_state(cid, plex_rating_key="100")
    assert overlays.apply_all()["drawn"] == 2
    fake.members = ["1"]                           # title 2 dropped off the list (the sync took it out)
    assert overlays.apply_all()["restored"] == 1
    assert fake.posters["2"] == fake.original["2"] and set(db.overlay_rows()) == {"1"}
    db.delete_collection(cid)
    overlays.apply_all()


def test_overlay_progress_lists_queued_triggers():
    from fastapi.testclient import TestClient
    from app import overlays
    from app.main import app
    with overlays._reasons_lock:
        overlays._reasons[:] = ["IMDb Top 250 removed", "Netflix Top 10 removed"]
    try:
        assert TestClient(app).get("/api/overlays/progress").json()["next"] == [
            "IMDb Top 250 removed", "Netflix Top 10 removed"]
    finally:
        with overlays._reasons_lock:
            overlays._reasons.clear()


def test_netflix_builtin_moves_to_tmdb_movie_list():
    from app import builtins
    films = db.create_collection({"name": "Netflix Top 10", "library": "Movies", "section_id": "1",
                                  "builtin": "netflix_top_10", "sources": [{"type": "netflix_chart", "value": "films"}]})
    tv = db.create_collection({"name": "Netflix Top 10", "library": "TV", "section_id": "2",
                               "builtin": "netflix_top_10", "sources": [{"type": "netflix_chart", "value": "tv"}]})
    builtins.refresh_all()
    assert db.get_collection(films)["config"]["sources"][0]["value"].endswith("/list/8300585-top-10-movies-netflix")
    assert db.get_collection(tv)["config"]["sources"][0]["value"] == "tv"           # TV keeps Netflix's chart
    assert builtins.collection_config(builtins.get("netflix_top_10"), {"id": "1", "title": "M", "type": "movie"}
                                      )["sources"][0]["type"] == "tmdb_list"
    db.delete_collection(films); db.delete_collection(tv)
