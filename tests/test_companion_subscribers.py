# coding=utf-8
"""
lib/companion/subscribers.py - keeping controllers told.

Two things here are worth guarding. The first is that playback state is read out
of NowPlayingManager rather than gathered again: it is already tracked there to
report to the server at /:/timeline, and a second source would drift from it and
leave the phone and the screen disagreeing about the position.

The second is the pruning. A subscribed phone is posted to every second, so a
phone that walked out of the house has to be dropped - by timeout, or by
refusing posts - or it holds up the posts to everyone still watching.
"""

from __future__ import absolute_import

from xml.etree import ElementTree

from lib.companion import protocol, subscribers

from .base import KodiTestCase, ensure_plex_interface


class FakePlayQueue(object):
    id = 4242
    selectedId = 7
    version = 3


class FakeTimeline(object):
    """Enough of plexnet's TimelineData for the adapter under test."""

    def __init__(self, state="stopped", item=None, play_queue=None, duration=0):
        self.state = state
        self.itemData = item
        self.playQueue = play_queue
        self.attrs = {"time": "12345"}
        self.duration = duration
        self.controllableStr = "playPause,stop,seekTo"

    def updateControllableStr(self):
        pass

    def get(self, name, default=None):
        return getattr(self, name, default)


ITEM = {
    "key": "/library/metadata/42",
    "ratingKey": "42",
    "guid": "plex://movie/abc",
    "duration": 60000,
}


class TimelineKwargsTest(KodiTestCase):
    def test_a_stopped_timeline_reports_only_that(self):
        data = subscribers._timeline_kwargs(FakeTimeline("stopped", ITEM))
        self.assertEqual({"state": "stopped"}, data)

    def test_a_timeline_with_no_item_is_stopped(self):
        """Guards the window between "playing" and the item being known."""
        data = subscribers._timeline_kwargs(FakeTimeline("playing", None))
        self.assertEqual({"state": "stopped"}, data)

    def test_a_playing_timeline_carries_the_position(self):
        data = subscribers._timeline_kwargs(FakeTimeline("playing", ITEM))
        self.assertEqual("playing", data["state"])
        self.assertEqual("12345", data["time"])
        self.assertEqual(60000, data["duration"])
        self.assertEqual("42", data["ratingKey"])

    def test_the_seek_range_spans_the_item(self):
        """Without it the apps show a scrub bar that cannot be dragged."""
        data = subscribers._timeline_kwargs(FakeTimeline("playing", ITEM))
        self.assertEqual("0-60000", data["seekRange"])

    def test_the_play_queue_is_reported_when_there_is_one(self):
        data = subscribers._timeline_kwargs(
            FakeTimeline("playing", ITEM, play_queue=FakePlayQueue()))
        self.assertEqual(4242, data["playQueueID"])
        self.assertEqual(7, data["playQueueItemID"])
        self.assertEqual("/playQueues/4242", data["containerKey"])

    def test_the_server_identifier_is_carried(self):
        data = subscribers._timeline_kwargs(FakeTimeline("playing", ITEM), "server-uuid")
        self.assertEqual("server-uuid", data["machineIdentifier"])

    def test_controllable_flags_are_passed_on(self):
        data = subscribers._timeline_kwargs(FakeTimeline("playing", ITEM))
        self.assertEqual("playPause,stop,seekTo", data["controllable"])


class BuildTimelinesTest(KodiTestCase):
    """Against the real NowPlayingManager, not a stand-in for it."""

    def setUp(self):
        KodiTestCase.setUp(self)
        ensure_plex_interface()
        from plexnet import plexapp
        plexapp.util.APP.nowplayingmanager.reset()

    def test_all_three_types_come_back(self):
        timelines = subscribers.build_timelines()
        self.assertEqual(set(protocol.TIMELINE_TYPES), set(timelines))

    def test_an_idle_player_is_stopped_everywhere(self):
        for data in subscribers.build_timelines().values():
            self.assertEqual("stopped", data["state"])

    def test_it_follows_what_the_manager_was_told(self):
        """
        updatePlaybackState is what the player itself calls, so driving the
        manager the same way is what proves the two stay in step.
        """
        from plexnet import plexapp
        from plexnet import util as plexnet_util

        manager = plexapp.util.APP.nowplayingmanager
        timeline = manager.timelines["video"]
        timeline.state = "playing"
        timeline.itemData = plexnet_util.AttributeDict(ITEM)
        timeline.attrs["time"] = "9000"

        video = subscribers.build_timelines()["video"]
        self.assertEqual("playing", video["state"])
        self.assertEqual("9000", video["time"])
        self.assertEqual("42", video["ratingKey"])

    def test_the_document_is_valid_xml_with_the_command_id(self):
        container = ElementTree.fromstring(subscribers.timeline_document(command_id=11))
        self.assertEqual("11", container.get("commandID"))
        self.assertEqual(3, len(container.findall("Timeline")))


