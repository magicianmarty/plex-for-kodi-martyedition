# coding=utf-8
"""
The download services layer: Sonarr/Radarr, qBittorrent, discovery, config.

Everything here is exercised against recorded answers rather than a live
service - the failure that matters is not "the network was down", it is that a
field moved between API versions and the list quietly went empty or wrong.
"""

from __future__ import absolute_import

import json
import os

from lib.downloads import model
from lib.downloads.arr import ArrClient, RADARR, SONARR
from lib.downloads.config import DownloadsConfig
from lib.downloads.manager import DownloadsManager, Snapshot
from lib.downloads.net import ServiceError
from lib.downloads.qbittorrent import QBITTORRENT, QbClient

from .base import KodiTestCase
from . import FIXTURES_ROOT


def fixture(name):
    with open(os.path.join(FIXTURES_ROOT, "downloads", name), "r", encoding="utf-8") as fp:
        return json.load(fp)


class FakeHttp(object):
    """Stands in for net.Session: hands back canned answers, records requests."""

    def __init__(self, answers=None, raises=None, base_url="http://box:8989"):
        self.answers = answers or {}
        self.raises = raises
        self.requests = []
        self.base_url = base_url

    def request(self, path, method="get", expect_json=True, ok=(200,), **kwargs):
        self.requests.append((method, path, kwargs.get("params") or {}))
        if self.raises:
            raise self.raises
        for prefix, answer in self.answers.items():
            if path.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return answer
        raise ServiceError("HTTP 404", status=404)


def sonarr(answers=None, raises=None, history=None):
    client = ArrClient("http://box:8989", "key", flavour=SONARR)
    answers = dict(answers or {})
    answers.setdefault("/api/v3/history", history if history is not None
                       else {"records": []})
    client.http = FakeHttp(answers, raises)
    return client


def radarr(answers=None):
    client = ArrClient("http://box:7878", "key", flavour=RADARR)
    answers = dict(answers or {})
    answers.setdefault("/api/v3/history", {"records": []})
    client.http = FakeHttp(answers)
    return client


def qbittorrent(answers=None, raises=None, credentials=True):
    client = QbClient("http://box:8080", "user" if credentials else None,
                      "pass" if credentials else None)
    client.http = FakeHttp(answers, raises)
    return client


class FormattingTest(KodiTestCase):
    def test_sizes_read_like_sizes(self):
        self.assertEqual("1.5 KB", model.formatSize(1536))
        self.assertEqual("5.0 GB", model.formatSize(5 * 1024 ** 3))
        self.assertEqual("", model.formatSize(0))

    def test_an_eta_is_coarse_on_purpose(self):
        self.assertEqual("45s", model.formatEta(45))
        self.assertEqual("12m", model.formatEta(12 * 60 + 30))
        self.assertEqual("1h 30m", model.formatEta(5400))
        self.assertEqual("2h", model.formatEta(7200))
        self.assertEqual("1d 2h", model.formatEta(26 * 3600))

    def test_an_unknown_eta_shows_nothing_rather_than_a_lie(self):
        """qBittorrent says 8640000 seconds when it means "no idea"."""
        self.assertEqual("", model.formatEta(model.UNKNOWN_ETA))
        self.assertEqual("", model.formatEta(None))
        self.assertEqual("", model.formatEta(0))

    def test_the_arr_timespan_format(self):
        self.assertEqual(754, model.parseTimeleft("00:12:34"))
        self.assertEqual(93784, model.parseTimeleft("1.02:03:04"))
        self.assertIsNone(model.parseTimeleft(None))
        self.assertIsNone(model.parseTimeleft("soon"))


