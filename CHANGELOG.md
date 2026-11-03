# Changelog

The version shown in the web UI's sidebar matches these entries. Each
release is also published as `ghcr.io/gaterunner341/curatarr:<version>`.

## 0.31.0

- **US rating icons from Kometa, for movies and shows:** G, PG, PG-13, R, NC-17, Not Rated, TV-Y, TV-G, TV-PG, TV-14 and TV-MA, in the top-left corner.
  - Choose **White** (outline, on a dark backing) or **Colour** (Kometa's coloured icons).
  - Turn it on per collection (Poster overlays → "US rating icon") or for any whole library (Settings → Poster overlays → Whole libraries → Rating icon).
  - Only US ratings get an icon: a UK "PG" doesn't show as the US one. Ratings with no icon (e.g. TV-Y7) keep the text badge if that's on.
  - These replace the TV icons added in 0.30.0. Where that option was on, movies now get their icon too.
  - The icons are part of Curatarr (`app/static/ratings`, with Kometa's MIT License alongside), not downloaded at runtime.

## 0.30.4

- **Netflix Top 10 feed:** in movie libraries the built-in now follows TMDB's list "Top 10 Movies Netflix" (themoviedb.org/list/8300585). TV libraries keep Netflix's own Top 10 TV chart. A Netflix Top 10 still on the old films chart moves to the TMDB list automatically. A feed you chose yourself is kept.

## 0.30.3

- **Overlay progress shows queued triggers:** a change made while a pass is already running waits for the next pass, and the top bar now says so, e.g. "Drawing poster overlays (Independence Day Collection synced; then IMDb Top 250 removed, Netflix Top 10 removed)". Hover for the full list.

## 0.30.2

- **Hall of Fame ribbons:** the IMDb Top 250 and Netflix Top 10 collections use Kometa's yellow ribbon images, drawn in the bottom-right corner at Kometa's size. The rating badge moves clear of them.
  - The images are part of Curatarr (`app/static/ribbons`, with Kometa's MIT License alongside), not downloaded at runtime.
  - Posters with the previous text ribbon are redrawn on the next overlay pass.

## 0.30.1

- **Overlay progress says what started it:** the top-bar indicator names the trigger, e.g. "Drawing poster overlays (IMDb Top 250 synced) · 9 / 662". Hover for the full text if it's cut short. Triggers: a collection synced, a collection's overlay settings changed, a collection removed, whole-library badges changed, a poster uploaded, napalm finished, or Redraw / Remove all clicked. Requests made during a pass are listed together.
- **Hall of Fame: Add collection:** each built-in has one library picker (primary library first) and an **Add collection** button. The Radarr/Sonarr option matches the library picked. Libraries it's already in are listed below under "In your libraries", with View, Change feed and Remove.

## 0.30.0

- **TV rating icons:** shows can show their US TV rating as an icon (TV-Y, TV-G, TV-PG, TV-14, TV-MA) in the top-left corner, on a dark backing so it reads on any poster.
  - Turn it on per collection (Poster overlays → "TV rating icon on shows") or for a whole TV library (Settings → Poster overlays → Whole libraries).
  - If a ribbon is in the top-left corner, the icon sits below it. When a show has the icon, the content rating isn't repeated as a text badge.
  - Ratings with no icon (e.g. TV-Y7) keep the text badge if that's on.
- **IMDb Top 250 feed:** the built-in now follows TMDB's list "Top 250 IMDb" (themoviedb.org/list/634). IMDb often blocks automated requests; TMDB doesn't. A built-in still on the old IMDb-chart default moves to it automatically. A feed you chose yourself is kept.
- **Hall of Fame: Remove** button on each library's built-in collection. It takes the ribbon off every poster (the originals go back) and can also delete the collection from Plex.

## 0.29.0

- **Netflix Top 10** in the Hall of Fame: this week's most-watched on Netflix worldwide, from netflix.com/tudum/top10.
  - Movie libraries get the top 10 films and TV libraries the top 10 shows, in Netflix's order. Its look is fixed: poster, ribbon, order and Sync mode.
  - Titles are matched on TMDB by exact name (a TMDB API key is needed). A title TMDB has no same-named match for is left out rather than guessed.
- **New source: Netflix Top 10 charts:** films or TV, English or non-English. Pick one with **+ Add chart**, or paste a netflix.com/tudum/top10 link into a list box.
- **Ribbon pictures:** built-in collections can use a picture for their ribbon instead of drawn text. It goes in the bottom-right corner, and the rating badge moves clear of it. Until the pictures are added, they fall back to a drawn text ribbon in that corner.
- Hall of Fame collections pick up changes to their fixed settings automatically when Curatarr starts.

## 0.28.0

- **Hall of Fame** (new menu link): built-in collections with a fixed look, starting with the **IMDb Top 250**.
  - **Look:** it has its own poster (IMDb yellow, "THE IMDb TOP 250"), an "IMDb / TOP 250" ribbon, IMDb's order and Sync mode. None of these can be changed.
  - **What you can change:** the feed (the list it follows, by default IMDb's Top 250 chart), whether it's on, its schedule and whether missing titles go to Radarr. You can also exclude titles from its View page.
  - **Adding it:** add it to any movie library from the Hall of Fame page. If that library already has a Curatarr collection with the same name (e.g. "IMDB Top 250"), that collection becomes the built-in one. It keeps its feed, schedule and Plex collection, and the Plex collection is renamed to "IMDb Top 250".
  - **Where it shows:** built-in collections appear in the Hall of Fame, not on the Movies page.

## 0.27.2

- **Live overlay preview:** in a collection's Poster overlays settings, the preview redraws by itself shortly after you change any setting (ribbon text, corner, size, font, colours, badges, fresh poster), and is drawn when the page opens. There's no Preview button any more. The previous image stays, dimmed, until the new one arrives.

## 0.27.1

- **Fixed:** two-line ribbon text read the wrong way round in the top corners. The first part (e.g. "IMDB") is now always the top line and a little bigger, with the rest ("TOP 250") below it, in every corner. Ribbon posters are redrawn on the next overlay pass.

## 0.27.0

- **Kometa-style ribbons:** ribbons are drawn with Kometa's proportions, in any of the four corners as before.
  - The band is thicker and sits closer to the corner.
  - Text that would come out small on one line is split over two, like Kometa's: the first part large on the inner side of the band, the rest smaller nearer the corner, e.g. "IMDb" over "TOP 250". Short text such as "4K" stays on one line, as big as fits.
  - The size and font options still apply. Badges still move clear of a ribbon in a bottom corner.
- Posters that already have ribbons are redrawn in the new style on the next overlay pass, from their saved originals.

## 0.26.2

- **Dashboard:** details in the cards (Needs attention, Coming up, Recent syncs) wrap inside the card instead of being cut off with "…". A very long message, such as an error, stops after four lines; hover to see all of it.
- **Most missing** shows which library each collection is in, e.g. "Angel Studios Collection (MoviesSpecial)", so same-named collections in different libraries can be told apart.

## 0.26.1

- **List boxes:** a link sits in a normal one-line box again, with no scrollbar over it in a narrow window. Pasting several lines, like an IMDb CSV export or ids one per line, switches to a bigger box.
- **Narrow windows:** the type tag moves above its box, so the box keeps its width.

## 0.26.0

- **No more source-type dropdown:** each list is one box. Paste a link, title ids or a TMDB discover query and Curatarr works out what it is. A tag next to the box says what it recognised, e.g. "TMDB studio", "IMDb watchlist", "Trakt list" or "3 title ids". Anything it doesn't recognise is flagged.
  - Recognised:
    - TMDB lists, collections, and studio, network, keyword and person pages
    - IMDb lists, watchlists and chart links
    - Trakt lists, watchlists and chart links
    - MDBList lists
    - title ids (tt…, tmdb:…, tvdb:…)
    - IMDb CSV exports
    - TMDB discover queries and discover links
  - Charts and Plex filters aren't links, so they have their own buttons:
    - **+ Add chart** gives one dropdown with every TMDB, IMDb and Trakt chart, grouped by service.
    - **+ Add Plex filter** keeps the Build filter button.
  - Pasting a chart link (e.g. imdb.com/chart/top) turns the row into that chart.
  - Saved collections keep their sources and show the recognised type when opened.

## 0.25.0

- **Links pick their own source type:** paste a link into a list source and Curatarr recognises it, switches the source to the right type and says what it found.
  - Recognised: TMDB list, collection, studio, network, keyword and person pages; IMDb lists, watchlists and charts; Trakt lists, watchlists and charts; MDBList lists.
  - A link it can't use is flagged.
- **Test button on every source:** fetches just that source and reports whether it works, how many titles it gives, how many are in your library, and the first few. If it doesn't work, it shows the error, e.g. a missing API key, a private list or IMDb's bot protection.
  - Works for every source type, including charts, discover queries, static ids and Plex filters.
- **Plex labels in the Plex filter builder:** pick a label to build a collection from every title with that Plex label, and use Test to check what it finds.

## 0.24.0

- **Dashboard:** "Needs attention" shows the Rogue Filenames count from the last scan, e.g. "11 files in 2 titles don't follow the naming format (Radarr 2, Sonarr 9)", with a link to the page.
  - It appears only once a scan has run and found files.
  - Services that couldn't be scanned aren't counted.

## 0.23.2

- **Dashboard:** removed the Watched % card.

## 0.23.1

- **Fixed:** "Sonarr couldn't find this title" for shows that Sonarr does have, such as new shows like Quokka's Wild Life.
  - Curatarr used to ask Sonarr only by TVDB id, which it got from TMDB. TMDB often has no TVDB link yet for new shows.
  - Now it also asks Sonarr by TMDB and IMDb id, then by title. A result only counts when its TMDB or IMDb id is the show's own, so a show with a similar name is never added by mistake.

## 0.23.0

- **Rogue Filenames** (Settings → Rogue Filenames): finds movie and episode files whose names don't follow the naming formats set in Radarr and Sonarr (Settings → Media Management).
  - Radarr and Sonarr decide this themselves. Curatarr asks each one for its rename preview for every movie and series, and lists the files it would rename: the current name → the name its format gives.
  - The page shows each service's formats, warns when Rename Movies/Episodes is off, and has a filter.
  - The scan runs in the background, can be stopped, and the last result is kept. Nothing is renamed: use **Rename Files** in Radarr or Sonarr.
  - Only file names are checked. Radarr and Sonarr don't report folders that differ from the folder format.
- **Settings menu folds up:** the arrow next to Settings shows or hides its sub-pages. Your browser remembers the choice, and opening a sub-page unfolds it.

## 0.22.0

- **Root folder per library, found automatically:** Curatarr works out each Plex library's Radarr/Sonarr root folder from Radarr/Sonarr's own data. It matches the library's titles to Radarr/Sonarr titles by TMDB/IMDb/TVDB id and uses the root folder most of them are in. Missing titles requested from a collection, by a sync or with **Add to Radarr/Sonarr**, go there. Nothing needs setting.
  - **Settings → Radarr / Sonarr** shows what was found for each library (e.g. "212 of 215 of this library's titles in Radarr are in /Movies_Special"). You can pick a folder there to override it.
  - A library with none of its titles in Radarr/Sonarr yet uses the Root folder setting.
  - The guess by folder name added in 0.21.1 is removed.

## 0.21.1

- **Root folder per library:** for a library with no folder set yet, Settings preselects the Radarr/Sonarr root folder whose name matches the library, ignoring case and punctuation (e.g. MoviesSpecial → `/Movies_Special`). It's marked "matched by name" and kept when you save.

## 0.21.0

- **Root folder per library:** Radarr and Sonarr can now use a different root folder for each Plex library. Before this, every request went to the single Root folder in Settings, whichever library the collection was in.
  - Set them in **Settings → Radarr / Sonarr**, under "Root folder for each Plex library". The list appears once Curatarr can reach Radarr/Sonarr, or after **Load folders & profiles**.
  - Titles requested from a collection, by a sync or with **Add to Radarr/Sonarr**, go to that library's folder. Libraries left on "Default" keep using the Root folder.

## 0.20.0

- **Primary libraries:** pick a primary movie library and a primary TV library under **Settings → General**. They're listed first everywhere, and every page and new collection starts on them: the collection editor, starter packs, holidays, Existing Plex collections, Poster overlays and Napalm. Leave them blank to keep Plex's order.

## 0.19.2

- **Fixed (prerolls):** Curatarr had Plex's separators backwards. In Plex's preroll setting, commas mean "play all of them, in order" and semicolons mean "play one at random". Curatarr now reads and writes them that way, so a semicolon list shows as "one played at random".
- **Prerolls:** until Curatarr manages your prerolls, the Prerolls page fills in the play mode and the Default set from Plex's current preroll list. Turn on managing and save to take it over as it is.

## 0.19.1

- **Fixed:** a collection or playlist that Curatarr created could be treated as one that "existed before Curatarr". This happened when Curatarr lost track of it and found it again by name, for example after a holiday was turned off and back on. Curatarr then only added titles to it and left it in Plex out of season.
  - Curatarr now records every Plex collection and playlist it creates.
  - Ones it made earlier are recognised from sync history and fixed automatically on their next sync.
- **Dashboard:** "Coming up" shows one entry when the same collection has the same dates in several libraries, listing all of them.

## 0.19.0

- **List overlays:** put a ribbon and/or badges on every title from a list, such as Oscar Best Picture winners or other awards, without making a Plex collection.
  - Create one with **+ New list overlay** under **Settings → Poster overlays**.
  - It uses the same editor and sources as a collection (TMDB, IMDb, Trakt, MDBList, static IDs, Plex filters), plus exclusions, the rating limit and Radarr/Sonarr requests. The collection-only options are hidden.
  - It syncs on the same schedule. Titles new to the list get the overlay, and titles that leave it get their original poster back.
  - **View** shows the titles it found. History records what each sync added and removed.
  - A title on several list overlays, collections or libraries with overlays gets them all combined on one poster.
  - Napalm turns off list overlays in the libraries it refreshes, like collection overlays.
- **The preroll library is hidden** from **Whole libraries** and **Napalm**. That's the one set on the Prerolls page, or one named like "PreRolls".

## 0.18.2

- **Bigger badges:** quality, content rating and rating badges are about 20% bigger by default.
- **Badge size:** a new option, Small, Medium (the default), Large or Extra large. It's in a collection's **Poster overlays** section and in each **Whole libraries** row. If a title gets badges from more than one place, the largest size is used.
- Existing posters are redrawn at the new size at the next overlay update (a sync, or **Update overlays now**).

## 0.18.1

- **Poster overlays** and **Napalm** now have their own pages, listed under **Settings** in the left menu next to History and Logs. Settings stays highlighted while either is open. The Settings page itself is back to connections and general options.

## 0.18.0

- **Prerolls:** a new page in the left menu that manages Plex's preroll list from a Plex library instead of the typed list of paths in Plex's settings.
  - **Your preroll library:** a library with "preroll" in its name, such as **PreRolls**, is picked automatically, or you can choose another. Its clips are listed with thumbnail, name, length and file. Paths come from Plex itself, so they're always the ones the server can play.
  - **Matched to Plex's current list:** the page shows what Plex plays now, marks those clips "in Plex's list now", and lists any paths in Plex's list that aren't in the library. **Use Plex's current list** copies it into the default set.
  - **Sets:** a **Default** set, plus **seasonal sets** with dates (e.g. Halloween Oct 1–31) that take over during their dates every year and switch automatically just after midnight. Windows can span New Year.
  - **Play mode:** one clip at random before each movie, all of them in order, or a new random pick of N clips each day.
  - **Safe:** before Curatarr first changes Plex's preroll list, it saves the list Plex had. **Restore Plex's original list** puts it back and stops managing. The page shows today's set and when it next changes.
  - Plex plays prerolls before movies only, on apps with Cinema Trailers turned on, and they need Plex Pass.

## 0.17.2

- **Fan edits on the Unmatched page:** titles with a Plex label like **Fan Edit** or **FanEdit** are now listed too, even when they're properly matched. Case, spaces, hyphens and underscores don't matter, and "Fan Edits" counts too.
  - They carry a **Fan edit** tag, next to **Not matched** or **No IMDb/TMDB IDs** when those apply as well.
  - The **Kind** filter and the totals include fan edits.
  - Upload poster, Keep poster and Open in Plex work for them like any other title.
- The page and its menu link are now called **Unmatched and Fan Edits**.

## 0.17.1

- **Upload posters for unmatched titles:** each title on **Unmatched titles** has an **Upload poster** button.
  - Choose an image file (JPEG, PNG or WebP, up to 10 MB) or paste an image URL, and see a preview before uploading. Plex then uses it as the title's poster.
  - The new poster is **kept** by default (the `Curatarr Keep Poster` label), so napalm and fresh posters won't replace it. Untick that to leave it unprotected.
  - Titles with Curatarr ribbons or badges get them redrawn on the new poster.

## 0.17.0

- **Unmatched titles:** a new page in the left menu that finds movies and shows not tied to IMDb, TMDB or TVDB, such as fan edits. They're sorted into two groups:
  - **Not matched:** Plex has no metadata match at all. Its poster is the one you uploaded or the one in its folder.
  - **No IMDb/TMDB IDs:** matched in Plex, but not to an IMDb, TMDB or TVDB entry. A fan edit matched to the wrong title shows up here.
  - Each title shows its poster, library and file name, with **Keep poster** and **Open in Plex**, which is where you fix a match.
  - Filter by library, kind and whether the poster is kept, or search by title, year or file name. **Keep posters for all shown** protects everything listed at once.
  - Totals at the top. The scan is cached for 10 minutes; **Scan again** refreshes it.
- **Keep poster** adds the Plex label `Curatarr Keep Poster`. Napalm and the fresh-poster option never change a poster with that label, and napalm counts those titles as "kept". Ribbons and badges are still drawn on the poster. The label works on any title, not just ones on this page.

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
