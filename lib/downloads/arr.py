# coding=utf-8
"""Sonarr and Radarr. Same API, two spellings of "what is it about"."""

from __future__ import absolute_import

from . import model
from .net import ServiceError, Session

SONARR = "sonarr"
RADARR = "radarr"
PROWLARR = "prowlarr"

SECTION_TYPES = {SONARR: "show", RADARR: "movie"}

# The two services are the same API with different nouns; every difference
# between them lives here rather than leaking into the windows.
NOUNS = {
    SONARR: {"item": "series", "id": "seriesId", "guid": "tvdbId",
             "search": "SeriesSearch", "search_ids": "seriesId"},
    RADARR: {"item": "movie", "id": "movieId", "guid": "tmdbId",
             "search": "MoviesSearch", "search_ids": "movieIds"},
}

# trackedDownloadState wins over status: a record can say "completed" while the
# import that actually puts it in your library has not happened yet, and that
# gap is exactly the bit worth showing.
# Being imported. Deliberately not importBlocked or importFailed: those mean
# the service has given up - usually because it cannot match the download to
# anything in its library - and calling that "Importing" tells you something is
# progressing when it will sit there forever.
IMPORT_STATES = ("importpending", "importing")
STUCK_STATES = ("importblocked", "importfailed", "failedpending")

# History is the only place the *arrs say a file actually landed in the library.
# Matched loosely on the event name rather than the numeric id, because Sonarr
# and Radarr do not number their event types identically.
IMPORTED_EVENT = "import"
HISTORY_PAGE = 30

# An interactive search makes the *arr ask every indexer and wait for them, so
# it takes tens of seconds where everything else here takes one. Measured
# against a live Sonarr: 79 releases, well over the default timeout.
SEARCH_TIMEOUT = 120.0


# Sonarr matches on TVDB, Radarr on TMDB. A Plex item carries both, once you
# look past its own guid: plex://movie/... says nothing to an *arr, but the
# Guid children alongside it say tmdb://9387 and tvdb://1317.
GUID_PREFIX = {SONARR: "tvdb", RADARR: "tmdb"}


def lookupTerm(item, flavour):
    """
    What to ask an *arr about a Plex item.

    An id when the item has one, which makes the match exact and needs no
    keyboard; the title only as a last resort, where it is a guess.
    """
    wanted = GUID_PREFIX.get(flavour, "tmdb")
    for guid in getattr(item, "guids", None) or []:
        raw = str(getattr(guid, "id", "") or "")
        if raw.startswith(wanted + "://"):
            return "{0}:{1}".format(wanted, raw.split("://", 1)[1])
    return str(getattr(item, "title", "") or "")


def flavourFor(item):
    """Films go to Radarr, everything else with episodes goes to Sonarr."""
    return RADARR if str(getattr(item, "TYPE", "") or "") == "movie" else SONARR


