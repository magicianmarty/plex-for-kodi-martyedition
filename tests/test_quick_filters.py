# coding=utf-8
"""
The quick-filter chip bar: Dolby Vision / Dolby Atmos / HDR / 4K / Unplayed.

The chips are the one-click front end to filters that otherwise take a dropdown
dive, so what matters is that a press ends up as the same server filter the
dropdown would have produced, that the state round-trips through
librarySettings, and that the ids stay wired to the skin.

lib/windows/ classes need a real Kodi window manager to instantiate, so these
drive the logic on an uninitialised LibraryWindow with the handful of
attributes it touches filled in - the chip state machine is plain bookkeeping
over boolFilters/filter and never touches a control.
"""

from __future__ import absolute_import

import os
import re

from plexnet import plexlibrary

from .base import KodiTestCase, import_window_module, make_engine

library = import_window_module("lib.windows.library")

# The theme is irrelevant to the chips; test_templates.py renders all of them.
THEME = "modern"

# Every library view the chips ship in. genres and the listviews inherit the
# same bar from library.xml.tpl.
CHIP_WINDOWS = (
    "posters", "posters-small", "posters-compact", "posters-small-compact",
    "squares", "listview-16x9", "listview-square", "genres",
)

VIDEO_SECTIONS = ("movie", "show", "movies_shows")
NON_VIDEO_SECTIONS = ("artist", "photo", "playlists", "collection")


class RecordingSettings(object):
    """Stands in for LibrarySettings, recording what the window persists."""

    def __init__(self):
        self.saved = {}
        self.writes = []

    def setSetting(self, key, value):
        self.saved[key] = value
        self.writes.append((key, value))

    def getSetting(self, key, default=None):
        return self.saved.get(key, default)

    def getItemType(self):
        return None


class FakeSection(object):
    def __init__(self, type_):
        self.TYPE = type_
        self.key = "1"


def make_window(section_type="movie", bool_filters=None, filter_=None):
    window = library.LibraryWindow.__new__(library.LibraryWindow)
    window.section = FakeSection(section_type)
    window.boolFilters = dict(bool_filters or {})
    window.filter = filter_
    window.librarySettings = RecordingSettings()
    window.properties = {}
    window.fills = []
    window.setProperty = lambda key, value: window.properties.__setitem__(key, value)
    window.fill = lambda: window.fills.append(True)

    # MultiWindow.__getattr__ forwards control ids to whichever view window is
    # current; there is none here, so take them off the class they live on.
    for name, value in vars(library.PostersWindow).items():
        if name.endswith("_ID"):
            setattr(window, name, value)
    return window


def chip(key):
    for qf in library.QUICK_FILTERS:
        if qf["key"] == key:
            return qf
    raise AssertionError("no quick filter for {0}".format(key))


def render(target_dir):
    """Render THEME and return {window name: xml text}."""
    engine = make_engine(target_dir)
    engine.apply(THEME, lambda at, steps, message: None)
    out = {}
    for name in engine.TEMPLATES:
        path = os.path.join(engine.target_dir, "script-plex-{0}.xml".format(name))
        with open(path, "r", encoding="utf-8") as fp:
            out[name] = fp.read()
    return out


