# Changelog

The version shown in the web UI's sidebar matches these entries. Each
release is also published as `ghcr.io/gaterunner341/curatarr:<version>`.

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