class ArrClient(object):
    def __init__(self, url, api_key=None, flavour=SONARR, timeout=6.0):
        self.flavour = flavour
        self.api_key = api_key
        headers = {"X-Api-Key": api_key} if api_key else {}
        self.http = Session(url, timeout=timeout, headers=headers)

    @property
    def url(self):
        return self.http.base_url

    def ping(self):
        """
        Answers without a key, which is what makes discovery possible: we can
        tell a Sonarr from an empty port before anyone has typed a secret.
        """
        try:
            data = self.http.request("/ping")
        except ServiceError:
            return False
        return bool(data) and str(data.get("status", "")).lower() == "ok"

    def queue(self):
        # includeUnknown* keeps grabs whose series/movie was since deleted from
        # vanishing off the list while they still occupy the download client.
        params = {
            "pageSize": 100,
            "includeUnknownSeriesItems": "true" if self.flavour == SONARR else None,
            "includeUnknownMovieItems": "true" if self.flavour == RADARR else None,
            "includeSeries": "true" if self.flavour == SONARR else None,
            # Without this the records carry episode ids and no episode, and
            # every row falls back to naming itself after the release file.
            "includeEpisode": "true" if self.flavour == SONARR else None,
            "includeMovie": "true" if self.flavour == RADARR else None,
        }
        params = dict((k, v) for k, v in params.items() if v is not None)
        data = self.http.request("/api/v3/queue", params=params)
        return self._grouped(self._records(data))

    def _grouped(self, records):
        """
        One row per grab, not per episode.

        A season pack arrives as one queue record per episode - ten identical
        rows, same release, same size, same progress - which turns the screen
        into a wall. They share a downloadId, which is the grab they came from.
        """
        order = []
        groups = {}
        for record in records:
            key = record.get("downloadId") or "id:{0}".format(record.get("id"))
            if key not in groups:
                order.append(key)
                groups[key] = []
            groups[key].append(record)

        rows = []
        for key in order:
            members = groups[key]
            row = self._download(members[0])
            if len(members) > 1:
                row.count = len(members)
                row.service_ids = [m.get("id") for m in members if m.get("id")]
                row.subtitle = self._packSubtitle(members)
                # The furthest from finished is the honest headline: a pack
                # with two episodes still downloading is not "importing".
                row.state = max((self._download(m).state for m in members),
                                key=lambda st: model.STATE_ORDER.get(st, 9))
                row.progress = min(self._download(m).progress for m in members)
                etas = [self._download(m).eta for m in members if self._download(m).eta]
                row.eta = max(etas) if etas else None
            rows.append(row)
        return rows

    @staticmethod
    def _packSubtitle(members):
        seasons = sorted({(m.get("episode") or {}).get("seasonNumber")
                          for m in members if m.get("episode")} - {None})
        count = "{0} episodes".format(len(members))
        if len(seasons) == 1:
            return "Season {0}  -  {1}".format(seasons[0], count)
        quality = ((members[0].get("quality") or {}).get("quality") or {}).get("name")
        return "{0}  -  {1}".format(quality, count) if quality else count

    def history(self, since=None):
        """
        What this service has actually imported, newest first.

        The queue tells you what is in flight; only history tells you something
        finished - an entry leaving the queue could equally have been removed,
        blocked or failed, and announcing those as "finished downloading" is
        how you end up not trusting the notifications.
        """
        params = {"page": 1, "pageSize": HISTORY_PAGE, "sortKey": "date",
                  "sortDirection": "descending"}
        if self.flavour == SONARR:
            params["includeSeries"] = "true"
        else:
            params["includeMovie"] = "true"

        data = self.http.request("/api/v3/history", params=params)
        finished = []
        for record in self._records(data):
            if IMPORTED_EVENT not in str(record.get("eventType") or "").lower():
                continue
            at = record.get("date")
            if since and at and at <= since:
                continue
            title, subtitle = self._titles(record)
            finished.append(model.Download(
                key="{0}:history:{1}".format(self.flavour, record.get("id")),
                title=title,
                subtitle=subtitle,
                source=self.flavour,
                state=model.DONE,
                progress=1.0,
                section_type=SECTION_TYPES.get(self.flavour),
                at=at,
            ))
        return finished

    # ---------------------------------------------------------------- writes

    def remove(self, download, from_client=False, blocklist=False):
        """
        Drop a grab from the queue.

        from_client is off by default on purpose: a finished download that only
        needs unpacking should not evaporate because a menu was ambiguous.
        skipRedownload rides along with blocklist=False so removing something
        does not immediately fetch it again.
        """
        ids = getattr(download, "service_ids", None) or (
            [download.service_id] if getattr(download, "service_id", None) else [])
        if not ids:
            raise ServiceError("nothing to remove")

        params = {
            "removeFromClient": "true" if from_client else "false",
            "blocklist": "true" if blocklist else "false",
            "skipRedownload": "false" if blocklist else "true",
        }
        # Every record behind the row, not just the first: one row can be a
        # ten-episode pack, and removing one of ten looks like nothing happened.
        for queue_id in ids:
            self.http.request("/api/v3/queue/{0}".format(queue_id),
                              method="delete", expect_json=False, params=params)
        return True

    def searchAgain(self, download):
        """Ask the service to go looking again for whatever this row is about."""
        parent = getattr(download, "parent_id", None)
        if not parent:
            raise ServiceError("nothing to search for")
        nouns = NOUNS[self.flavour]
        body = {"name": nouns["search"]}
        if nouns["search_ids"].endswith("s"):
            body[nouns["search_ids"]] = [parent]
        else:
            body[nouns["search_ids"]] = parent
        self.http.request("/api/v3/command", method="post", json=body)
        return True

    # ------------------------------------------------- picking a release yourself

    def releases(self, download, season=None):
        """
        What the indexers are actually offering for this thing.

        Slow - the *arr goes and asks every indexer - so it is only ever run
        from an explicit action, never from a poll.
        """
        parent = getattr(download, "parent_id", None)
        if not parent:
            raise ServiceError("nothing to search for")

        params = {NOUNS[self.flavour]["id"]: parent}
        if self.flavour == SONARR and season is not None:
            params["seasonNumber"] = season
        data = self.http.request("/api/v3/release", params=params, timeout=SEARCH_TIMEOUT)

        found = []
        for record in data or []:
            quality = ((record.get("quality") or {}).get("quality") or {}).get("name") or ""
            found.append(model.Release(
                title=record.get("title") or "",
                guid=record.get("guid"),
                indexer_id=record.get("indexerId"),
                size=record.get("size") or 0,
                seeders=record.get("seeders"),
                quality=quality,
                indexer=record.get("indexer") or "",
                protocol=record.get("protocol") or "",
                age=record.get("age"),
                rejected=record.get("rejected"),
                rejections=record.get("rejections") or (),
            ))
        # What is worth taking first: accepted before rejected, then seeders.
        found.sort(key=lambda r: (r.rejected, -(r.seeders or 0)))
        return found

    def grab(self, release):
        """Take this exact release, whatever the *arr would have chosen."""
        if not release.guid:
            raise ServiceError("that release cannot be grabbed")
        return self.http.request("/api/v3/release", method="post",
                                 json={"guid": release.guid, "indexerId": release.indexer_id})

    # ------------------------------------------------------------ adding new

    def lookup(self, term):
        """
        Find something to add. `term` is a title, or "tvdb:1234" / "tmdb:1234",
        which is what makes adding from a Plex watchlist exact rather than a
        fuzzy title match.
        """
        nouns = NOUNS[self.flavour]
        data = self.http.request("/api/v3/{0}/lookup".format(nouns["item"]),
                                 params={"term": term})
        found = []
        for record in data or []:
            found.append(model.Candidate(
                title=record.get("title") or "",
                year=record.get("year"),
                ident=record.get(nouns["guid"]),
                poster=self.poster({nouns["item"]: record}),
                overview=record.get("overview") or "",
                source=self.flavour,
                # lookup only carries an id for things the service already has
                added=bool(record.get("id")),
            ))
        return found

    def profiles(self):
        return [(p.get("id"), p.get("name") or "")
                for p in self.http.request("/api/v3/qualityprofile") or []]

    def rootFolders(self):
        return [(f.get("id"), f.get("path") or "")
                for f in self.http.request("/api/v3/rootfolder") or []]

    def add(self, candidate, profile_id, root_folder, monitor=True, search=True):
        """Add it, and start looking for it."""
        nouns = NOUNS[self.flavour]
        body = {
            "title": candidate.title,
            nouns["guid"]: candidate.ident,
            "qualityProfileId": profile_id,
            "rootFolderPath": root_folder,
            "monitored": monitor,
        }
        if self.flavour == SONARR:
            body["seasonFolder"] = True
            body["addOptions"] = {"monitor": "all" if monitor else "none",
                                  "searchForMissingEpisodes": bool(search)}
        else:
            body["minimumAvailability"] = "released"
            body["addOptions"] = {"searchForMovie": bool(search)}
        return self.http.request("/api/v3/{0}".format(nouns["item"]),
                                 method="post", json=body, ok=(200, 201))

    def poster(self, record):
        """The artwork the *arr already knows about, so rows are not text-only."""
        for owner in (record.get("series") or {}, record.get("movie") or {}):
            for image in owner.get("images") or []:
                if image.get("coverType") == "poster":
                    return image.get("remoteUrl") or image.get("url") or ""
        return ""

    @staticmethod
    def _records(data):
        # v3 answered with a bare list, v4 paginates. Both are still out there.
        if isinstance(data, dict):
            return data.get("records") or []
        return data or []

    def _download(self, record):
        size = record.get("size") or 0
        left = record.get("sizeleft")
        if left is None:
            left = size
        progress = (size - left) / float(size) if size else 0.0

        title, subtitle = self._titles(record)
        state, message = self._state(record)

        nouns = NOUNS[self.flavour]
        return model.Download(
            poster=self.poster(record),
            service_id=record.get("id"),
            parent_id=record.get(nouns["id"]),
            key="{0}:{1}".format(self.flavour, record.get("id") or record.get("downloadId") or title),
            title=title,
            subtitle=subtitle,
            source=self.flavour,
            state=state,
            progress=progress,
            size=size,
            eta=model.parseTimeleft(record.get("timeleft")),
            message=message,
            section_type=SECTION_TYPES.get(self.flavour),
        )

    def _titles(self, record):
        """
        The release name is unreadable across a room
        ('Show.S03E04.2160p.WEB-DL.DV.HDR...'), so prefer what it is actually
        about and keep the release out of the way.
        """
        series = record.get("series") or {}
        movie = record.get("movie") or {}
        episode = record.get("episode") or {}
        release = record.get("title") or ""

        if series.get("title"):
            subtitle = ""
            if episode:
                subtitle = "S{0:02d}E{1:02d}".format(episode.get("seasonNumber") or 0,
                                                     episode.get("episodeNumber") or 0)
                if episode.get("title"):
                    subtitle = "{0} - {1}".format(subtitle, episode["title"])
            # The release name is the last resort, not the second: it is
            # unreadable from a sofa.
            return series["title"], subtitle or self._quality(record) or release
        if movie.get("title"):
            year = movie.get("year")
            return movie["title"], str(year) if year else release
        if release:
            title, detail = model.prettifyRelease(release)
            return title or release, detail
        return "Unknown", ""

    @staticmethod
    def _quality(record):
        return ((record.get("quality") or {}).get("quality") or {}).get("name") or ""

    @staticmethod
    def _state(record):
        status = str(record.get("status") or "").lower()
        tracked = str(record.get("trackedDownloadState") or "").lower()
        health = str(record.get("trackedDownloadStatus") or "").lower()
        message = record.get("errorMessage") or ""

        if not message:
            for entry in record.get("statusMessages") or []:
                messages = entry.get("messages") or []
                if messages:
                    message = messages[0]
                    break

        if tracked in STUCK_STATES:
            state = model.FAILED
            if not message:
                message = "The service could not import this"
        elif tracked in IMPORT_STATES:
            state = model.IMPORTING
        elif status in ("paused", "delay"):
            state = model.PAUSED
        elif status in ("queued", "delayed"):
            state = model.QUEUED
        elif status in ("completed",) and tracked in ("imported",):
            state = model.DONE
        elif status == "warning" or health == "warning":
            state = model.STALLED
        else:
            state = model.DOWNLOADING

        if health == "error" or status == "failed":
            state = model.FAILED

        return state, message
