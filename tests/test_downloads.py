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

from lib.downloads import arr, model
from lib.downloads.arr import ArrClient, RADARR, SONARR
from lib.downloads.config import DownloadsConfig
from lib.downloads.manager import DownloadsManager, Snapshot
from lib.downloads.net import ServiceError
from lib.downloads.qbittorrent import QBITTORRENT, QbClient

from .base import KodiTestCase, import_window_module
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
        self.requests.append((method, path, kwargs.get("json",
                                                       kwargs.get("params",
                                                                  kwargs.get("data")) or {})))
        if self.raises:
            raise self.raises
        # Longest prefix wins, so /api/v3/series/lookup is not answered by the
        # entry for /api/v3/series.
        for prefix in sorted(self.answers, key=len, reverse=True):
            if path.startswith(prefix):
                answer = self.answers[prefix]
                if isinstance(answer, Exception):
                    raise answer
                return answer
        if method != "get":
            return {}          # a write the service accepted and said nothing about
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


class ReleaseNameTest(KodiTestCase):
    """
    What a row looks like when the service knows nothing about the item - a
    grab whose series was removed. It is the least readable row on the screen,
    so it gets the most help.
    """

    def test_a_scene_name_becomes_a_title_and_a_spec(self):
        title, detail = model.prettifyRelease(
            "House.Of.The.Dragon.S02.2160p.UHD.BluRay.REMUX.DV.HDR10.TrueHD.7.1")
        self.assertEqual("House Of The Dragon", title)
        self.assertTrue(detail.startswith("S02 2160p"))

    def test_a_film_splits_on_its_year(self):
        title, detail = model.prettifyRelease("Conan.the.Barbarian.1982.2160p.UHD.BluRay")
        self.assertEqual("Conan the Barbarian", title)
        self.assertTrue(detail.startswith("1982"))

    def test_something_unparseable_is_left_readable(self):
        title, detail = model.prettifyRelease("some_odd_release")
        self.assertEqual("some odd release", title)
        self.assertEqual("", detail)

    def test_a_name_that_is_all_spec_keeps_its_name(self):
        title, _detail = model.prettifyRelease("2160p.BluRay")
        self.assertEqual("2160p BluRay", title)

    def test_the_queue_uses_it_when_the_service_knows_nothing(self):
        client = sonarr({"/api/v3/queue": {"records": [
            {"id": 1, "size": 100, "sizeleft": 50, "status": "downloading",
             "title": "House.Of.The.Dragon.S02.2160p.UHD.BluRay.REMUX"}]}})
        item = client.queue()[0]
        self.assertEqual("House Of The Dragon", item.title)
        self.assertIn("2160p", item.subtitle)


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
        # No series known, so the row is named from the release: "Unknown
        # Release" rather than "Unknown.Release.1080p".
        item = self.byTitle("Unknown Release")
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


class WriteBackTest(KodiTestCase):
    """
    Everything here changes somebody's library, so the exact request matters
    more than usual - and the defaults matter most of all.
    """

    def setUp(self):
        KodiTestCase.setUp(self)
        self.client = sonarr()
        self.item = model.Download("k", "Andor", SONARR, service_id=42, parent_id=7)

    def sent(self):
        return self.client.http.requests[0]

    def test_removing_leaves_the_files_alone(self):
        """
        A finished download that only needs unpacking must not evaporate
        because a menu was ambiguous - so removeFromClient is off unless asked.
        """
        self.client.remove(self.item)

        method, path, params = self.sent()
        self.assertEqual(("delete", "/api/v3/queue/42"), (method, path))
        self.assertEqual("false", params["removeFromClient"])
        self.assertEqual("false", params["blocklist"])

    def test_removing_without_blocklisting_does_not_re_grab_it(self):
        """Otherwise the *arr fetches the same broken release straight back."""
        self.client.remove(self.item)
        self.assertEqual("true", self.sent()[2]["skipRedownload"])

    def test_blocklisting_asks_for_a_different_release(self):
        self.client.remove(self.item, blocklist=True)
        params = self.sent()[2]
        self.assertEqual("true", params["blocklist"])
        self.assertEqual("false", params["skipRedownload"])

    def test_a_row_with_no_service_id_cannot_be_removed(self):
        with self.assertRaises(ServiceError):
            self.client.remove(model.Download("k", "T", SONARR))

    def test_searching_again_uses_each_services_own_command(self):
        self.client.searchAgain(self.item)
        self.assertEqual(("post", "/api/v3/command", {"name": "SeriesSearch", "seriesId": 7}),
                         self.sent())

        movies = radarr()
        movies.searchAgain(model.Download("k", "T", RADARR, service_id=1, parent_id=9))
        self.assertEqual(("post", "/api/v3/command", {"name": "MoviesSearch", "movieIds": [9]}),
                         movies.http.requests[0])

    def test_nothing_to_search_for_is_refused_rather_than_guessed(self):
        with self.assertRaises(ServiceError):
            self.client.searchAgain(model.Download("k", "T", SONARR, service_id=42))