class SonarrQueueTest(KodiTestCase):
    def setUp(self):
        KodiTestCase.setUp(self)
        self.client = sonarr({"/api/v3/queue": fixture("sonarr_queue.json")})
        self.items = self.client.queue()

    def byTitle(self, title):
        return [item for item in self.items if item.title == title][0]

    def test_the_queue_is_read(self):
        """Seven records, but three of them are one grab: four rows."""
        self.assertEqual(5, len(self.items))

    def test_a_season_pack_is_one_row_not_one_per_episode(self):
        """
        Sonarr sends a pack as one record per episode - same release, same
        size, same progress - which put ten identical rows on the screen.
        """
        pack = self.byTitle("Band of Brothers")
        self.assertEqual(3, pack.count)
        self.assertEqual("Season 1  -  3 episodes", pack.subtitle)

    def test_a_pack_is_only_as_finished_as_its_least_finished_episode(self):
        pack = self.byTitle("Band of Brothers")
        self.assertEqual(model.DOWNLOADING, pack.state)
        self.assertEqual(0, pack.percent)
        self.assertEqual("4h", pack.etaDisplay())

    def test_a_lone_record_is_left_alone(self):
        self.assertEqual(1, self.byTitle("Andor").count)

    def test_an_episode_is_named_by_what_it_is_not_by_its_release(self):
        """'Andor.S02E03.2160p.WEB-DL.DV.HDR.x265' is unreadable across a room."""
        item = self.byTitle("Andor")
        self.assertEqual("S02E03 - Harvest", item.subtitle)
        self.assertEqual(SONARR, item.source)
        self.assertEqual("show", item.section_type)

    def test_progress_comes_from_what_is_left(self):
        item = self.byTitle("Andor")
        self.assertEqual(75, item.percent)
        self.assertEqual("12m", item.etaDisplay())
        self.assertEqual(model.DOWNLOADING, item.state)

    def test_a_finished_download_that_is_not_in_plex_yet_reads_as_importing(self):
        """
        The gap between 100% and "it is in your library" is the whole reason to
        look at this screen; 'completed' with an import pending is not done.
        """
        item = self.byTitle("Severance")
        self.assertEqual(model.IMPORTING, item.state)
        self.assertEqual(100, item.percent)

    def test_a_queued_item_is_not_shown_as_downloading(self):
        item = self.byTitle("Foundation")
        self.assertEqual(model.QUEUED, item.state)
        self.assertEqual(0, item.percent)
        self.assertEqual("1d 2h", item.etaDisplay())

    def test_a_failing_grab_carries_its_reason(self):
        item = self.byTitle("Unknown.Release.1080p")
        self.assertEqual(model.FAILED, item.state)
        self.assertIn("eligible for import", item.message)

    def test_a_missing_error_message_falls_back_to_the_status_messages(self):
        record = {"id": 1, "title": "x", "size": 1, "sizeleft": 0,
                  "trackedDownloadStatus": "warning",
                  "statusMessages": [{"title": "t", "messages": ["the real reason"]}]}
        state, message = ArrClient._state(record)
        self.assertEqual(model.STALLED, state)
        self.assertEqual("the real reason", message)

    def test_the_request_asks_for_the_series_and_for_orphans(self):
        """
        Without includeSeries the records carry ids and no titles, and without
        includeUnknownSeriesItems a grab whose series was deleted vanishes from
        the list while still occupying the download client.
        """
        _method, path, params = self.client.http.requests[0]
        self.assertEqual("/api/v3/queue", path)
        self.assertEqual("true", params["includeSeries"])
        self.assertEqual("true", params["includeEpisode"])
        self.assertEqual("true", params["includeUnknownSeriesItems"])

    def test_a_bare_list_still_parses(self):
        """Sonarr v3 answered with a list; v4 paginates. Both are in the wild."""
        records = fixture("sonarr_queue.json")["records"]
        client = sonarr({"/api/v3/queue": records})
        self.assertEqual(5, len(client.queue()))

    def test_keys_are_stable_across_polls(self):
        again = sonarr({"/api/v3/queue": fixture("sonarr_queue.json")}).queue()
        self.assertEqual([i.key for i in self.items], [i.key for i in again])


class RadarrQueueTest(KodiTestCase):
    def test_a_movie_is_named_by_title_and_year(self):
        items = radarr({"/api/v3/queue": fixture("radarr_queue.json")}).queue()
        self.assertEqual(1, len(items))
        self.assertEqual("Dune: Part Two", items[0].title)
        self.assertEqual("2024", items[0].subtitle)
        self.assertEqual("movie", items[0].section_type)
        self.assertEqual(50, items[0].percent)

    def test_the_movie_request_asks_for_the_movie(self):
        client = radarr({"/api/v3/queue": fixture("radarr_queue.json")})
        client.queue()
        _method, _path, params = client.http.requests[0]
        self.assertEqual("true", params["includeMovie"])
        self.assertNotIn("includeSeries", params)


class PingTest(KodiTestCase):
    def test_ping_needs_no_key_which_is_what_makes_discovery_possible(self):
        client = sonarr({"/ping": {"status": "OK"}})
        self.assertTrue(client.ping())

    def test_an_unreachable_service_does_not_raise_out_of_ping(self):
        self.assertFalse(sonarr(raises=ServiceError("unreachable")).ping())

    def test_something_else_answering_on_the_port_is_not_a_sonarr(self):
        self.assertFalse(sonarr({"/ping": {"status": "nope"}}).ping())


