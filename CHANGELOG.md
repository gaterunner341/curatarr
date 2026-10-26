# Changelog

The version shown in the web UI's sidebar matches these entries. Each
release is also published as `ghcr.io/gaterunner341/curatarr:<version>`.

## 0.4.0

- **Home screen calendar:** a collection can be shown on Library recommended, My home and Friends' home only between two dates, once or every year. Yearly windows can span New Year, such as Dec 15 – Jan 5.
  - Ticking the calendar with no home-screen spots selected selects all three.
  - Collections switch on and off just after midnight (local time, from the `TZ` setting) and when Curatarr starts, without waiting for a sync.
  - Collection cards show the dates and whether the collection is showing or hidden right now.
- Fixed: the "Remove image file" button showed even when there was no image file.

## 0.3.3

- You can choose a poster and background image while creating a collection, not only after it's saved. Chosen images show a preview right away and upload when you save, before the first sync runs.
- Choosing or removing an image on an existing collection no longer reloads the page and throws away unsaved edits. The change is applied when you save.
- After an upgrade, the browser always loads the new version's interface instead of a cached old one.

## 0.3.2

- Syncs log each step with timings: library size, matched and missing counts, items added and removed, reorder progress, and artwork and settings. A long-running sync now shows what it's doing.
- Reordering moves only the items that are out of place, using far fewer Plex calls on big collections.
- New collections are checked against Plex's actual order, then reordered if needed.
- Plex paging stops if an endpoint keeps returning the same page, so a sync can't loop forever.

## 0.3.1

- The default sync schedule is now every 6 hours (`0 */6 * * *`) instead of daily at 3 AM. Installs still on the old default switch over automatically; a custom schedule is left alone.

## 0.3.0

- **Movies** and **TV Shows** are now separate pages in the sidebar, replacing the single Collections page. Each shows only its own Curatarr collections and existing Plex collections.
- **+ New collection** on each page starts with a library of that type selected.
- **Sync all** syncs only the collections on the page you're viewing.
- Old `#/collections` links open the Movies page.

## 0.2.0

- Existing Plex collections are listed below Curatarr's. **Sync with a list** links one to a list (append mode by default) without creating a duplicate.
- The TMDB source accepts company (studio), keyword, network, person and collection links, not just lists.
- A new **Logs** page with level and text filters, and **Download logs** (a zip of the logs plus diagnostics, with tokens and API keys removed). Logs are kept in `/config/logs`.
- The Plex card in Settings becomes a locked "Connected" summary with Test, Change server and Disconnect. The main Save no longer changes Plex settings.
- Paste-ready TrueNAS SCALE YAML (`truenas/curatarr.yaml`).
- **Sync all** is hidden until a collection exists.
- Removed Discord notifications.
- IMDb bot-check errors explain the alternatives (MDBList, or a CSV export in a Static ids source).

## 0.1.0

- First release: Plex collections from TMDB, IMDb, Trakt, MDBList and static ID lists, with scheduling, posters, home-screen promotion, preview, Radarr/Sonarr requests and YAML import/export.