class AddNewTest(KodiTestCase):
    LOOKUP = [
        {"title": "Severance", "year": 2022, "tvdbId": 371980,
         "overview": "Work-life balance", "id": 0,
         "images": [{"coverType": "poster", "remoteUrl": "http://art/sev.jpg"}]},
        {"title": "Andor", "year": 2022, "tvdbId": 368159, "id": 7},
    ]

    def setUp(self):
        KodiTestCase.setUp(self)
        self.client = sonarr({"/api/v3/series/lookup": self.LOOKUP,
                              "/api/v3/qualityprofile": [{"id": 4, "name": "HD-1080p"},
                                                         {"id": 5, "name": "Ultra-HD"}],
                              "/api/v3/rootfolder": [{"id": 2, "path": "/media/media/tv"}],
                              "/api/v3/series": {"id": 99}})

    def test_a_lookup_reads_like_something_you_can_choose_from(self):
        found = self.client.lookup("severance")
        self.assertEqual("Severance (2022)", found[0].display)
        self.assertEqual(371980, found[0].ident)
        self.assertEqual("http://art/sev.jpg", found[0].poster)

    def test_things_already_in_the_library_say_so(self):
        """lookup only carries an id for what the service already has."""
        found = self.client.lookup("andor")
        self.assertFalse(found[0].added)
        self.assertTrue(found[1].added)

    def test_a_guid_can_be_looked_up_directly(self):
        """
        What makes adding from a Plex watchlist exact: the watchlist entry
        already carries the id, so nothing has to be matched on a title.
        """
        self.client.lookup("tvdb:371980")
        self.assertEqual("tvdb:371980", self.client.http.requests[0][2]["term"])

    def test_adding_a_series_asks_for_it_to_be_searched(self):
        candidate = self.client.lookup("severance")[0]
        self.client.add(candidate, 4, "/media/media/tv")

        method, path, body = self.client.http.requests[-1]
        self.assertEqual(("post", "/api/v3/series"), (method, path))
        self.assertEqual(371980, body["tvdbId"])
        self.assertEqual(4, body["qualityProfileId"])
        self.assertEqual("/media/media/tv", body["rootFolderPath"])
        self.assertTrue(body["monitored"])
        self.assertTrue(body["addOptions"]["searchForMissingEpisodes"])

    def test_adding_a_movie_speaks_radarr(self):
        movies = radarr({"/api/v3/movie/lookup": [{"title": "Sisu", "year": 2022, "tmdbId": 987}],
                         "/api/v3/movie": {"id": 5}})
        candidate = movies.lookup("sisu")[0]
        movies.add(candidate, 5, "/media/media/movies")

        method, path, body = movies.http.requests[-1]
        self.assertEqual(("post", "/api/v3/movie"), (method, path))
        self.assertEqual(987, body["tmdbId"])
        self.assertTrue(body["addOptions"]["searchForMovie"])
        self.assertNotIn("seasonFolder", body)

    def test_the_options_an_add_needs(self):
        self.assertEqual([(4, "HD-1080p"), (5, "Ultra-HD")], self.client.profiles())
        self.assertEqual([(2, "/media/media/tv")], self.client.rootFolders())


class ManagerRoutingTest(KodiTestCase):
    def test_a_row_knows_which_service_to_act_on(self):
        tv, films = sonarr(), radarr()
        mgr = DownloadsManager(config=_StubConfig([tv, films]))

        self.assertIs(tv, mgr.clientFor(model.Download("k", "T", SONARR)))
        self.assertIs(films, mgr.clientFor(model.Download("k", "T", RADARR)))
        self.assertIsNone(mgr.clientFor(model.Download("k", "T", "qbittorrent")))

    def test_only_the_arrs_can_be_added_to(self):
        mgr = DownloadsManager(config=_StubConfig([sonarr(), radarr(), qbittorrent()]))
        self.assertEqual({SONARR, RADARR}, set(mgr.services()))

    def test_a_removed_row_leaves_the_screen_at_once(self):
        """Waiting a poll for it to disappear reads as "the button did nothing"."""
        client = sonarr({"/api/v3/queue": fixture("sonarr_queue.json")})
        mgr = DownloadsManager(config=_StubConfig([client]))
        snapshot = mgr.refresh()
        gone = snapshot.items[0]

        after = mgr.forget(gone)

        self.assertNotIn(gone.key, [i.key for i in after.items])
        self.assertEqual(len(snapshot.items) - 1, len(after.items))


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