class QbittorrentTest(KodiTestCase):
    def setUp(self):
        KodiTestCase.setUp(self)
        self.client = qbittorrent({
            "/api/v2/auth/login": "Ok.",
            "/api/v2/torrents/info": fixture("qbittorrent_torrents.json"),
        })

    def test_torrents_are_normalised(self):
        items = self.client.torrents()
        self.assertEqual(3, len(items))
        self.assertEqual(50, items[0].percent)
        self.assertEqual("45m", items[0].etaDisplay())
        self.assertEqual(QBITTORRENT, items[0].source)

    def test_the_states_that_matter_are_distinguished(self):
        states = dict((item.title, item.state) for item in self.client.torrents())
        self.assertEqual(model.DOWNLOADING, states["Dune.Part.Two.2024.2160p.UHD.BluRay.REMUX.DV"])
        self.assertEqual(model.STALLED, states["Some.Linux.ISO"])
        self.assertEqual(model.PAUSED, states["Paused.Thing"])

    def test_qbittorrent_5_renamed_paused_to_stopped(self):
        item = QbClient._download({"hash": "h", "name": "n", "state": "stoppedDL"})
        self.assertEqual(model.PAUSED, item.state)

    def test_credentials_are_exchanged_for_a_session_before_asking(self):
        self.client.torrents()
        methods = [(m, p) for m, p, _ in self.client.http.requests]
        self.assertEqual(("post", "/api/v2/auth/login"), methods[0])

    def test_an_expired_session_is_retried_once(self):
        class Expiring(FakeHttp):
            def __init__(self):
                FakeHttp.__init__(self)
                self.calls = 0

            def request(self, path, method="get", **kwargs):
                self.requests.append((method, path, kwargs.get("params") or {}))
                if path.startswith("/api/v2/auth/login"):
                    return "Ok."
                self.calls += 1
                if self.calls == 1:
                    raise ServiceError("HTTP 403", status=403)
                return fixture("qbittorrent_torrents.json")

        self.client.http = Expiring()
        self.assertEqual(3, len(self.client.torrents()))

    def test_a_rejected_login_is_not_retried_forever(self):
        client = qbittorrent({"/api/v2/auth/login": "Fails."})
        with self.assertRaises(ServiceError):
            client.torrents()

    def test_a_403_identifies_qbittorrent_rather_than_hiding_it(self):
        """Discovery only needs to know a WebUI is there, not to get in."""
        client = qbittorrent(raises=ServiceError("HTTP 403", status=403))
        self.assertTrue(client.identify())

    def test_nothing_listening_is_not_qbittorrent(self):
        client = qbittorrent(raises=ServiceError("unreachable"))
        self.assertFalse(client.identify())


class ConfigTest(KodiTestCase):
    def config(self, data=None, settings=None):
        settings = settings or {}
        return DownloadsConfig(data or {}, settings=lambda key, default="": settings.get(key, default))

    def test_the_file_alone_is_enough(self):
        config = self.config({"sonarr": {"url": "http://box:8989", "key": "abc"}})
        self.assertTrue(config.enabled("sonarr"))
        clients = config.clients()
        self.assertEqual(1, len(clients))
        self.assertEqual("http://box:8989", clients[0].url)

    def test_a_filled_in_setting_wins_over_the_file(self):
        config = self.config({"sonarr": {"url": "http://old:8989", "key": "abc"}},
                             {"downloads_sonarr_url": "http://new:8989"})
        self.assertEqual("http://new:8989", config.service("sonarr")["url"])

    def test_an_empty_setting_does_not_wipe_the_file(self):
        """The settings screen starts empty; that must not delete provisioning."""
        config = self.config({"sonarr": {"url": "http://box:8989", "key": "abc"}},
                             {"downloads_sonarr_url": "   "})
        self.assertEqual("http://box:8989", config.service("sonarr")["url"])

    def test_a_service_can_be_switched_off_without_deleting_it(self):
        config = self.config({"sonarr": {"url": "http://box:8989", "enabled": False}})
        self.assertFalse(config.enabled("sonarr"))
        self.assertEqual([], config.clients())

    def test_no_url_means_not_configured(self):
        self.assertFalse(self.config({"sonarr": {"key": "abc"}}).enabled("sonarr"))
        self.assertEqual([], self.config().clients())

    def test_qbittorrent_credentials_are_passed_through(self):
        config = self.config({"qbittorrent": {"url": "http://box:8080",
                                              "user": "u", "pass": "p"}})
        client = config.clients()[0]
        self.assertEqual("u", client.username)
        self.assertEqual("p", client.password)

    def test_junk_in_the_file_does_not_take_the_feature_out(self):
        self.assertEqual([], self.config({"sonarr": "not a dict"}).clients())


