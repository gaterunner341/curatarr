# Changelog

The version shown in the web UI's sidebar matches these entries. Each
release is also published as `ghcr.io/gaterunner341/curatarr:<version>`.

## 0.16.0

- **Badges for whole libraries:** in **Settings → Poster overlays → Whole libraries**, give every movie or show in a library a content rating badge, plus quality badges (movies) and a rating badge if you like. It isn't limited to titles in a collection.
  - **Preview** shows a library's first title with its badges. **Save library badges** asks before drawing on a library for the first time.
  - Uses the same engine as collection overlays: original posters are kept and put back when a library is turned off, and progress shows in the top bar.
  - A title also in a collection with badges or a ribbon gets them combined on one poster.
  - The first update on a big library takes a while, at one poster per title (roughly an hour for 5,000 titles). After that, only changed titles are redrawn.
- Napalm and **Remove all overlays** turn off library-wide badges too. Napalm lists them among what it turns off.

## 0.15.4

- **Napalm shows how many titles each library has.** Tick a library and its count appears next to it (e.g. "MoviesSpecial (Movies) · 651 movies"). A summary line totals the libraries you picked, like "651 movies and 120 TV shows will be checked". Only titles not already on their fresh poster change.

## 0.15.3

- **Napalm's preview shows titles that would change.** Titles with Curatarr overlays come first, then random titles that would get a different poster. Titles that keep their poster only fill in when fewer than eight would change, and they're shown last.
  - Titles with an overlay are marked "its Curatarr overlay is removed".

## 0.15.2

- **Fixed:** napalm and the fresh-poster option could pick a wide image, such as a video frame, because Plex's sources sometimes offer those as posters. Each candidate is now checked, and only a properly shaped poster is used (between 1.25 and 1.8 times as tall as wide, like the usual 2:3). Titles with none keep their current poster.
- Running napalm again fixes titles that got a wide image: their proper poster isn't the selected one, so they're switched to it.

## 0.15.1

- **Napalm now leaves posters clean.** It turns off Curatarr's poster overlays (ribbon, badges and fresh poster) on every collection in the libraries it refreshes, so they aren't drawn back on afterwards.
  - The fresh posters are kept. Curatarr drops its backups of the old posters instead of restoring them.
  - Titles napalm didn't reach (because it was stopped early, or there was no source poster) get their original posters back.
  - You'll see which collections are affected in three places: on the card as soon as you tick a library, in the confirmation, and in the message when it finishes. The card also keeps a **Last refresh** summary that links to those collections, so you can turn their overlays back on.
  - No overlay update runs while napalm is working, so old posters can't come back part way through.

## 0.15.0

- **Bigger ribbons by default:** the band is thicker and reaches further along the edges, so the text is larger.
- **Ribbon size:** Small, Medium (the new default), Large or Extra large. The text is always drawn as large as fits in the band.
- **Ribbon font:** choose from free fonts installed in the image: Sans bold, Condensed bold, Roboto bold, Open Sans bold, Lato black, Serif bold and Mono bold. Only fonts available on your server are listed. The Docker image adds the Liberation, Roboto, Open Sans and Lato font packages.
- Existing ribbons are redrawn at the new default size at the next overlay update (a sync, or **Settings → Poster overlays → Update overlays now**).

## 0.14.0

- **Content rating badge:** a new badge option under **Poster overlays**. It shows the title's rating from Plex (PG-13, R, TV-MA, or a country rating like 12A) in gold, first in the bottom-left row.
- **Start from a fresh poster:** a new option under **Poster overlays**. Each title's ribbon and badges are drawn on the first poster from Plex's metadata sources (such as TMDB) instead of the current one, so artwork other tools added drops away.
  - On its own, without a ribbon or badges, it just switches the collection's titles to that clean poster.
  - The current posters are backed up as usual and come back if you turn it off.
  - **Preview** shows the fresh poster too.
- **I love the smell of napalm in the morning:** a new card in Settings that gives every movie and show in the libraries you pick a fresh poster, the first one from Plex's metadata sources.
  - **Preview** shows random titles with their current poster next to the one they'd get. Click it again for others.
  - Clear warnings, a tick box and a confirmation come before anything changes: posters picked by hand are replaced too, and it can't be undone in one click. Nothing is deleted, though: it uses Plex's own poster selection, so the old posters stay in each title's poster list in Plex.
  - Progress shows in the top bar ("Refreshing posters · 120 / 5748"), and there's a **Stop** button. A summary appears when it finishes.
  - Titles with Curatarr ribbons or badges are redrawn on their new poster afterwards.
  - Titles already on their fresh poster, or with no poster from Plex's sources, are left as they are.

## 0.13.4

- **Ribbons can go in any corner:** bottom right and bottom left join top right and top left.
- When a ribbon is in a bottom corner, the badges on that side move inward along the bottom edge to clear it. If the rating badge then doesn't fit beside the quality badges, it moves up one row. Posters with top-corner ribbons look the same as before.

## 0.13.3

- **See background work as it happens:** the top bar shows what's running on every page.
  - A sync shows as "Syncing IMDB Top 250…".
  - Poster overlays show their progress, like "Drawing poster overlays · 45 / 176" or "Restoring original posters · 12 / 40".
  - When the overlays finish you get a message, and the View page and Dashboard refresh so the new posters show. If any poster failed, the message says so; the details are in Logs.
  - Curatarr checks every 2 seconds while work is running, every 15 seconds otherwise, and right after you save or start something.

## 0.13.2

