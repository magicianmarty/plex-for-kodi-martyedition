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
HD = "hd"
SD = "sd"
CHANNELS = "channels"
HDR = "hdr"
DV = "dv"

# What the server calls a resolution, and which tier it belongs to. Real values
# from a live library: sd, 480, 576, 720, 1080, 4k.
RESOLUTIONS = {"4k": UHD, "1080": HD, "720": HD, "576": SD, "480": SD, "sd": SD}

# Channel counts as people say them out loud.
CHANNEL_LABELS = {1: "1.0", 2: "2.0", 3: "2.1", 4: "4.0", 5: "4.1",
                  6: "5.1", 7: "6.1", 8: "7.1", 10: "9.1", 12: "11.1"}

# Rarest first, because only two or three chips fit. Resolution tiers are
# mutually exclusive, so an ordinary film shows "HD 5.1" while a 4K Dolby
# Vision disc spends its chips on the things that make it special.
ORDER = (DV, ATMOS, DTSX, HDR, UHD, HD, SD, CHANNELS)

LABELS = {DV: "DV", ATMOS: "ATMOS", HDR: "HDR", DTSX: "DTS:X",
          UHD: "4K", HD: "HD", SD: "SD", CHANNELS: ""}

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
        tier = RESOLUTIONS.get(resolution)
        if tier:
            found.add(tier)
        if "atmos" in profile:
            found.add(ATMOS)
        if "dts:x" in profile or "dtsx" in profile:
            found.add(DTSX)
        if channels(medium):
            found.add(CHANNELS)

    # One resolution tier, the best of them: a file is not both 4K and SD.
    for better, worse in ((UHD, HD), (UHD, SD), (HD, SD)):
        if better in found:
            found.discard(worse)
    return found


def channels(medium):
    """The channel layout as a label, or "" when the server did not say."""
    raw = attr(medium, "audioChannels")
    try:
        count = int(float(raw))
    except (TypeError, ValueError):
        return ""
    return CHANNEL_LABELS.get(count, "{0}.0".format(count) if count else "")


def channelsOf(item):
    for medium in getattr(item, "media", None) or []:
        label_ = channels(medium)
        if label_:
            return label_
    return ""


def label(badge, item=None, profile=None):
    """
    What a chip says. Two of them depend on the item rather than the badge:
    Dolby Vision carries its profile, and the channel chip *is* its value.
    """
    if badge == DV:
        return "DV{0}".format(profile) if profile else LABELS[DV]
    if badge == CHANNELS:
        return channelsOf(item) if item is not None else ""
    return LABELS.get(badge, "")


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
        What a chip says, with the profile this section knows about. Some
        titles match the Dolby Vision filter without the server naming a
        profile, and those stay a plain DV rather than claiming one.
        """
        profile = self.profiles.get(str(getattr(item, "ratingKey", "") or ""))
        return label(badge, item, profile)

    def of(self, item):
        """Every badge for one item, listing-derived and server-derived."""
        found = fromMedia(item)
        key = str(getattr(item, "ratingKey", "") or "")
        if key:
            for badge, keys in self.keys.items():
                if key in keys:
                    found.add(badge)
        return found