class QuickFilterDefinitionTest(KodiTestCase):
    def test_ids_are_unique(self):
        ids = [qf["id"] for qf in library.QUICK_FILTERS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(library.QUICK_FILTER_BY_ID,
                         dict((qf["id"], qf) for qf in library.QUICK_FILTERS))

    def test_ids_do_not_collide_with_an_existing_control(self):
        """
        onClick() dispatches on the raw control id. A chip sharing an id with
        one of the view's own buttons would silently steal its press.
        """
        taken = dict((value, name) for name, value in vars(library.PostersWindow).items()
                     if name.endswith("_ID") and isinstance(value, int))
        for qf in library.QUICK_FILTERS:
            self.assertNotIn(qf["id"], taken,
                             "chip {0} reuses {1}".format(qf["label"], taken.get(qf["id"])))

    def test_every_chip_is_fully_specified(self):
        props = set()
        for qf in library.QUICK_FILTERS:
            self.assertIn(qf["kind"], ("bool", "res"))
            self.assertTrue(qf["label"])
            self.assertTrue(qf["prop"].startswith("qf."))
            self.assertNotIn(qf["prop"], props, "duplicate window property")
            props.add(qf["prop"])
            if qf["kind"] == "res":
                self.assertEqual(qf["key"].split(":", 1)[0], "resolution")
                self.assertTrue(qf["key"].split(":", 1)[1])

    def test_the_dropdown_labels_the_same_filters_the_same_way(self):
        """
        The chips and the filter dropdown name the same server filters. Letting
        them drift gives the same filter two names in one window.
        """
        window = make_window()
        for qf in library.QUICK_FILTERS:
            if qf["kind"] != "bool":
                continue
            self.assertEqual(window._filterLabel(qf["key"], "server title"), qf["label"])


class QuickFilterToggleTest(KodiTestCase):
    def test_a_boolean_chip_switches_its_server_filter_on(self):
        window = make_window()
        window.quickFilterClicked(chip("dovi")["id"])

        self.assertEqual(window.boolFilters, {"dovi": True})
        self.assertEqual(window.librarySettings.saved["filter.bools"], {"dovi": True})
        self.assertEqual(window.properties["qf.dovi"], "1")
        self.assertEqual(len(window.fills), 1)

    def test_pressing_it_again_removes_the_key_rather_than_zeroing_it(self):
        """
        Same contract as the dropdown's toggle. A key left behind as False is
        filtered out server-side but would accrete in the persisted settings
        blob and reappear in every later read.
        """
        window = make_window(bool_filters={"dovi": True})
        window.quickFilterClicked(chip("dovi")["id"])

        self.assertEqual(window.boolFilters, {})
        self.assertEqual(window.librarySettings.saved["filter.bools"], {})
        self.assertEqual(window.properties["qf.dovi"], "")

    def test_boolean_chips_stack(self):
        window = make_window()
        for key in ("dovi", "atmos", "hdr", "unwatched"):
            window.quickFilterClicked(chip(key)["id"])

        self.assertEqual(window.boolFilters,
                         {"dovi": True, "atmos": True, "hdr": True, "unwatched": True})

    def test_the_4k_chip_sets_the_resolution_value_filter(self):
        window = make_window()
        window.quickFilterClicked(chip("resolution:4k")["id"])

        self.assertEqual(window.filter["type"], "resolution")
        self.assertEqual(window.filter["sub"]["val"], "4k")
        self.assertEqual(window.filter["sub"]["display"], "4K")
        self.assertTrue(window.filter["display"])
        self.assertEqual(window.librarySettings.saved["filter"], window.filter)
        self.assertEqual(window.properties["qf.4k"], "1")

    def test_the_4k_chip_clears_the_filter_again(self):
        window = make_window()
        window.quickFilterClicked(chip("resolution:4k")["id"])
        window.quickFilterClicked(chip("resolution:4k")["id"])

        self.assertIsNone(window.filter)
        self.assertIsNone(window.librarySettings.saved["filter"])
        self.assertEqual(window.properties["qf.4k"], "")

    def test_4k_replaces_another_value_filter(self):
        """Only one value filter can be active, so 4K takes over from genre."""
        window = make_window(filter_={"type": "genre", "display": "Genre",
                                      "sub": {"val": "1", "display": "Horror"}})
        window.quickFilterClicked(chip("resolution:4k")["id"])

        self.assertEqual(window.filter["type"], "resolution")
        self.assertEqual(window.properties["qf.4k"], "1")

    def test_a_different_resolution_leaves_the_4k_chip_off(self):
        window = make_window(filter_={"type": "resolution", "display": "Resolution",
                                      "sub": {"val": "1080", "display": "1080p"}})
        window._updateQuickFilterChips()

        self.assertEqual(window.properties["qf.4k"], "")

    def test_booleans_and_4k_are_independent(self):
        window = make_window()
        window.quickFilterClicked(chip("dovi")["id"])
        window.quickFilterClicked(chip("resolution:4k")["id"])

        self.assertEqual(window.boolFilters, {"dovi": True})
        self.assertEqual(window.filter["sub"]["val"], "4k")
        self.assertEqual(window.properties["qf.dovi"], "1")
        self.assertEqual(window.properties["qf.4k"], "1")

    def test_every_chip_persists_and_refills(self):
        for qf in library.QUICK_FILTERS:
            window = make_window()
            window.quickFilterClicked(qf["id"])
            self.assertEqual(len(window.fills), 1, qf["label"])
            self.assertTrue(window.librarySettings.writes, qf["label"])
            self.assertEqual(window.properties[qf["prop"]], "1", qf["label"])

    def test_an_unknown_control_id_does_nothing(self):
        window = make_window(bool_filters={"dovi": True})
        window.quickFilterClicked(999)

        self.assertEqual(window.boolFilters, {"dovi": True})
        self.assertEqual(window.librarySettings.writes, [])
        self.assertEqual(window.fills, [])

    def test_onclick_routes_chip_presses_and_nothing_else(self):
        window = make_window()
        pressed = []
        window.quickFilterClicked = pressed.append
        window.filter1ButtonClicked = lambda: pressed.append("filter1")

        for qf in library.QUICK_FILTERS:
            library.LibraryWindow.onClick(window, qf["id"])
        library.LibraryWindow.onClick(window, window.FILTER1_BUTTON_ID)

        self.assertEqual(pressed, [qf["id"] for qf in library.QUICK_FILTERS] + ["filter1"])


class QuickFilterDisplayTest(KodiTestCase):
    def test_chips_are_offered_on_video_sections(self):
        for type_ in VIDEO_SECTIONS:
            window = make_window(section_type=type_)
            window._updateQuickFilterChips()
            self.assertEqual(window.properties["quickfilters.available"], "1", type_)

    def test_chips_stay_hidden_everywhere_else(self):
        for type_ in NON_VIDEO_SECTIONS:
            window = make_window(section_type=type_)
            window._updateQuickFilterChips()
            self.assertEqual(window.properties["quickfilters.available"], "", type_)

    def test_updating_the_filter_display_paints_the_chips(self):
        window = make_window(bool_filters={"atmos": True})
        window.updateFilterDisplay()

        self.assertEqual(window.properties["qf.atmos"], "1")
        self.assertEqual(window.properties["qf.dovi"], "")
        self.assertIn("Dolby Atmos", window.properties["filter1.display"])

    def test_clearing_the_filters_clears_every_chip(self):
        window = make_window(bool_filters={"dovi": True, "hdr": True},
                             filter_={"type": "resolution", "display": "Resolution",
                                      "sub": {"val": "4k", "display": "4K"}})
        window.clearFilters()

        for qf in library.QUICK_FILTERS:
            self.assertEqual(window.properties[qf["prop"]], "", qf["label"])


class QuickFilterServerArgsTest(KodiTestCase):
    """
    The chips only pay off if their keys are the ones the server understands;
    a typo would filter nothing and look like an empty library.
    """

    def apply(self, section_type, bool_filters, type_=None):
        section = FakeSection(section_type)
        args = {}
        plexlibrary.LibrarySection._applyBoolFilters(section, args, bool_filters, type_)
        return args

    def test_boolean_chips_map_to_flag_arguments(self):
        for key in ("dovi", "atmos", "hdr"):
            self.assertEqual(self.apply("movie", {key: True}), {key: 1})

    def test_unplayed_keeps_its_libtype_translation(self):
        self.assertEqual(self.apply("movie", {"unwatched": True}), {"unwatched": 1})
        self.assertEqual(self.apply("show", {"unwatched": True}), {"show.unwatchedLeaves": 1})
        self.assertEqual(self.apply("show", {"unwatched": True}, type_=4),
                         {"episode.unwatched": 1})

    def test_a_chip_that_is_off_sends_nothing(self):
        self.assertEqual(self.apply("movie", {"dovi": False}), {})


class QuickFilterSkinTest(KodiTestCase):
    """
    The chips are ordinary skin buttons; the generated XML is gitignored and
    only written on a real device, so a broken id or property is invisible
    until someone's library bar stops responding.
    """

    def setUp(self):
        KodiTestCase.setUp(self)
        self.windows = render(self.mktemp())

    def test_every_chip_is_a_button_in_every_library_view(self):
        for name in CHIP_WINDOWS:
            xml = self.windows[name]
            for qf in library.QUICK_FILTERS:
                needle = '<control type="button" id="{0}">'.format(qf["id"])
                self.assertIn(needle, xml, "{0} is missing {1}".format(name, qf["label"]))
                self.assertIn("<label>{0}</label>".format(qf["label"]), xml)
                self.assertIn("Window.Property({0})".format(qf["prop"]), xml)

    def test_no_other_control_claims_a_chip_id(self):
        for name, xml in self.windows.items():
            for qf in library.QUICK_FILTERS:
                found = re.findall(r'<control type="(\w+)" id="{0}">'.format(qf["id"]), xml)
                self.assertTrue(len(found) <= 1, "{0} declares id {1} twice".format(name, qf["id"]))
                if found:
                    self.assertEqual(found[0], "button")

    def test_the_chip_bar_is_gated_on_the_availability_property(self):
        for name in CHIP_WINDOWS:
            self.assertIn("Window.Property(quickfilters.available)", self.windows[name], name)

    def test_no_chips_where_the_window_cannot_use_them(self):
        """
        Sections without the chips (music, photos) run through their own
        windows; a stray chip there would toggle a filter nothing reads.
        """
        for name, xml in self.windows.items():
            if name in CHIP_WINDOWS:
                continue
            for qf in library.QUICK_FILTERS:
                self.assertNotIn('id="{0}">'.format(qf["id"]), xml,
                                 "{0} should not carry chip {1}".format(name, qf["label"]))