class PlexItemTest(KodiTestCase):
    """
    Sending something you are already looking at to the stack. This is the
    route that needs no keyboard, so what matters is that the id it sends is
    the exact one rather than a title to be guessed at.
    """

    class Guid(object):
        def __init__(self, ident):
            self.id = ident

    class Item(object):
        def __init__(self, type_, title, guids=()):
            self.TYPE = type_
            self.title = title
            self.guids = [PlexItemTest.Guid(g) for g in guids]

    def test_a_film_goes_to_radarr_by_its_tmdb_id(self):
        item = self.Item("movie", "Conan the Barbarian",
                         ["imdb://tt0082198", "tmdb://9387", "tvdb://1317"])
        self.assertEqual(RADARR, arr.flavourFor(item))
        self.assertEqual("tmdb:9387", arr.lookupTerm(item, RADARR))

    def test_a_show_goes_to_sonarr_by_its_tvdb_id(self):
        item = self.Item("show", "Andor", ["tmdb://83867", "tvdb://368159"])
        self.assertEqual(SONARR, arr.flavourFor(item))
        self.assertEqual("tvdb:368159", arr.lookupTerm(item, SONARR))

    def test_plex_own_guid_is_no_use_and_is_not_offered(self):
        """
        A watchlist row's guid is plex://movie/5d776832..., which means nothing
        to an *arr - the ids it needs are the Guid children alongside it.
        """
        item = self.Item("movie", "Conan the Barbarian", ["plex://movie/5d7768"])
        self.assertEqual("Conan the Barbarian", arr.lookupTerm(item, RADARR))

    def test_without_ids_it_falls_back_to_the_title(self):
        self.assertEqual("Sisu", arr.lookupTerm(self.Item("movie", "Sisu"), RADARR))


class ReleasePickingTest(KodiTestCase):
    """
    Taking over from the *arr and choosing the file yourself - the fix for a
    grab that keeps failing. A live Sonarr answers this with 79 releases for
    one season, so what matters is which one is put in front of you first.
    """

    RELEASES = [
        {"title": "Show.S01.720p.WEB", "guid": "g1", "indexerId": 3, "size": 2000000000,
         "seeders": 4, "indexer": "nzbgeek", "protocol": "usenet",
         "quality": {"quality": {"name": "WEBDL-720p"}}, "rejected": False},
        {"title": "Show.S01.2160p.REMUX", "guid": "g2", "indexerId": 3, "size": 60000000000,
         "seeders": 56, "indexer": "torrentleech", "protocol": "torrent",
         "quality": {"quality": {"name": "Bluray-2160p"}}, "rejected": False},
        {"title": "Show.S01.CAM", "guid": "g3", "indexerId": 4, "size": 700000000,
         "seeders": 300, "indexer": "somewhere", "protocol": "torrent",
         "quality": {"quality": {"name": "CAM"}}, "rejected": True,
         "rejections": ["Quality CAM is rejected by profile"]},
    ]

    def setUp(self):
        KodiTestCase.setUp(self)
        self.client = sonarr({"/api/v3/release": self.RELEASES})
        self.item = model.Download("k", "Show", SONARR, service_id=1, parent_id=7)

    def test_the_best_bet_is_offered_first(self):
        """Accepted before rejected, then by seeders - not the server's order."""
        found = self.client.releases(self.item)
        self.assertEqual(["Show.S01.2160p.REMUX", "Show.S01.720p.WEB", "Show.S01.CAM"],
                         [r.title for r in found])

    def test_a_release_says_what_it_is_worth(self):
        best = self.client.releases(self.item)[0]
        self.assertIn("Bluray-2160p", best.display)
        self.assertIn("56 seeders", best.display)
        self.assertIn("torrentleech", best.display)

    def test_a_rejected_release_says_so_and_why(self):
        """It is still offered - sometimes you want it anyway - but not quietly."""
        worst = self.client.releases(self.item)[-1]
        self.assertTrue(worst.rejected)
        self.assertIn("rejected", worst.display)
        self.assertIn("CAM is rejected", worst.display)

    def test_the_search_is_scoped_to_the_right_thing(self):
        self.client.releases(self.item, season=2)
        _method, path, params = self.client.http.requests[0]
        self.assertEqual("/api/v3/release", path)
        self.assertEqual(7, params["seriesId"])
        self.assertEqual(2, params["seasonNumber"])

    def test_grabbing_names_the_exact_release(self):
        release = self.client.releases(self.item)[0]
        self.client.grab(release)
        method, path, body = self.client.http.requests[-1]
        self.assertEqual(("post", "/api/v3/release"), (method, path))
        self.assertEqual({"guid": "g2", "indexerId": 3}, body)

    def test_something_with_no_guid_cannot_be_grabbed(self):
        with self.assertRaises(ServiceError):
            self.client.grab(model.Release("t", None, 1))


