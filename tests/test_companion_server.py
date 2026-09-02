# coding=utf-8
"""
lib/companion/server.py - the control server, exercised over a real socket.

These start the actual ControlServer on an ephemeral port and talk to it with
requests, rather than calling the handler directly. That is deliberate: most of
what can go wrong with this server is in the HTTP layer rather than the routing
- a missing Content-Length that makes a keep-alive connection hang, an OPTIONS
preflight that comes back without the CORS headers Plex Web needs, a reply
without the client identifier - and none of that is visible if the handler is
poked in isolation.
"""

from __future__ import absolute_import

import socket
import threading

import requests

from xml.etree import ElementTree

from lib.companion import commands, protocol, server, subscribers

from .base import KodiTestCase


IDENTITY = {
    "machine_identifier": "test-machine-id",
    "name": "Test Lounge",
    "product": "PM4K",
    "version": "1.14.1",
    "platform": "Linux",
    "platform_version": "6.1",
}


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class ServerTestCase(KodiTestCase):
    """Runs a real ControlServer for the duration of each test."""

    def setUp(self):
        KodiTestCase.setUp(self)
        self.executed = []

        # The command layer reaches into Kodi and the player; what matters here
        # is that the server routes to it and reports the outcome faithfully.
        self._real_execute = commands.execute

        def record(section, command, params):
            self.executed.append((section, command, params))
            return command != "notARealCommand"

        commands.execute = record

        # Timelines are covered by their own tests and need a live plexnet;
        # here they only have to produce a document the server can send.
        self._real_document = subscribers.timeline_document
        subscribers.timeline_document = lambda command_id=0, machine_identifier=None: (
            protocol.timeline_xml({"video": {"state": "playing", "time": 42}},
                                  command_id=command_id,
                                  machine_identifier=machine_identifier))

        self.port = free_port()
        self.server = server.ControlServer(self.port, IDENTITY)
        self.server.start()
        self.server.started.wait(5)
        self.assertTrue(self.server.bound, "control server did not bind")

    def tearDown(self):
        self.server.stop()
        commands.execute = self._real_execute
        subscribers.timeline_document = self._real_document
        subscribers.REGISTRY.clear()
        KodiTestCase.tearDown(self)

    def url(self, path):
        return "http://127.0.0.1:{0}{1}".format(self.port, path)

    def get(self, path, **kwargs):
        return requests.get(self.url(path), timeout=5, **kwargs)


class ResourcesTest(ServerTestCase):
    def test_it_identifies_itself(self):
        response = self.get("/resources")
        self.assertEqual(200, response.status_code)
        player = ElementTree.fromstring(response.text).find("Player")
        self.assertEqual("test-machine-id", player.get("machineIdentifier"))
        self.assertEqual("Test Lounge", player.get("title"))

    def test_every_reply_carries_the_client_identifier(self):
        response = self.get("/resources")
        self.assertEqual("test-machine-id",
                         response.headers.get("X-Plex-Client-Identifier"))

    def test_content_length_is_set(self):
        """
        Without it a keep-alive client waits for a body that never ends, which
        looks exactly like the player having hung.
        """
        response = self.get("/resources")
        self.assertEqual(str(len(response.content)),
                         response.headers.get("Content-Length"))

    def test_a_trailing_slash_is_the_same_resource(self):
        self.assertEqual(200, self.get("/resources/").status_code)


class CORSTest(ServerTestCase):
    def test_preflight_is_answered(self):
        response = requests.options(self.url("/player/playback/pause"), timeout=5)
        self.assertEqual(200, response.status_code)
        self.assertEqual("*", response.headers.get("Access-Control-Allow-Origin"))

    def test_preflight_allows_the_headers_plex_web_sends(self):
        response = requests.options(self.url("/resources"), timeout=5)
        allowed = response.headers.get("Access-Control-Allow-Headers", "").lower()
        for header in ("x-plex-client-identifier", "x-plex-target-client-identifier",
                       "x-plex-token", "x-plex-device-name"):
            self.assertIn(header, allowed)


class RoutingTest(ServerTestCase):
    def test_navigation_reaches_the_command_layer(self):
        response = self.get("/player/navigation/moveUp")
        self.assertEqual(200, response.status_code)
        self.assertEqual(("navigation", "moveUp"), self.executed[0][:2])

    def test_query_parameters_are_passed_through(self):
        self.get("/player/playback/seekTo?offset=90000&type=video")
        _, _, params = self.executed[0]
        self.assertEqual("90000", params["offset"])
        self.assertEqual("video", params["type"])

    def test_an_unknown_command_is_not_reported_as_success(self):
        """
        A controller told a command worked will not retry it; the user just sees
        a button that does nothing.
        """
        response = self.get("/player/playback/notARealCommand")
        self.assertEqual(404, response.status_code)
        body = ElementTree.fromstring(response.text)
        self.assertEqual("404", body.get("code"))

    def test_an_unknown_path_is_a_404(self):
        self.assertEqual(404, self.get("/nope").status_code)

    def test_post_is_accepted_as_well_as_get(self):
        response = requests.post(self.url("/player/navigation/select"), timeout=5)
        self.assertEqual(200, response.status_code)
        self.assertEqual(("navigation", "select"), self.executed[0][:2])


