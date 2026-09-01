# coding=utf-8
"""
Plex's server-sent event stream.

The fixture is a real recording off PMS 1.43.3 during a scan of a movie
section, trimmed. The proportions in that recording are the whole point:

    1556  activity   one per file scanned, almost all of it noise
       4  status
       2  timeline
       2  ping

so the tests are mostly about what gets *ignored*. Acting on the wrong message
means redrawing the home screen 1500 times during a scan.
"""

from __future__ import absolute_import

import os

from lib import plexevents

from .base import KodiTestCase
from . import FIXTURES_ROOT


def stream():
    path = os.path.join(FIXTURES_ROOT, "plexevents", "scan_stream.txt")
    with open(path, "r", encoding="utf-8") as fp:
        return fp.read().splitlines()


def events():
    return list(plexevents.parseStream(stream()))


class ParseTest(KodiTestCase):
    def test_every_frame_in_a_real_recording_is_read(self):
        names = [name for name, _ in events()]
        self.assertEqual(10, len(names))
        self.assertEqual(5, names.count("activity"))
        self.assertEqual(2, names.count("timeline"))
        self.assertEqual(2, names.count("status"))
        self.assertEqual(1, names.count("ping"))

    def test_a_broken_frame_does_not_end_the_stream(self):
        """A long-lived connection cannot be killed by one odd message."""
        lines = ["event: activity", "data: {not json", "", "event: ping", "data: {}", ""]
        self.assertEqual([("ping", {})], list(plexevents.parseStream(lines)))

    def test_data_without_an_event_name_still_parses(self):
        lines = ["data: {\"StatusNotification\": {\"notificationName\": \"LIBRARY_UPDATE\"}}", ""]
        name, payload = list(plexevents.parseStream(lines))[0]
        self.assertEqual("message", name)
        self.assertIn("StatusNotification", payload)


class MeaningTest(KodiTestCase):
    def read(self, name):
        return [plexevents.readEvent(n, p) for n, p in events() if n == name]

    def test_only_the_end_of_a_section_scan_is_a_refresh(self):
        kinds = [kind for kind, _, _ in self.read("activity")]
        self.assertEqual(["scan"], [k for k in kinds if k])

    def test_the_refresh_carries_the_section_that_changed(self):
        kind, section, _title = [e for e in self.read("activity") if e[0]][0]
        self.assertEqual("scan", kind)
        self.assertEqual("3", section)

    def test_the_scan_progress_firehose_is_ignored(self):
        """1556 of these per scan; every one of them must mean nothing."""
        updates = [e for e in self.read("activity") if e[0] is None]
        self.assertTrue(updates)

    def test_another_kind_of_activity_is_not_a_library_change(self):
        payload = {"ActivityNotification": {"event": "ended", "Activity": {
            "type": "provider.subscriptions.process", "title": "Processing subscriptions"}}}
        self.assertEqual((None, None, None), plexevents.readEvent("activity", payload))

    def test_a_finished_item_is_named_so_it_can_be_announced(self):
        finished = [e for e in self.read("timeline") if e[0]]
        self.assertEqual([("item", "3", "Conan the Barbarian")], finished)

    def test_an_item_still_being_worked_on_is_not_announced(self):
        """state 5 is done; anything less is mid-flight."""
        pending = [e for e in self.read("timeline") if e[0] is None]
        self.assertEqual(1, len(pending))

    def test_a_status_message_is_never_a_refresh(self):
        """
        Watching a live server: LIBRARY_UPDATE fires at the *start* of a scan as
        well as the end, and names no section - refreshing on it would redraw
        everything before anything had changed.
        """
        self.assertEqual([(None, None, None)] * 2, self.read("status"))

    def test_a_ping_is_liveness_and_nothing_else(self):
        self.assertEqual((None, None, None), plexevents.readEvent("ping", {}))


class ListenerTest(KodiTestCase):
    def setUp(self):
        KodiTestCase.setUp(self)
        self.signals = []
        self.listener = plexevents.EventListener(FakeServer(), debounce=0)
        import plexnet.plexapp as plexapp
        plexapp.util.APP.on("library:updated", self.record)
        self.app = plexapp.util.APP

    def tearDown(self):
        self.app.off("library:updated", self.record)
        KodiTestCase.tearDown(self)

    def record(self, **kwargs):
        self.signals.append(kwargs)

    def feed(self):
        for name, payload in events():
            self.listener.handle(name, payload)
        self.listener.flush(force=True)

    def test_a_whole_scan_produces_one_signal_per_section(self):
        """
        Not one per message: importing a season would otherwise redraw the home
        screen once per episode.
        """
        self.feed()
        sections = [str(s["sectionID"]) for s in self.signals]
        self.assertEqual(["3"], sections)

    def test_the_names_of_what_arrived_ride_along(self):
        self.feed()
        named = [s for s in self.signals if s["sectionID"] == "3"][0]
        self.assertEqual(["Conan the Barbarian"], named["titles"])

    def test_nothing_is_sent_while_the_debounce_window_is_open(self):
        listener = plexevents.EventListener(FakeServer(), debounce=60)
        for name, payload in events():
            listener.handle(name, payload)
        listener.flush()
        self.assertEqual([], self.signals)

    def test_the_token_goes_on_the_stream_url(self):
        self.assertIn("/:/eventsource/notifications", self.listener.url)
        self.assertIn("filters=timeline,activity,status", self.listener.url)
        self.assertIn("X-Plex-Token", self.listener.url)


class FakeServer(object):
    name = "VALIANT"

    def buildUrl(self, path, includeToken=False):
        return "http://server:32400{0}{1}".format(
            path, "&X-Plex-Token=xxx" if includeToken else "")
