# coding=utf-8
"""
Format badges on library tiles.

Written against what the server actually returns, checked live: a library
listing carries Media attributes but no Stream elements, and neither
includeStreams nor checkFiles changes that. So 4K, Atmos and DTS:X are free,
and Dolby Vision and HDR have to be asked for as filters - which is the same
route the quick-filter chips take.
"""

from __future__ import absolute_import

import xml.etree.ElementTree as ET

from lib import badges

from .base import KodiTestCase


class FakeMedium(object):
    """
    Shaped like plexnet's PlexMedia: __slots__, and the XML attributes reachable
    only through get(). A fake with plain attributes is what let the first
    version ship broken - getattr() answered empty for every item on the box
    while every test passed.
    """
    __slots__ = ("_data",)

    def __init__(self, videoResolution="", audioProfile=""):
        self._data = {"videoResolution": videoResolution, "audioProfile": audioProfile}

    def get(self, key, default=None):
        return self._data.get(key, default)


class PlainMedium(object):
    """Some callers hand back plain attributes; both shapes have to work."""

    def __init__(self, videoResolution="", audioProfile=""):
        self.videoResolution = videoResolution
        self.audioProfile = audioProfile


class FakeItem(object):
    def __init__(self, ratingKey="1", media=None):
        self.ratingKey = ratingKey
        self.media = media or []


class FakeServer(object):
    def __init__(self, answers=None):
        self.answers = answers or {}
        self.queries = []

    def query(self, path, **kwargs):
        self.queries.append((path, kwargs))
        for fragment, xml in self.answers.items():
            if fragment in path:
                return ET.fromstring(xml)
        return None


class FakeSection(object):
    TYPE = "movie"

    def __init__(self, server):
        self.key = "3"
        self.server = server


def listing(*keys):
    return "<MediaContainer>{0}</MediaContainer>".format(
        "".join('<Video ratingKey="{0}" />'.format(k) for k in keys))


class ListingBadgesTest(KodiTestCase):
    def test_a_4k_item_is_marked(self):
        item = FakeItem(media=[FakeMedium(videoResolution="4k")])
        self.assertEqual({badges.UHD}, badges.fromMedia(item))

    def test_atmos_comes_out_of_the_audio_profile(self):
        """The profile reads 'dolby truehd + dolby atmos' verbatim."""
        item = FakeItem(media=[FakeMedium(audioProfile="dolby truehd + dolby atmos")])
        self.assertEqual({badges.ATMOS}, badges.fromMedia(item))

    def test_dts_x_too(self):
        item = FakeItem(media=[FakeMedium(audioProfile="ma + dts:x")])
        self.assertEqual({badges.DTSX}, badges.fromMedia(item))

    def test_plain_media_earns_nothing(self):
        item = FakeItem(media=[FakeMedium(videoResolution="1080", audioProfile="lc")])
        self.assertEqual(set(), badges.fromMedia(item))

    def test_the_attributes_are_read_the_way_plexnet_exposes_them(self):
        """PlexMedia has __slots__: getattr sees nothing, get() sees everything."""
        medium = FakeMedium(videoResolution="4k")
        self.assertEqual("4k", badges.attr(medium, "videoResolution"))
        self.assertEqual("", badges.attr(medium, "nonsense"))

    def test_a_plain_attribute_object_works_too(self):
        item = FakeItem(media=[PlainMedium(videoResolution="4k")])
        self.assertEqual({badges.UHD}, badges.fromMedia(item))

    def test_an_item_with_no_media_does_not_raise(self):
        self.assertEqual(set(), badges.fromMedia(FakeItem()))
        self.assertEqual(set(), badges.fromMedia(object()))

    def test_dolby_vision_is_not_guessable_from_a_listing(self):
        """
        A DV title looks exactly like any other HEVC one in a listing -
        videoProfile is 'main 10' either way - which is why the filters exist.
        """
        item = FakeItem(media=[FakeMedium(videoResolution="4k",
                                          audioProfile="dolby truehd + dolby atmos")])
        self.assertNotIn(badges.DV, badges.fromMedia(item))


