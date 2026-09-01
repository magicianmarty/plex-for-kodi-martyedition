# coding=utf-8
"""One shape for a download, whatever produced it."""

from __future__ import absolute_import

DOWNLOADING = "downloading"
QUEUED = "queued"
IMPORTING = "importing"
STALLED = "stalled"
PAUSED = "paused"
FAILED = "failed"
DONE = "done"

# What belongs on screen: everything the stack still owes you.
ACTIVE_STATES = (DOWNLOADING, IMPORTING, QUEUED, STALLED, PAUSED, FAILED)

# The order rows are shown in - what is closest to landing goes on top.
STATE_ORDER = {IMPORTING: 0, DOWNLOADING: 1, STALLED: 2, QUEUED: 3, PAUSED: 4, FAILED: 5, DONE: 6}

# qBittorrent's "no idea" eta, and its cousins elsewhere.
UNKNOWN_ETA = 8640000


def formatSize(size):
    if not size:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024 or unit == "TB":
            return "{0:.0f} {1}".format(size, unit) if unit == "B" \
                else "{0:.1f} {1}".format(size, unit)
        size /= 1024.0


def formatEta(seconds):
    """Coarse on purpose: nobody reads seconds off a TV across the room."""
    if seconds is None or seconds <= 0 or seconds >= UNKNOWN_ETA:
        return ""
    if seconds < 60:
        return "{0}s".format(int(seconds))
    if seconds < 3600:
        return "{0}m".format(int(seconds // 60))
    hours, minutes = divmod(int(seconds // 60), 60)
    if hours < 24:
        return "{0}h {1}m".format(hours, minutes) if minutes else "{0}h".format(hours)
    return "{0}d {1}h".format(hours // 24, hours % 24)


def parseTimeleft(value):
    """
    Sonarr/Radarr hand back a timespan, not a number: '00:12:34', and
    '1.02:03:04' once it is over a day.
    """
    if not value or not isinstance(value, str):
        return None
    days = 0
    if "." in value and ":" in value and value.index(".") < value.index(":"):
        head, _, value = value.partition(".")
        try:
            days = int(head)
        except ValueError:
            return None
    parts = value.split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = (int(float(p)) for p in parts)
    except ValueError:
        return None
    return ((days * 24 + hours) * 60 + minutes) * 60 + seconds


class Download(object):
    """
    A single thing the stack is working on.

    `key` has to survive across polls unchanged - it is what tells a finished
    download from a new one, and so what decides whether you get told about it.
    """

    def __init__(self, key, title, source, state=QUEUED, progress=0.0, size=0,
                 eta=None, message="", subtitle="", section_type=None, poster="",
                 at=None):
        self.key = key
        self.title = title
        self.subtitle = subtitle
        self.source = source
        self.state = state
        self.progress = max(0.0, min(1.0, progress or 0.0))
        self.size = size or 0
        self.eta = eta
        self.message = message
        # 'show' or 'movie' where we know it, so a finished item can point at
        # the Plex library it belongs to.
        self.section_type = section_type
        self.poster = poster
        # ISO timestamp for history entries; None for anything still in flight.
        self.at = at

    @property
    def percent(self):
        return int(self.progress * 100)

    @property
    def active(self):
        return self.state in ACTIVE_STATES

    @property
    def sortKey(self):
        return (STATE_ORDER.get(self.state, 9), -self.progress, self.title.lower())

    def etaDisplay(self):
        return formatEta(self.eta)

    def sizeDisplay(self):
        return formatSize(self.size)

    def __repr__(self):
        return "<Download {0} {1} {2}%>".format(self.source, repr(self.title), self.percent)

    def __eq__(self, other):
        return isinstance(other, Download) and other.key == self.key \
            and other.state == self.state and other.percent == self.percent

    def __ne__(self, other):
        return not self.__eq__(other)