class SubscriberTest(KodiTestCase):
    def test_the_post_url(self):
        subscriber = subscribers.Subscriber("phone", "10.0.0.5", 32500)
        self.assertEqual("http://10.0.0.5:32500/:/timeline", subscriber.url)

    def test_it_expires_without_renewal(self):
        subscriber = subscribers.Subscriber("phone", "10.0.0.5", 32500)
        self.assertFalse(subscriber.expired)
        subscriber.last_seen = 0
        self.assertTrue(subscriber.expired)

    def test_renewing_resets_the_clock_and_the_command_id(self):
        subscriber = subscribers.Subscriber("phone", "10.0.0.5", 32500, command_id=1)
        subscriber.last_seen = 0
        subscriber.renew(9)
        self.assertFalse(subscriber.expired)
        self.assertEqual(9, subscriber.command_id)


class RegistryTest(KodiTestCase):
    def setUp(self):
        KodiTestCase.setUp(self)
        self.registry = subscribers.SubscriberRegistry()

    def test_add_and_list(self):
        self.registry.add("phone", "10.0.0.5", 32500)
        self.assertEqual(["phone"], [s.uuid for s in self.registry.all()])

    def test_re_subscribing_updates_rather_than_duplicates(self):
        """A phone that changed network keeps its identity but not its address."""
        self.registry.add("phone", "10.0.0.5", 32500, command_id=1)
        self.registry.add("phone", "10.0.0.9", 32501, command_id=5)
        subscriber = self.registry.all()[0]
        self.assertEqual(1, len(self.registry.all()))
        self.assertEqual("10.0.0.9", subscriber.host)
        self.assertEqual(32501, subscriber.port)
        self.assertEqual(5, subscriber.command_id)

    def test_remove(self):
        self.registry.add("phone", "10.0.0.5", 32500)
        self.registry.remove("phone")
        self.assertEqual([], self.registry.all())

    def test_removing_something_absent_is_harmless(self):
        self.registry.remove("never-here")

    def test_prune_drops_only_the_expired(self):
        self.registry.add("stale", "10.0.0.5", 32500)
        self.registry.add("fresh", "10.0.0.6", 32500)
        self.registry.all()[0].last_seen = 0
        stale = [s.uuid for s in self.registry.all() if s.expired][0]

        self.registry.prune()
        remaining = [s.uuid for s in self.registry.all()]
        self.assertNotIn(stale, remaining)
        self.assertEqual(1, len(remaining))

    def test_clear(self):
        self.registry.add("phone", "10.0.0.5", 32500)
        self.registry.clear()
        self.assertEqual([], self.registry.all())


class PusherTest(KodiTestCase):
    def setUp(self):
        KodiTestCase.setUp(self)
        subscribers.REGISTRY.clear()
        self.pusher = subscribers.TimelinePusher("machine-id")
        self._real_post = subscribers.requests.post
        self._real_document = subscribers.timeline_document
        subscribers.timeline_document = lambda **kwargs: "<MediaContainer/>"

    def tearDown(self):
        subscribers.requests.post = self._real_post
        subscribers.timeline_document = self._real_document
        subscribers.REGISTRY.clear()
        KodiTestCase.tearDown(self)

    def test_a_subscriber_is_posted_to(self):
        posted = []
        subscribers.requests.post = lambda url, **kwargs: posted.append(url)
        subscriber = subscribers.REGISTRY.add("phone", "10.0.0.5", 32500)
        self.pusher._push([subscriber])
        self.assertEqual(["http://10.0.0.5:32500/:/timeline"], posted)

    def test_a_refusing_subscriber_is_dropped_after_three_tries(self):
        """
        A closed app leaves its socket refusing, and retrying it forever would
        hold up the posts to everyone else.
        """
        def refuse(url, **kwargs):
            raise IOError("connection refused")

        subscribers.requests.post = refuse
        subscriber = subscribers.REGISTRY.add("phone", "10.0.0.5", 32500)

        for _ in range(subscribers.TimelinePusher.MAX_FAILURES - 1):
            self.pusher._push([subscriber])
        self.assertEqual(1, len(subscribers.REGISTRY.all()))

        self.pusher._push([subscriber])
        self.assertEqual([], subscribers.REGISTRY.all())

    def test_a_recovered_subscriber_keeps_its_place(self):
        outcomes = [IOError("nope"), None]

        def flaky(url, **kwargs):
            outcome = outcomes.pop(0)
            if outcome:
                raise outcome

        subscribers.requests.post = flaky
        subscriber = subscribers.REGISTRY.add("phone", "10.0.0.5", 32500)
        self.pusher._push([subscriber])
        self.pusher._push([subscriber])

        self.assertEqual(0, subscriber.failures)
        self.assertEqual(1, len(subscribers.REGISTRY.all()))

    def test_one_dead_subscriber_does_not_stop_the_others(self):
        posted = []

        def selective(url, **kwargs):
            if "10.0.0.5" in url:
                raise IOError("nope")
            posted.append(url)

        subscribers.requests.post = selective
        dead = subscribers.REGISTRY.add("dead", "10.0.0.5", 32500)
        alive = subscribers.REGISTRY.add("alive", "10.0.0.6", 32500)
        self.pusher._push([dead, alive])
        self.assertEqual(["http://10.0.0.6:32500/:/timeline"], posted)