class SectionBadgesTest(KodiTestCase):
    def setUp(self):
        KodiTestCase.setUp(self)
        self.server = FakeServer({"dovi=1": listing("11", "12"),
                                  "hdr=1": listing("12", "13")})
        self.section = FakeSection(self.server)
        self.sectionBadges = badges.SectionBadges(self.section)

    def test_the_server_is_asked_once_per_format(self):
        self.sectionBadges.load()
        self.sectionBadges.load()

        paths = [p for p, _ in self.server.queries]
        self.assertEqual(1, len([p for p in paths if "dovi=1" in p]))
        self.assertEqual(1, len([p for p in paths if "hdr=1" in p]))
        # Plus one batch for the Dolby Vision profiles; a second load() adds
        # nothing, which is what makes this cheap enough to do on open.
        self.assertEqual(3, len(paths))

    def test_an_item_gets_both_kinds_of_badge(self):
        self.sectionBadges.load()
        item = FakeItem("12", [FakeMedium(videoResolution="4k")])

        self.assertEqual({badges.DV, badges.HDR, badges.UHD}, self.sectionBadges.of(item))

    def test_an_item_in_neither_set_keeps_its_listing_badges(self):
        self.sectionBadges.load()
        item = FakeItem("99", [FakeMedium(audioProfile="dolby atmos")])

        self.assertEqual({badges.ATMOS}, self.sectionBadges.of(item))

    def test_before_the_answer_arrives_tiles_still_get_what_is_free(self):
        """A slow lookup costs the extra badges, never the tile."""
        item = FakeItem("12", [FakeMedium(videoResolution="4k")])
        self.assertEqual({badges.UHD}, self.sectionBadges.of(item))

    def test_a_server_that_says_nothing_is_survivable(self):
        sectionBadges = badges.SectionBadges(FakeSection(FakeServer()))
        sectionBadges.load()
        self.assertEqual(set(), sectionBadges.of(FakeItem("12")))

    def test_the_request_is_capped(self):
        self.sectionBadges.load()
        self.assertEqual(badges.MAX_KEYS, self.server.queries[0][1].get("limit"))


class ProfileTest(KodiTestCase):
    """
    Dolby Vision profile on the chip. Profile 7 is dual-layer FEL and 8 is
    single-layer; they behave differently on playback, so "DV7" says more than
    "DV". The listing cannot tell you, and one request per title would be 43 -
    /library/metadata takes a comma-separated list instead.
    """

    def setUp(self):
        KodiTestCase.setUp(self)
        metadata = ("<MediaContainer>"
                    "<Video ratingKey='11'><Media><Part>"
                    "<Stream streamType='1' DOVIPresent='1' DOVIProfile='7'/>"
                    "</Part></Media></Video>"
                    "<Video ratingKey='12'><Media><Part>"
                    "<Stream streamType='1' DOVIPresent='1' DOVIProfile='8'/>"
                    "</Part></Media></Video>"
                    "<Video ratingKey='13'><Media><Part>"
                    "<Stream streamType='1'/>"
                    "</Part></Media></Video>"
                    "</MediaContainer>")
        self.server = FakeServer({"dovi=1": listing("11", "12", "13"),
                                  "hdr=1": listing(),
                                  "/library/metadata/": metadata})
        self.sectionBadges = badges.SectionBadges(FakeSection(self.server))
        self.sectionBadges.load()

    def test_the_profile_rides_on_the_chip(self):
        self.assertEqual("DV7", self.sectionBadges.label(badges.DV, FakeItem("11")))
        self.assertEqual("DV8", self.sectionBadges.label(badges.DV, FakeItem("12")))

    def test_a_dv_title_with_no_profile_stays_a_plain_dv(self):
        """Some titles match the filter without the server naming a profile."""
        self.assertEqual("DV", self.sectionBadges.label(badges.DV, FakeItem("13")))

    def test_the_whole_section_costs_one_extra_request(self):
        metadata = [p for p, _ in self.server.queries if "/library/metadata/" in p]
        self.assertEqual(1, len(metadata))
        self.assertIn("11,12,13", metadata[0])

    def test_other_badges_are_unaffected(self):
        self.assertEqual("ATMOS", self.sectionBadges.label(badges.ATMOS, FakeItem("11")))


class SlotTest(KodiTestCase):
    """
    The skin draws three chips at fixed positions, so the code decides which
    badge goes in which slot. Anything below the poster collides with the
    title, which is what the first attempt did.
    """

    def slots(self, found):
        shown = badges.ordered(found)
        return [badges.LABELS[shown[i]] if len(shown) > i else ''
                for i in range(badges.MAX_SHOWN)]

    def test_the_rarest_badge_takes_the_first_chip(self):
        self.assertEqual(["DV", "ATMOS", "4K"],
                         self.slots({badges.UHD, badges.ATMOS, badges.DV}))

    def test_unused_chips_are_empty_so_the_skin_hides_them(self):
        self.assertEqual(["4K", "", ""], self.slots({badges.UHD}))

    def test_nothing_at_all_fills_no_chips(self):
        self.assertEqual(["", "", ""], self.slots(set()))


class OrderTest(KodiTestCase):
    def test_the_rarest_format_leads(self):
        """Three badges is already a lot on a poster; DV earns the front."""
        self.assertEqual([badges.DV, badges.ATMOS, badges.UHD],
                         badges.ordered({badges.UHD, badges.DV, badges.ATMOS}))

    def test_a_tile_never_shows_more_than_it_can_fit(self):
        """
        A 4K DV Atmos disc qualifies for four - The Abyss on the real server
        does - and four does not fit on a small poster.
        """
        everything = {badges.DV, badges.ATMOS, badges.HDR, badges.DTSX, badges.UHD}
        shown = badges.ordered(everything)
        self.assertEqual(badges.MAX_SHOWN, len(shown))
        self.assertEqual([badges.DV, badges.ATMOS, badges.HDR], shown)

    def test_every_badge_has_a_label(self):
        for badge in badges.ORDER:
            self.assertTrue(badges.LABELS.get(badge))
