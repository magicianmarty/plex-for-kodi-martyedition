# Downloads, in both directions

Today the Downloads screen reads. This is the plan for making it write: clearing
out what you do not want, and putting new things into the stack without leaving
the sofa.

Everything below was checked against a live Sonarr and Radarr, so the endpoints,
the payloads and the costs are real rather than assumed.

## What the services already allow

| Need | Endpoint | Notes |
|---|---|---|
| Drop a grab | `DELETE /api/v3/queue/{id}` | `removeFromClient`, `blocklist`, `skipRedownload` |
| Never grab that release again | same, `blocklist=true` | the *arr then looks for a different one |
| Try again | `POST /api/v3/command` `{name: SeriesSearch \| MoviesSearch}` | |
| Find something to add | `GET /api/v3/series/lookup?term=` / `movie/lookup` | returns title, year, tvdbId/tmdbId, overview, **poster URLs** |
| Where to put it | `GET /api/v3/rootfolder` | one folder here: `/media/media/tv`, 22 TB free |
| How good a copy | `GET /api/v3/qualityprofile` | six here: Any, SD, HD-720p, HD-1080p, Ultra-HD, HD-720p/1080p |
| Add it | `POST /api/v3/series` / `movie` | `addOptions.searchForMissingEpisodes` starts the hunt |
| Pick the release yourself | `GET /api/v3/release?seriesId=` then `POST /api/v3/release` | phase 3 |

## The typing problem decides the design

An API key was bad enough. A search term is worse, and it is the thing that
kills "add from the couch" in every other client. Three ways around it, in the
order they are worth building:

1. **Add from the Plex watchlist.** The client is already a Plex client and the
   watchlist is already a section in it. A watchlist entry carries the TMDB or
   TVDB guid, which is exactly what `lookup` wants - so "download this" on a
   watchlist item needs no typing at all, and no search screen. This is the
   feature; the rest is scaffolding.
2. **Add from what you are already looking at.** A show whose next season is
   missing, an item in Discover: same one-press flow, same guid.
3. **Search by name**, last, for the cases neither covers - with the on-screen
   keyboard, which a phone can drive over JSON-RPC anyway.

## Phase 1 - clearing out  *(built)*

A context menu on a Downloads tile:

- **Remove** - off the queue, files left alone.
- **Remove and blocklist** - and never take that release again; the *arr looks
  for another.
- **Search again** - for the stuck ones.

Rules that matter more than the menu:

- Removing is confirmed, and the prompt says plainly what happens to the files.
  `removeFromClient` stays **off** by default; a 21 GB download that just needs
  extracting should not evaporate because a menu was ambiguous.
- Blocklisting is explained where it is offered, not in a manual.
- Every write is checked for a 2xx and reported. A silent failure here is worse
  than no button, because the row stays on screen and looks like a bug.

Cost: no new window, no skin work. `arr.py` grows three methods, the context
menu grows three entries.

## Phase 2 - adding  *(search built; watchlist next)*

**Search and add** is built: the Add button on the Downloads screen takes a
term, asks both services, shows what they found (marking what is already in
your library), asks for quality and destination once and remembers them, then
adds and searches. It is made of dialogs the add-on already had, which is what
makes the watchlist route below cheap - it arrives at the same code with the
term already known.

**From the watchlist** *(built)*. A "Download" action on a watchlist item.
One correction to the plan above, found by looking: a watchlist row's own guid
is `plex://movie/5d776832...`, which means nothing to an *arr. The ids it needs
are the `Guid` children alongside it - `tmdb://9387`, `tvdb://1317` - which
plexnet already parses into `item.guids`. So the flow is:

1. Read the tmdb/tvdb id off `item.guids`, not the item's own guid.
2. `lookup` by that guid, so the match is exact rather than fuzzy.
3. If it is already in the *arr, say so and offer a search instead of adding twice.
4. Otherwise add it with the remembered profile and root folder, monitored, and
   kick a search.

**The options nobody wants to answer twice.** Quality profile and root folder
are asked once and remembered per service, in settings, with the *arr's own
defaults pre-selected. A second root folder or a deliberate "ask me every time"
setting can come later; with one root folder and one profile it should be a
single press.

**Feedback.** Adding starts a real download on real disks. The confirmation says
what will be searched and where it will land, and the item appears on the
Downloads screen within a poll - which is the honest proof it worked.

## Phase 3 - the rest

- **Interactive search**: list what the indexers have, with size, seeders,
  quality and rejection reasons, and grab one specifically. This is where a
  stuck release gets replaced by a good one.
- **qBittorrent controls**: pause, resume, priority - blocked on credentials
  being configured at all, which they are not yet.
- **Per-item state in the library**: a missing season showing "not on disk" with
  a download action, rather than only being visible from the Downloads screen.

## Shape of the code

`lib/downloads/arr.py` stays the only thing that talks to Sonarr and Radarr, and
stays free of Kodi imports, so all of this is testable against recorded answers
the way the queue and history already are. The differences between the two
services - `series` vs `movie`, `tvdbId` vs `tmdbId`, monitor options - belong
in that module and nowhere else.

The UI reuses what exists: `dropdown` for the context menu, `optionsdialog` for
confirmations, the Downloads window's own tile grid for search results. Only
phase 3's interactive search needs a new list layout.

## What will bite

- **Adding is not undoable from here.** Remove-from-*arr is another write, and
  files already downloaded are the user's problem. Confirmations have to be
  honest about that.
- **The two services diverge** more than the queue suggests. Payloads, monitor
  options and the shape of `lookup` results all differ; the abstraction earns
  its place only if it hides that.
- **A shared server is read-only.** All of this is offered only where the
  services are configured, which is already how the Downloads screen behaves.
