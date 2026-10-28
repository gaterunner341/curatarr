# Changelog

The version shown in the web UI's sidebar matches these entries. Each
release is also published as `ghcr.io/gaterunner341/curatarr:<version>`.

## 0.9.0

- **Playlists:** a new **Playlists** page in the left menu, below TV Shows. A playlist is built from lists just like a collection, but plays in list order, which suits watch orders such as the MCU or Star Wars.
  - A playlist can take titles from several libraries at once, for example movies and TV together. Tick the libraries in the editor.
  - A TV show in a playlist brings all of its episodes, in order.
  - When titles are removed or the list order changes, Curatarr rebuilds the playlist in list order. New titles at the end are simply added.
  - Playlists belong to the Plex account Curatarr signed in with.
  - Exclusions, the content-rating cap, Show missing titles, Add to Radarr/Sonarr, History details and Undo all work for playlists.
- **Existing Plex playlists** are listed below yours, with **View** and **Sync with a list**, the same as existing collections.

## 0.8.0

- **Plex library filter:** a new list source that picks titles from the collection's own Plex library instead of an outside list.
  - Examples: unwatched 80s horror, everything added in the last 30 days, a director's films.
  - Choose **Plex · Plex library filter** as a source and click **Build filter** to pick genre, director, studio, content rating, years, recently added, unwatched only and sort order.
  - It can be combined with other lists or used on its own.
- **Starter packs:** ready-made collections from TMDB, one click each. Open them with **Starter packs** on the Movies and TV Shows pages.

  | Library | Packs |
  | --- | --- |
  | Movies | 12 studios (Pixar, Disney Animation, DreamWorks Animation, Studio Ghibli, LAIKA, Aardman, Marvel Studios, Lucasfilm, A24, Blumhouse, Legendary, New Line), best of each decade from the 1950s, top rated by genre |
  | TV | 10 networks and streamers (HBO, Netflix, AMC, FX, Apple TV+, Disney+, Prime Video, Hulu, Showtime, BBC One), best of each decade from the 1980s, top rated by genre |

  - Pick a library, tick the collections you want, and choose Sync or Append and whether to send missing titles to Radarr/Sonarr.
  - Each pack becomes a normal collection you can edit afterwards.
  - Collections already in that library are marked "added".

## 0.7.0

- **Exclude a title:** on a collection's View page, hover a poster and click **✕** to take that title out of the collection and keep it out, even when a list has it. Excluded titles are listed in the collection's settings, where you can allow them again.
- **Content-rating cap:** a collection can leave out titles above a rating, such as PG for a kids collection.
  - The setting is **Highest content rating** under Sync behaviour. Movie and TV ratings that mean about the same are treated alike, for example PG-13 and TV-14.
  - Titles without a US rating are kept unless you tick **Also leave out unrated titles**.
- **Add one missing title:** in **Show missing titles**, each row has an **Add to Radarr** (or **Add to Sonarr**) button. It doesn't count toward the per-sync limit.
- **What changed:** History lists the titles each sync added (+) and removed (−). Click the +/− count to see them. This applies to syncs from 0.7.0 on.
- **Undo:** the View page shows the last change and has **Undo this change**, which takes out the titles that sync added and puts back the ones it removed.
  - Syncing is then paused, so the next scheduled sync doesn't redo it. Click **Resume syncing** when you're ready.
  - Undoing again redoes the change.
  - Undo doesn't restore the previous order. The next sync after you resume puts the titles back in list order.

## 0.6.5

- **View a collection** without opening Plex. Click a collection's name or **View** on the Movies, TV Shows or Holidays page to see the titles in it, in collection order, with posters and year. Watched titles have a check mark, and you can filter by title.
- Curatarr collections have **Show missing titles** on that page, listing the titles on the collection's lists that aren't in the Plex library.
- Existing Plex collections can be viewed the same way.

## 0.6.4

- **History** and **Logs** are now listed under **Settings** in the left menu, as indented sub-items. Settings stays highlighted while either one is open.

## 0.6.3

- **Fixed:** deleting a collection from Plex failed with HTTP 404. This affected the "Only in Plex during its dates" option and **Delete → also delete from Plex**. Plex deletes collections at `/library/metadata/<id>`, not the section address from the published API reference, which is now only a fallback.