class TorrentControlTest(KodiTestCase):
    """qBittorrent 4.6 here; 5 renamed pause and resume, so both are handled."""

    def setUp(self):
        KodiTestCase.setUp(self)
        self.client = qbittorrent({"/api/v2/auth/login": "Ok."})
        self.item = model.Download("k", "T", QBITTORRENT, service_id="abc123")

    def paths(self):
        return [(m, p) for m, p, _ in self.client.http.requests if "torrents" in p]

    def test_pause_and_resume_address_the_torrent(self):
        self.client.pause(self.item)
        self.client.resume(self.item)
        self.assertEqual([("post", "/api/v2/torrents/pause"),
                          ("post", "/api/v2/torrents/resume")], self.paths())

    def test_removing_a_torrent_keeps_the_files(self):
        self.client.remove(self.item)
        data = [kw for m, p, kw in self.client.http.requests if p.endswith("delete")][0]
        self.assertEqual("false", data["deleteFiles"])

    def test_a_row_with_no_hash_is_refused(self):
        with self.assertRaises(ServiceError):
            self.client.pause(model.Download("k", "T", QBITTORRENT))

    def test_qbittorrent_5_naming_is_handled(self):
        class Renamed(FakeHttp):
            """A qBittorrent 5, which has stop/start and no pause/resume."""

            def request(self, path, method="get", **kwargs):
                if path.endswith("/pause"):
                    self.requests.append((method, path, {}))
                    raise ServiceError("HTTP 404", status=404)
                return FakeHttp.request(self, path, method, **kwargs)

        self.client.http = Renamed({"/api/v2/auth/login": "Ok."})
        self.client.pause(self.item)
        self.assertIn(("post", "/api/v2/torrents/stop"), self.paths())


class SearchAsYouTypeTest(KodiTestCase):
    """
    The autocomplete dialog's decisions, which are the parts that are not
    layout: when it asks, what it asks, and what it does with a stale answer.
    """

    def setUp(self):
        KodiTestCase.setUp(self)
        self.arrsearch = import_window_module("lib.windows.arrsearch")
        self.client = sonarr({"/api/v3/series/lookup": [
            {"title": "Severance", "year": 2022, "tvdbId": 371980},
            {"title": "Severance", "year": 2006, "tvdbId": 1, "id": 4},
        ]})
        self.dialog = self.arrsearch.ArrSearchDialog.__new__(self.arrsearch.ArrSearchDialog)
        self.dialog.services = {SONARR: self.client}
        self.dialog.candidates = []
        self.dialog.lastQuery = None
        self.dialog.searchUntil = 0
        self.dialog.searchThread = None
        self.drawn = []
        self.dialog.draw = lambda status: self.drawn.append(status)
        self.dialog.setProperty = lambda *a: None
        self.dialog.edit = type("E", (), {"getText": lambda _s: self.typed})()
        self.typed = ""

    def test_one_letter_is_not_worth_a_request(self):
        self.typed = "s"
        self.dialog._search()
        self.assertEqual([], self.client.http.requests)

    def test_a_real_query_asks_every_service(self):
        self.typed = "severance"
        self.dialog._search()
        self.assertEqual(1, len(self.client.http.requests))
        self.assertEqual("severance", self.client.http.requests[0][2]["term"])
        self.assertEqual(2, len(self.dialog.candidates))

    def test_typing_the_same_thing_again_asks_nothing(self):
        self.typed = "severance"
        self.dialog._search()
        self.dialog._search()
        self.assertEqual(1, len(self.client.http.requests))

    def test_an_answer_for_an_abandoned_query_is_dropped(self):
        """
        You keep typing while the service is thinking; what comes back is
        about what you used to be searching for, and putting it on screen
        would be worse than showing nothing.
        """
        typing = {"value": "severance"}
        self.dialog.edit = type("E", (), {"getText": lambda _s: typing["value"]})()

        original = self.client.lookup

        def lookupThenType(term):
            found = original(term)
            typing["value"] = "severance s01"   # the user carried on
            return found

        self.client.lookup = lookupThenType
        self.dialog._search()

        self.assertEqual([], self.dialog.candidates)
        self.assertEqual([], self.drawn)

    def test_a_service_that_fails_does_not_take_the_dialog_with_it(self):
        self.dialog.services = {SONARR: sonarr(raises=ServiceError("unreachable"))}
        self.typed = "severance"
        self.dialog._search()
        self.assertEqual([], self.dialog.candidates)
        self.assertTrue(self.drawn)
