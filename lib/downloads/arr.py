# coding=utf-8
"""Sonarr and Radarr. Same API, two spellings of "what is it about"."""

from __future__ import absolute_import

from . import model
from .net import ServiceError, Session

SONARR = "sonarr"
RADARR = "radarr"
PROWLARR = "prowlarr"

SECTION_TYPES = {SONARR: "show", RADARR: "movie"}

# trackedDownloadState wins over status: a record can say "completed" while the
# import that actually puts it in your library has not happened yet, and that
# gap is exactly the bit worth showing.
IMPORT_STATES = ("importpending", "importing", "importblocked", "importfailed")

# History is the only place the *arrs say a file actually landed in the library.
# Matched loosely on the event name rather than the numeric id, because Sonarr
# and Radarr do not number their event types identically.
IMPORTED_EVENT = "import"
HISTORY_PAGE = 30


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

        return model.Download(
            poster=self.poster(record),
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

        if tracked in IMPORT_STATES:
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