class ManagerTest(KodiTestCase):
    def manager(self, *clients):
        return DownloadsManager(config=_StubConfig(clients))

    def test_everything_lands_in_one_sorted_list(self):
        mgr = self.manager(sonarr({"/api/v3/queue": fixture("sonarr_queue.json")}),
                           radarr({"/api/v3/queue": fixture("radarr_queue.json")}))
        snapshot = mgr.refresh()

        self.assertEqual(6, len(snapshot.items))
        # Importing first, then downloading, then queued, then failed.
        self.assertEqual(model.IMPORTING, snapshot.items[0].state)
        self.assertEqual(model.FAILED, snapshot.items[-1].state)

    def test_a_dead_service_does_not_empty_the_screen(self):
        """
        A Sonarr that stopped answering must not look like an empty queue -
        that reads as "nothing is downloading", which is a lie.
        """
        working = sonarr({"/api/v3/queue": fixture("sonarr_queue.json")})
        mgr = self.manager(working)
        mgr.refresh()

        working.http.raises = ServiceError("unreachable")
        snapshot = mgr.refresh()

        self.assertEqual(5, len(snapshot.items))
        self.assertTrue(snapshot.stale)
        self.assertIn(SONARR, snapshot.errors)

    def test_one_broken_service_does_not_take_the_others_with_it(self):
        mgr = self.manager(sonarr(raises=ServiceError("unreachable")),
                           radarr({"/api/v3/queue": fixture("radarr_queue.json")}))
        snapshot = mgr.refresh()

        self.assertEqual(1, len(snapshot.items))
        self.assertEqual([SONARR], list(snapshot.errors))

    def test_only_what_the_service_imported_counts_as_finished(self):
        """
        Not "it left the queue": an entry also disappears when it is removed,
        blocked or fails, and announcing those as finished downloading is how
        the notifications stop being believed.
        """
        client = sonarr({"/api/v3/queue": fixture("sonarr_queue.json")},
                        history={"records": []})
        mgr = self.manager(client)
        mgr.refresh()
        mgr.finished()

        client.http.answers["/api/v3/history"] = fixture("sonarr_history.json")
        mgr.refresh()

        finished = mgr.finished()
        self.assertEqual(["Band of Brothers", "Band of Brothers"],
                         [f.title for f in finished])
        self.assertEqual(["S01E06 - Bastogne", "S01E05 - Crossroads"],
                         [f.subtitle for f in finished])

    def test_a_grab_or_a_failure_is_not_a_finish(self):
        client = sonarr({"/api/v3/queue": {"records": []}}, history={"records": []})
        mgr = self.manager(client)
        mgr.refresh()
        client.http.answers["/api/v3/history"] = fixture("sonarr_history.json")
        mgr.refresh()

        self.assertEqual(2, len(mgr.finished()))  # 4 records, 2 of them imports

    def test_the_first_poll_announces_nothing(self):
        """
        Everything in history finished before the add-on started; announcing it
        on launch would be a wall of notifications for last week.
        """
        mgr = self.manager(sonarr({"/api/v3/queue": fixture("sonarr_queue.json")},
                                  history=fixture("sonarr_history.json")))
        mgr.refresh()
        self.assertEqual([], mgr.finished())

    def test_the_same_import_is_not_announced_on_every_poll(self):
        client = sonarr({"/api/v3/queue": {"records": []}}, history={"records": []})
        mgr = self.manager(client)
        mgr.refresh()
        client.http.answers["/api/v3/history"] = fixture("sonarr_history.json")
        mgr.refresh()
        self.assertEqual(2, len(mgr.finished()))

        mgr.refresh()
        self.assertEqual([], mgr.finished())

    def test_the_summary_is_what_the_indicator_shows(self):
        snapshot = Snapshot([
            model.Download("a", "A", SONARR, model.DOWNLOADING, 0.5),
            model.Download("b", "B", SONARR, model.DOWNLOADING, 0.1),
            model.Download("c", "C", SONARR, model.IMPORTING, 1.0),
        ])
        count, percent = snapshot.summary()
        self.assertEqual(3, count)
        self.assertEqual(30, percent)

    def test_nothing_active_is_not_zero_percent_of_something(self):
        self.assertEqual((0, 0), Snapshot([]).summary())


class _StubConfig(object):
    def __init__(self, clients):
        self._clients = list(clients)

    def clients(self):
        return self._clients
