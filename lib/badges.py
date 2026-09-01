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

# Plex takes a comma-separated list of rating keys on /library/metadata, which
# is how the Dolby Vision profiles come back in one request rather than 43.
PROFILE_BATCH = 150


def attr(medium, name):
    """
    One media attribute, however this object chooses to expose it.

    plexnet's PlexMedia defines __slots__ and keeps the XML attributes in a
    dict behind get() - so getattr() on it always answers empty, silently,
    which is exactly how this shipped once already.
    """
    getter = getattr(medium, "get", None)
    if callable(getter):
        value = getter(name)
        if value is not None:
            return str(value)
    return str(getattr(medium, name, "") or "")


def fromMedia(item):
    """Badges readable straight off a library listing."""
    found = set()
    media = getattr(item, "media", None) or []
    for medium in media:
        resolution = attr(medium, "videoResolution").lower()
        profile = attr(medium, "audioProfile").lower()
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
        # {ratingKey: "7"} - which Dolby Vision profile, where the server says.
        self.profiles = {}
        self.loaded = False

    def load(self):
        if self.loaded or not self.section:
            return self.loaded
        for badge, filter_name in FILTERS.items():
            self.keys[badge] = self._keys(filter_name)
        self._loadProfiles()
        self.loaded = True
        return True

    def _loadProfiles(self):
        """
        Which Dolby Vision profile each DV title is.

        Profile matters here: 7 is dual-layer FEL, 8 is single-layer, and they
        behave differently on playback - so "DV7" is worth more than "DV". The
        listing cannot say, and asking per item would be one request each, but
        /library/metadata takes a comma-separated list, so the whole section
        costs one round trip.
        """
        keys = sorted(self.keys.get(DV) or ())
        for start in range(0, len(keys), PROFILE_BATCH):
            batch = keys[start:start + PROFILE_BATCH]
            data = self.section.server.query("/library/metadata/{0}".format(",".join(batch)))
            if data is None:
                continue
            for video in data:
                key = video.attrib.get("ratingKey")
                if not key:
                    continue
                for stream in video.iter("Stream"):
                    profile = stream.attrib.get("DOVIProfile")
                    if profile:
                        self.profiles[str(key)] = str(profile)
                        break

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

    def label(self, badge, item):
        """
        What a chip says. Dolby Vision carries its profile when the server
        knows it - some titles match the filter without one, and those stay a
        plain DV rather than claiming a profile we did not see.
        """
        if badge != DV:
            return LABELS[badge]
        profile = self.profiles.get(str(getattr(item, "ratingKey", "") or ""))
        return "DV{0}".format(profile) if profile else LABELS[DV]

    def of(self, item):
        """Every badge for one item, listing-derived and server-derived."""
        found = fromMedia(item)
        key = str(getattr(item, "ratingKey", "") or "")
        if key:
            for badge, keys in self.keys.items():
                if key in keys:
                    found.add(badge)
        return found