- **Overlays are easier to check:** every overlay pass now writes one line to the log, even when nothing changed. For example: "Overlays: 176 title(s) with overlays: 176 drawn, 0 unchanged, 0 with nothing to show; 0 restored, 0 failed".
- The log bundle's diagnostics now show each collection's overlay settings and how many posters have overlays.
- **Fixed:** a rating badge could be missing when Plex left ratings out of a collection's title list. Curatarr now reads the rating from the title's full details instead.

## 0.13.1

- **See what's in a collection even when it isn't in Plex.** An off-season holiday, or any collection not created in Plex yet, now lists on its View page the titles from your library it will have, with their posters.
  - Exclusions, the rating cap and any order you set by hand are applied.
  - You can exclude titles from there too.
  - **Show missing titles** still lists what isn't in your library.
- **Check your poster overlays:** on a collection's View page, a line shows how many of its posters have overlays so far, and those titles get a small gold dot. The posters shown are Plex's own, so ribbons and badges appear right on them.

## 0.13.0

- **Poster overlays: quality and rating badges.** Under **Poster overlays** in a collection's settings, every title's poster can show small badges along the bottom:
  - **Quality badges** (movies), bottom left: resolution (4K, 1080P, 720P, SD), then DV (Dolby Vision) or HDR, then ATMOS. They come from Plex's own media info for the best version of each movie.
  - **Rating badge**, bottom right: the audience rating (e.g. IMDb 8.4) or the critic rating (e.g. RT 92%) that Plex shows for the title. Ratings come from the library's settings in Plex. You can hide ratings below a minimum, such as only 7.0 and up.
  - Badges are text in each site's color, not copies of their logos.
- A title's quality is read from Plex once and saved. It's only checked again when the title's files change, so later syncs stay fast.
- Badges and ribbons work together and use the same original-poster backup. **Remove all overlays** turns off both.
- **Preview** uses the collection's first title, with sample badges where it has no data.

## 0.12.0

- **Poster overlays: collection ribbons.** A collection can put a diagonal corner ribbon on the poster of every title in it, such as "IMDb TOP 250" in yellow.
  - It's under **Poster overlay** in the collection's settings. Set the text, the ribbon and text colors and the corner, then click **Preview** to see it on one of the collection's posters.
  - A title in several collections with ribbons gets all of them, stacked inward from the corner.
  - Before a poster is changed, its original is saved in the config folder (`/config/overlays`). Turning a ribbon off, deleting the collection, or a title leaving the collection puts the original poster back.
  - Posters are redrawn only when a ribbon changes. If Plex replaces a poster, through a metadata refresh or a poster you picked, that becomes the new original and the ribbon is drawn on it.
  - Titles with an overlay get the Plex label `Curatarr Overlay`.
  - **Settings → Poster overlays** shows how many posters have overlays and has **Update overlays now** and **Remove all overlays**. Remove all puts every original back and turns all ribbons off.
- Overlays are updated after every sync, and straight away when you change a ribbon or delete a collection.

## 0.11.2

- **Show missing titles** marks titles Radarr or Sonarr already has with an **In Radarr** (or **In Sonarr**) badge as soon as the list opens, instead of showing an **Add** button. Those titles are waiting to be downloaded. Curatarr checks each service's library once, so the list still opens quickly.

## 0.11.1

- **Dashboard → Coming up** shows the dates each collection is on the home screen, such as "Nov 12 – Nov 28", and its library. Below that, it says when the collection starts or until when it's showing.

## 0.11.0

- **Seven more holidays,** each with a poster in the same style as the others:

  | Holiday | Dates | TMDB keywords |
  | --- | --- | --- |
  | New Year's | Dec 26 – Jan 2 | new year's eve (613), new year's day (5632) |
  | Lunar New Year | Jan 20 – Feb 20 | chinese new year (250496), lunar new year (356063) |
  | Football | Jan 25 – Feb 15 | american football (579) |
  | Mother's Day | May 1 – May 14 | mother's day (173983) |
  | Father's Day | Jun 1 – Jun 21 | father's day (195439) |
  | Back to School | Aug 10 – Sep 10 | back to school (187282), high school (6270) |
  | Hanukkah | Nov 28 – Jan 2 | hanukkah (7328), chanukah (272884) |

- **Add your own holiday:** **+ Add holiday** on the Holidays page.
  - Give it a name, dates, a TMDB keyword or list link, and poster colors. Curatarr draws a matching poster with the holiday's initial.
  - Your holidays work like the built-in ones and can be edited or deleted. Editing the dates updates their collections too.
- **Top of the home screen:** a collection with a calendar can be moved to the top of the home screen while it's showing, then put back afterwards.
  - Holiday collections do this by default, including ones you already have.
  - To change it, use **Move it to the top of the home screen during these dates** in the collection's settings.
- The Docker image now includes Pillow and the DejaVu fonts, which draw the posters for holidays you add.

## 0.10.0

- **Dashboard:** a new start page, at the top of the left menu.
  - Totals for collections, playlists, holiday collections, titles in Plex, missing titles and how much has been watched.
  - **Needs attention:** collections with a sync error or warning, or paused ones.
  - **Coming up:** the next home-screen calendar changes, such as when Thanksgiving appears.
  - **Most missing:** the collections with the most titles not yet in your library.
  - **Recent syncs.**
- **Arrange order by hand:** on the View page of a playlist or a collection in list order, click **Arrange order** and drag the posters into place. Then click **Save order**.
  - Plex is updated right away, and later syncs keep your order. New titles from the lists go at the end.
  - **Reset to list order** goes back to the lists' order.
- **Choose a poster from TMDB:** in a collection's or playlist's Artwork section, **Choose from TMDB…** shows posters for the collection's TMDB franchise, plus matches for its name.
  - Click one to use it. You can also search for something else.
  - It's applied in Plex at the next sync after you save.

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