class TargetingTest(ServerTestCase):
    def test_a_command_aimed_at_another_player_is_ignored(self):
        """
        With several players on one subnet, acting on someone else's command
        makes two boxes respond to one keypress.
        """
        response = self.get(
            "/player/navigation/moveUp",
            headers={"X-Plex-Target-Client-Identifier": "some-other-device"})
        self.assertEqual(404, response.status_code)
        self.assertEqual([], self.executed)

    def test_a_command_aimed_at_us_is_obeyed(self):
        response = self.get(
            "/player/navigation/moveUp",
            headers={"X-Plex-Target-Client-Identifier": "test-machine-id"})
        self.assertEqual(200, response.status_code)
        self.assertEqual(1, len(self.executed))

    def test_an_untargeted_command_is_obeyed(self):
        self.assertEqual(200, self.get("/player/navigation/moveUp").status_code)


class TimelineEndpointTest(ServerTestCase):
    def test_poll_returns_a_timeline(self):
        response = self.get("/player/timeline/poll?commandID=4")
        self.assertEqual(200, response.status_code)
        container = ElementTree.fromstring(response.text)
        self.assertEqual("4", container.get("commandID"))
        self.assertEqual(3, len(container.findall("Timeline")))

    def test_subscribe_registers_the_controller(self):
        self.get("/player/timeline/subscribe"
                 "?protocol=http&port=32500&commandID=1"
                 "&X-Plex-Client-Identifier=phone-1")
        registered = subscribers.REGISTRY.all()
        self.assertEqual(1, len(registered))
        self.assertEqual("phone-1", registered[0].uuid)
        self.assertEqual(32500, registered[0].port)

    def test_the_subscriber_is_reached_at_its_own_address(self):
        """
        The port comes from the request but the host must come from the socket:
        a controller behind NAT reports an address that is not routable here.
        """
        self.get("/player/timeline/subscribe"
                 "?port=32500&X-Plex-Client-Identifier=phone-1")
        self.assertEqual("http://127.0.0.1:32500/:/timeline",
                         subscribers.REGISTRY.all()[0].url)

    def test_subscribing_twice_does_not_duplicate(self):
        for command_id in (1, 2):
            self.get("/player/timeline/subscribe"
                     "?port=32500&commandID={0}"
                     "&X-Plex-Client-Identifier=phone-1".format(command_id))
        self.assertEqual(1, len(subscribers.REGISTRY.all()))
        self.assertEqual(2, subscribers.REGISTRY.all()[0].command_id)

    def test_unsubscribe_removes_it(self):
        self.get("/player/timeline/subscribe"
                 "?port=32500&X-Plex-Client-Identifier=phone-1")
        self.get("/player/timeline/unsubscribe"
                 "?X-Plex-Client-Identifier=phone-1")
        self.assertEqual([], subscribers.REGISTRY.all())

    def test_the_identifier_may_arrive_as_a_header(self):
        self.get("/player/timeline/subscribe?port=32500",
                 headers={"X-Plex-Client-Identifier": "phone-header"})
        self.assertEqual("phone-header", subscribers.REGISTRY.all()[0].uuid)

    def test_polling_keeps_a_subscription_alive(self):
        """
        A controller that only ever polls would otherwise be pruned out from
        under itself while it is plainly still there.
        """
        self.get("/player/timeline/subscribe"
                 "?port=32500&X-Plex-Client-Identifier=phone-1")
        subscriber = subscribers.REGISTRY.all()[0]
        subscriber.last_seen = 0

        self.get("/player/timeline/poll?commandID=9"
                 "&X-Plex-Client-Identifier=phone-1")
        self.assertFalse(subscriber.expired)
        self.assertEqual(9, subscriber.command_id)


class ResilienceTest(ServerTestCase):
    def test_a_failing_command_does_not_take_the_server_down(self):
        def explode(section, command, params):
            raise RuntimeError("boom")

        commands.execute = explode
        response = self.get("/player/navigation/moveUp")
        self.assertEqual(500, response.status_code)

        commands.execute = self._real_execute
        self.assertEqual(200, self.get("/resources").status_code)

    def test_concurrent_requests_are_served(self):
        """Threaded, because a subscribed phone polls while PMS also asks."""
        results = []

        def hit():
            try:
                results.append(self.get("/resources").status_code)
            except Exception:
                results.append(None)

        threads = [threading.Thread(target=hit) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)

        self.assertEqual([200] * 8, results)