## 0.6.2

- The left menu stays in place, with the version number at its bottom, while the page content scrolls. Long pages, such as an expanded Existing Plex collections section, no longer push the menu out of view.

## 0.6.1

- **Existing Plex collections** on the Movies and TV Shows pages can be collapsed, as a whole section and per library. The section starts collapsed and shows how many collections it holds.
- Your browser remembers which sections you opened or closed, for each page.

## 0.6.0

- **Seasonal-only collections:** a collection with a calendar can exist in Plex only during its dates.
  - It's created when the dates start and deleted from Plex after they end. This happens just after midnight, or at the next sync.
  - It's re-created each year with its poster and settings, and Curatarr keeps its settings all year.
  - Out of season, syncs skip fetching the lists entirely.
- On the Holidays page, each holiday has an **Only in Plex during its dates (deleted after)** option. You can set it before turning the holiday on or change it later. Cards show "not in Plex until <date>" when out of season.
- The same option is in the collection editor under the home screen calendar.
- A Plex collection that existed before Curatarr is never deleted this way. It's left in place.

## 0.5.3

Fixes from the first round of TrueNAS logs:

- **Fixed:** removing titles from a collection failed with HTTP 404. Plex removes collection items with DELETE, not the PUT that the published API reference describes.
- **Fixed:** after a collection was moved to a different library, syncs failed with HTTP 400 because they tried to add titles to the old library's Plex collection. A new collection is now created in the new library, and the old one is left untouched.
- **Safer:** when a new Curatarr collection has the same name as a collection you already made in Plex, Curatarr uses it but only adds titles. It never removes titles from it or deletes it. A notice in the editor lets you allow removals.
- **Safer:** missing titles are sent to Radarr/Sonarr at most 25 per collection per sync by default (**Settings → General**, 0 = no limit). Titles Radarr/Sonarr already has are skipped with one library check instead of one lookup per title, so large lists sync much faster. Each added title is logged.
- The scheduler's "Added job" messages no longer fill the logs.

## 0.5.2

- Holiday collections get the sort title `!01_<Holiday> Collection`, such as `!01_Halloween Collection`, so they sort above every other collection in Plex.
- Holiday collections that already exist get the sort title on the next start, unless you set your own. Plex shows it after the collection's next sync.

## 0.5.1

- Every holiday now has its own poster, all in one matching style: a dark seasonal gradient, a single emblem, a serif title and a thin frame. The posters show on the Holidays page and are applied in Plex when a holiday is turned on.
- Holiday collections turned on in 0.5.0 get their poster automatically on the next start, unless you've already set one.
- The posters are generated by `tools/holiday_posters.py`.

## 0.5.0

- New **Holidays** page in the sidebar. Tick a holiday to create its collection in the chosen library, with a yearly home screen calendar for its season, shown on Library recommended, My home and Friends' home.
  - Untick to turn it off. You choose whether to keep the collection in Plex.
  - **Edit dates & settings** opens the normal editor to change the dates, lists or where it appears.
  - Holiday collections are listed on the Holidays page instead of Movies / TV Shows.
- Each holiday uses the 100 most popular movies for its TMDB keyword. A link to the TMDB list is on each card.

  | Holiday | On the home screen |
  | --- | --- |
  | Valentine's Day | Feb 1 – Feb 14 |
  | St. Patrick's Day | Mar 10 – Mar 17 |
  | Easter | Mar 20 – Apr 25 (covers every possible Easter date) |
  | Independence Day | Jun 25 – Jul 4 |
  | Halloween | Oct 1 – Oct 31 |
  | Veteran's Day | Nov 1 – Nov 11 |
  | Thanksgiving | Nov 12 – Nov 28 |
  | Christmas | Nov 25 – Dec 26 |
- Each holiday has an **Add missing movies to Radarr** option.
  - Choose it before turning a holiday on, or change it later.
  - Curatarr asks for confirmation first, because up to 100 movies could be added.
  - The option is greyed out until Radarr is set up in Settings.
- Holidays can only be added to movie libraries, because the lists are movie lists.

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
