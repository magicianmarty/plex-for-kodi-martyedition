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

    def __init__(self, videoResolution="", audioProfile="", audioChannels=""):
        self._data = {"videoResolution": videoResolution, "audioProfile": audioProfile,
                      "audioChannels": audioChannels}

    def get(self, key, default=None):
        return self._data.get(key, default)


class PlainMedium(object):
    """Some callers hand back plain attributes; both shapes have to work."""

    def __init__(self, videoResolution="", audioProfile="", audioChannels=""):
        self.videoResolution = videoResolution
        self.audioProfile = audioProfile
        self.audioChannels = audioChannels


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

    def test_ordinary_media_still_says_something_useful(self):
        """An HD stereo film is not special, but "HD 2.0" is worth knowing."""
        item = FakeItem(media=[FakeMedium(videoResolution="1080", audioChannels="2")])
        self.assertEqual({badges.HD, badges.CHANNELS}, badges.fromMedia(item))
        self.assertEqual(["HD", "2.0"],
                         [badges.label(b, item) for b in badges.ordered(badges.fromMedia(item))])

    def test_the_resolution_tiers_the_server_actually_uses(self):
        """Live values off a real library: sd, 480, 576, 720, 1080, 4k."""
        for resolution, expected in (("4k", badges.UHD), ("1080", badges.HD),
                                     ("720", badges.HD), ("576", badges.SD),
                                     ("480", badges.SD), ("sd", badges.SD)):
            item = FakeItem(media=[FakeMedium(videoResolution=resolution)])
            self.assertIn(expected, badges.fromMedia(item), resolution)

    def test_only_one_resolution_tier_survives(self):
        """Two versions of a film must not badge it both 4K and SD."""
        item = FakeItem(media=[FakeMedium(videoResolution="4k"),
                               FakeMedium(videoResolution="sd")])
        found = badges.fromMedia(item)
        self.assertIn(badges.UHD, found)
        self.assertNotIn(badges.SD, found)
        self.assertNotIn(badges.HD, found)

    def test_channel_layouts_read_the_way_people_say_them(self):
        for count, expected in (("2", "2.0"), ("6", "5.1"), ("8", "7.1"),
                                ("1", "1.0"), ("7", "6.1")):
            item = FakeItem(media=[FakeMedium(audioChannels=count)])
            self.assertEqual(expected, badges.label(badges.CHANNELS, item), count)

    def test_no_channel_count_means_no_chip(self):
        item = FakeItem(media=[FakeMedium(videoResolution="1080")])
        self.assertNotIn(badges.CHANNELS, badges.fromMedia(item))

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


class ShowSectionTest(KodiTestCase):
    """
    Badging a series. A series carries no Media at all - its episodes do - and
    the server confirms it: a TV section answers dovi=1 with nothing, but
    type=4&dovi=1 with every matching episode. So the question is asked of the
    episodes and answered about the series.
    """

    def episodes(self, *rows):
        return "<MediaContainer>{0}</MediaContainer>".format("".join(
            '<Video ratingKey="{0}" grandparentRatingKey="{1}"/>'.format(ep, show)
            for ep, show in rows))

    def setUp(self):
        KodiTestCase.setUp(self)
        metadata = ("<MediaContainer><Video ratingKey='900'><Media><Part>"
                    "<Stream streamType='1' DOVIProfile='8'/></Part></Media></Video>"
                    "</MediaContainer>")
        # hdr and resolution answer about the series; dovi, atmos and
        # audioLayout only about the episodes - so the fakes mirror that.
        self.server = FakeServer({
            "dovi=1": self.episodes(("900", "7"), ("901", "7")),
            "hdr=1": listing("7"),
            "atmos=1": self.episodes(("910", "8")),
            "resolution=4k": listing("9"),
            "resolution=1080": listing("8"),
            "audioLayout=7%2E1": self.episodes(("930", "9")),
            "audioLayout=5%2E1": self.episodes(("940", "8")),
            "/library/metadata/": metadata,
        })
        section = FakeSection(self.server)
        section.TYPE = "show"
        self.sectionBadges = badges.SectionBadges(section)
        self.sectionBadges.load()

    def test_each_filter_is_asked_at_the_level_that_answers_it(self):
        """
        Found by asking a real server: resolution=1080 returns 64 shows, but
        audioLayout=7.1 returns nothing at series level and 39 episodes at
        episode level.
        """
        episode_level = [p for p, _ in self.server.queries if "type=4" in p]
        series_level = [p for p, _ in self.server.queries if "type=4" not in p
                        and "/library/metadata/" not in p]

        self.assertTrue(all("dovi" in p or "atmos" in p or "audioLayout" in p
                            for p in episode_level), episode_level)
        self.assertTrue(all("hdr" in p or "resolution" in p for p in series_level),
                        series_level)

    def test_a_series_inherits_what_its_episodes_have(self):
        self.assertEqual({badges.DV, badges.HDR}, self.sectionBadges.of(FakeItem("7")))
        self.assertEqual({badges.ATMOS, badges.HD, badges.CHANNELS},
                         self.sectionBadges.of(FakeItem("8")))
        self.assertEqual({badges.UHD, badges.CHANNELS}, self.sectionBadges.of(FakeItem("9")))

    def test_a_series_gets_a_channel_layout_too(self):
        """A TV shelf where only the rare shows badge looks broken next to films."""
        self.assertEqual("7.1", self.sectionBadges.label(badges.CHANNELS, FakeItem("9")))
        self.assertEqual("5.1", self.sectionBadges.label(badges.CHANNELS, FakeItem("8")))

    def test_the_best_layout_a_series_has_is_the_one_shown(self):
        self.assertNotEqual("5.1", self.sectionBadges.label(badges.CHANNELS, FakeItem("9")))

    def test_a_series_is_one_resolution_tier_not_several(self):
        found = self.sectionBadges.of(FakeItem("9"))
        self.assertIn(badges.UHD, found)
        self.assertNotIn(badges.HD, found)

    def test_a_series_with_nothing_special_gets_nothing(self):
        self.assertEqual(set(), self.sectionBadges.of(FakeItem("99")))

    def test_the_dolby_vision_profile_is_read_off_one_episode(self):
        """One sample episode per series, not one request per episode."""
        self.assertEqual("DV8", self.sectionBadges.label(badges.DV, FakeItem("7")))
        metadata = [p for p, _ in self.server.queries if "/library/metadata/" in p]
        self.assertEqual(1, len(metadata))
        self.assertIn("900", metadata[0])

    def test_a_movie_section_still_asks_about_items(self):
        server = FakeServer({"dovi=1": listing("11"), "hdr=1": listing()})
        movies = badges.SectionBadges(FakeSection(server))
        movies.load()
        self.assertEqual([], [p for p, _ in server.queries if "type=4" in p])
        self.assertEqual({badges.DV}, movies.of(FakeItem("11")))


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
        A 4K DV Atmos disc qualifies for six - The Abyss on the real server
        does - and even three is a lot on a small poster. The rare things win:
        nobody needs telling that a Dolby Vision disc is also HD.
        """
        everything = {badges.DV, badges.ATMOS, badges.HDR, badges.DTSX,
                      badges.UHD, badges.HD, badges.CHANNELS}
        shown = badges.ordered(everything)
        self.assertEqual(badges.MAX_SHOWN, len(shown))
        self.assertEqual([badges.DV, badges.ATMOS, badges.DTSX], shown)

    def test_every_badge_can_produce_a_label(self):
        item = FakeItem(media=[FakeMedium(audioChannels="6")])
        for badge in badges.ORDER:
            self.assertTrue(badges.label(badge, item), badge)
