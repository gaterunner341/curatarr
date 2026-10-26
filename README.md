# Curatarr

**Curatarr** keeps Plex collections in sync with lists from TMDB, IMDb, Trakt and MDBList, in the same spirit as Sonarr and Radarr. Pick a list, pick a library, and Curatarr creates the collection, keeps it up to date on a schedule, applies your poster, and can send missing titles to Radarr or Sonarr.

## Features

- **List sources**
  - TMDB: lists, franchise collections, charts (popular, top rated, trending…) and discover queries
  - IMDb: lists, watchlists and charts (Top 250, Most Popular…), plus pasted IMDb CSV exports
  - Trakt: lists, watchlists and charts
  - MDBList lists
  - Static ID lists (`tt…`, `tmdb:…`, `tvdb:…`)
- **Several sources per collection**, merged in order with duplicates removed
- **Sync or append mode.** Sync adds and removes titles so Plex matches the list. Append only adds titles.
- **Order:** keep the list order (custom sort in Plex), or sort by release date or alphabetically
- **Artwork:** upload a poster or background image, or give an image URL. TMDB franchise posters are used automatically.
- **Plex presentation:** summary, sort title, labels, collection mode (hide items or show items), and promotion to Library Recommended, your Home and Friends' Home
- **Matching:** uses the IMDb, TMDB and TVDB IDs stored in Plex, for both new and legacy agents, with a title and year fallback
- **Preview:** shows which titles are already in your library before you save
- **Missing titles:** listed in the History page, and can be added to Radarr or Sonarr automatically
- **Scheduling:** a global cron schedule or one per collection, plus "Sync now" and dry runs
- **YAML import and export.** A `collections.yml` dropped in `/config` is imported on startup.
- **Sign in with Plex:** gets a token and lists your servers, or you can paste a token yourself
- **Optional security:** a login for the UI and an API key for scripts. The REST API is documented at `/api/docs`.

## Install with Docker Compose

```yaml
services:
  curatarr:
    image: ghcr.io/gaterunner341/curatarr:latest
    container_name: curatarr
    restart: unless-stopped
    ports:
      - "8585:8585"
    volumes:
      - ./config:/config
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=America/New_York
```

```bash
docker compose up -d
```

Open `http://<host>:8585` and go to **Settings**:

1. **Plex:** click **Sign in with Plex** and pick a server connection. You can also enter the server URL and your [X-Plex-Token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/) yourself.
2. **TMDB:** add a free API key, which TMDB sources need.
3. **Trakt / MDBList / Radarr / Sonarr:** add these only if you plan to use them.

Then go to **Collections → New collection**.

See [`docker-compose.yml`](docker-compose.yml) for every supported environment variable.

## Install on TrueNAS SCALE

On TrueNAS SCALE 24.10 or newer:

1. Go to **Apps → Discover Apps → ⋮ (top right) → Install via YAML**.
2. Name the app `curatarr`.
3. Paste the contents of [`truenas/curatarr.yaml`](truenas/curatarr.yaml) and click **Save**.

The file already maps port 8585 and creates storage for the config, so it needs no edits. Open `http://<truenas-ip>:8585` once the app shows **Running**.

Use **Install via YAML** rather than the **Custom App** form. The form leaves port mappings empty unless you add them yourself, and the web UI can't be reached without one.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `PUID` / `PGID` | User and group that own the files in `/config` (default `1000`) |
| `TZ` | Time zone used for schedules |
| `PLEX_URL`, `PLEX_TOKEN` | Plex connection (or set in UI) |
| `TMDB_API_KEY`, `TRAKT_CLIENT_ID`, `MDBLIST_API_KEY` | List provider keys |
| `RADARR_URL`, `RADARR_API_KEY`, `SONARR_URL`, `SONARR_API_KEY` | Missing title requests |
| `CURATARR_SCHEDULE` | Default cron schedule (default `0 3 * * *`) |
| `CURATARR_USERNAME`, `CURATARR_PASSWORD` | Turn on a browser login for the UI and API |
| `CURATARR_API_KEY` | Require an `X-Api-Key` header (or `?apikey=`) for the API |
| `CURATARR_PORT` | Listen port (default `8585`) |
| `CURATARR_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`… |

If a setting is saved in the UI, the saved value wins over the environment variable.

## Collections as YAML

```yaml
collections:
  - name: Marvel Cinematic Universe
    library: Movies
    sources:
      - type: tmdb_list
        value: https://www.themoviedb.org/list/8136
    order: release
    sort_title: "!02 MCU"
    promote_home: true

  - name: Trending Shows
    library: TV Shows
    sources:
      - type: trakt_chart
        value: shows/trending
        limit: 30
    schedule: "0 */12 * * *"
    request_missing: true
```

| Field | Default | Notes |
| --- | --- | --- |
| `name`, `library`, `sources` | required | `library` is the Plex library title |
| `sources[].type` | | `tmdb_list`, `tmdb_collection`, `tmdb_chart`, `tmdb_discover`, `imdb_list`, `imdb_chart`, `trakt_list`, `trakt_chart`, `mdblist`, `static` |
| `sources[].value` | | URL, id, chart name (`movie/popular`, `top`, `shows/trending`…) or discover query (`movie?with_genres=27`) |
| `sources[].limit` | none | Max titles taken from that source |
| `sync_mode` | `sync` | `sync` or `append` |
| `order` | `custom` | `custom` (list order), `release`, `alpha` |
| `item_limit` / `min_items` | `0` / `1` | Total cap, and the minimum number of matches before the collection is created |
| `delete_below_min` | `false` | Delete the Plex collection when matches drop below `min_items` |
| `summary`, `sort_title`, `labels` | | Collection metadata |
| `collection_mode` | `default` | `default`, `hide`, `hideItems`, `showItems` |
| `poster_url`, `art_url` | | Image URLs; uploaded files take priority |
| `promote_recommended`, `promote_home`, `promote_shared` | `false` | Home screen hubs |
| `schedule` | global | Five-field cron expression |
| `request_missing` | `false` | Send missing titles to Radarr or Sonarr |
| `enabled` | `true` | Turn scheduled syncs on or off |

## A note on IMDb

IMDb has no public API, and it sometimes turns away automated requests with a bot check. Curatarr does not try to get around that check. If an IMDb source is blocked, use one of these instead:

- Add the IMDb list to an [MDBList](https://mdblist.com) list, which can follow IMDb lists, and use an **MDBList list** source.
- Use **Export** on the IMDb list page and paste the CSV into a **Static ids** source.
- Trakt and MDBList both offer the IMDb Top 250 as public lists.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # Windows: .venv\Scripts\pip
.venv/bin/pytest
CURATARR_CONFIG_DIR=./config .venv/bin/python -m app
```

The backend is FastAPI with SQLite and APScheduler. The UI is a single dependency-free page in `app/static`. Pushing to `main`, or pushing a `v*` tag, builds a multi-arch image (amd64 and arm64) and publishes it to GHCR through GitHub Actions.

## License

MIT
