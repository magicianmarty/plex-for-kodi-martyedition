# coding=utf-8
"""
Format badges for library tiles: Dolby Vision, Atmos, DTS:X, HDR, 4K.

Two sources, because the server gives them up in two different ways.

Resolution and audio profile ride along in every library listing, so 4K, Atmos
and DTS:X cost nothing - `audioProfile` literally reads
"dolby truehd + dolby atmos".

Dolby Vision and HDR are not in a listing at all. A listing carries no Stream
elements, and neither includeStreams nor checkFiles changes that, so DOVIPresent
is simply not reachable that way. The server does know - it exposes both as
filters, which is what the quick-filter chips use - so the trick is to ask it
which items match, once per section, and remember the answer.
"""

from __future__ import absolute_import

ATMOS = "atmos"
DTSX = "dtsx"
UHD = "4k"
HDR = "hdr"
DV = "dv"

# Longest first: a tile has room for two or three, and "Dolby Vision" beats
# "4K" for anyone who cares enough to look.
ORDER = (DV, ATMOS, HDR, DTSX, UHD)

LABELS = {DV: "DV", ATMOS: "ATMOS", HDR: "HDR", DTSX: "DTS:X", UHD: "4K"}

# A 4K Dolby Vision Atmos disc earns four of these, which is more than a small
# poster can show; the order above decides which three survive.
MAX_SHOWN = 3

# What the server calls the filters these come from.
FILTERS = {DV: "dovi", HDR: "hdr"}

# A section's worth of keys, capped: past this the request costs more than the
# badges are worth, and a library that size is not curated anyway.
MAX_KEYS = 5000


def fromMedia(item):
    """Badges readable straight off a library listing."""
    found = set()
    media = getattr(item, "media", None) or []
    for medium in media:
        resolution = str(getattr(medium, "videoResolution", "") or "").lower()
        profile = str(getattr(medium, "audioProfile", "") or "").lower()
        if resolution == "4k":
            found.add(UHD)
        if "atmos" in profile:
            found.add(ATMOS)
        if "dts:x" in profile or "dtsx" in profile:
            found.add(DTSX)
    return found


def ordered(badges):
    """The badges worth showing, rarest first, capped to what a tile can hold."""
    return [badge for badge in ORDER if badge in badges][:MAX_SHOWN]


class SectionBadges(object):
    """
    The Dolby Vision and HDR members of one library section.

    Loading is one request per filter and is meant to run off the UI thread.
    Until it has, `of()` simply returns what the listing itself supports, so a
    slow or failed load costs the extra badges and nothing else.
    """

    def __init__(self, section):
        self.section = section
        self.keys = {}
        self.loaded = False

    def load(self):
        if self.loaded or not self.section:
            return self.loaded
        for badge, filter_name in FILTERS.items():
            self.keys[badge] = self._keys(filter_name)
        self.loaded = True
        return True

    def _keys(self, filter_name):
        path = "/library/sections/{0}/all?{1}=1".format(self.section.key, filter_name)
        data = self.section.server.query(path, limit=MAX_KEYS)
        if data is None:
            return set()
        found = set()
        for element in data:
            key = element.attrib.get("ratingKey")
            if key:
                found.add(str(key))
        return found

    def of(self, item):
        """Every badge for one item, listing-derived and server-derived."""
        found = fromMedia(item)
        key = str(getattr(item, "ratingKey", "") or "")
        if key:
            for badge, keys in self.keys.items():
                if key in keys:
                    found.add(badge)
        return found
