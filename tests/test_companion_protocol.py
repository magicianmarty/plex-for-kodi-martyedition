# coding=utf-8
"""
lib/companion/protocol.py - the Companion wire format.

Nothing here touches Kodi or a socket. The point of keeping the format in a pure
module is that the parts a controller is fussy about can be asserted directly,
and those are mostly shape rather than content: a missing blank line after the
GDM headers, a timeline that names two types instead of three, or a commandID
the player invented rather than echoed all present as "the device does not
work", with nothing logged anywhere.
"""

from __future__ import absolute_import

from xml.etree import ElementTree

from lib.companion import protocol

from .base import KodiTestCase


class GDMResponseTest(KodiTestCase):
    def response(self, **kwargs):
        defaults = dict(name="Lounge", port=3005, product="PM4K",
                        version="1.14.1", resource_identifier="abc123")
        defaults.update(kwargs)
        return protocol.gdm_response(**defaults)

    def test_it_is_parseable_as_http_headers(self):
        body = self.response()
        status, rest = body.split("\r\n", 1)
        self.assertEqual("HTTP/1.0 200 OK", status)

        headers = {}
        for line in rest.split("\r\n"):
            if not line:
                break
            name, _, value = line.partition(": ")
            headers[name] = value

        self.assertEqual("plex/media-player", headers["Content-Type"])
        self.assertEqual("3005", headers["Port"])
        self.assertEqual("abc123", headers["Resource-Identifier"])
        self.assertEqual("Lounge", headers["Name"])
        self.assertEqual("stb", headers["Device-Class"])

    def test_it_ends_with_a_blank_line(self):
        """A reply without the terminator reads as truncated and is dropped."""
        self.assertTrue(self.response().endswith("\r\n\r\n"))

    def test_every_line_ends_crlf(self):
        body = self.response()
        self.assertNotIn("\n\n", body)
        for line in body.split("\r\n"):
            self.assertNotIn("\n", line)

    def test_it_advertises_only_what_is_implemented(self):
        """
        The capability list is a promise - the apps will call whatever is named
        here, so a capability with no endpoint behind it is a dead button.
        """
        headers = dict(
            line.split(": ", 1)
            for line in self.response().split("\r\n")
            if ": " in line
        )
        self.assertEqual(protocol.PROTOCOL_CAPABILITIES,
                         headers["Protocol-Capabilities"])
        self.assertNotIn("mirror", headers["Protocol-Capabilities"])


class ResourcesTest(KodiTestCase):
    def player(self, **kwargs):
        defaults = dict(machine_identifier="abc123", name="Lounge", product="PM4K",
                        version="1.14.1", platform="Linux", platform_version="6.1")
        defaults.update(kwargs)
        xml = protocol.resources_xml(**defaults)
        return ElementTree.fromstring(xml).find("Player")

    def test_it_identifies_the_player(self):
        player = self.player()
        self.assertEqual("abc123", player.get("machineIdentifier"))
        self.assertEqual("Lounge", player.get("title"))
        self.assertEqual("plex", player.get("protocol"))
        self.assertEqual(protocol.PROTOCOL_CAPABILITIES,
                         player.get("protocolCapabilities"))

    def test_a_name_with_markup_in_it_does_not_break_the_document(self):
        """Kodi's device name is free text and reaches here unfiltered."""
        player = self.player(name='Marty & "the" <Lounge>')
        self.assertEqual('Marty & "the" <Lounge>', player.get("title"))


class TimelineTest(KodiTestCase):
    def container(self, timelines, **kwargs):
        return ElementTree.fromstring(protocol.timeline_xml(timelines, **kwargs))

    def test_all_three_types_are_always_present(self):
        """
        Sending only the type that is playing leaves the apps on a spinner.
        """
        container = self.container({"video": {"state": "playing", "time": 10}})
        types = [t.get("type") for t in container.findall("Timeline")]
        self.assertEqual(["video", "music", "photo"], types)

    def test_untouched_types_are_stopped(self):
        container = self.container({"video": {"state": "playing", "time": 10}})
        music = container.findall("Timeline")[1]
        self.assertEqual("stopped", music.get("state"))

    def test_a_stopped_timeline_carries_nothing_else(self):
        """
        A ratingKey on a stopped timeline makes the apps offer to resume
        something that is not on screen.
        """
        container = self.container({"video": {"state": "stopped", "ratingKey": "42",
                                              "time": 900}})
        video = container.find("Timeline")
        self.assertEqual({"type", "state"}, set(video.keys()))

    def test_command_id_is_echoed(self):
        """The controller matches replies on its own number, not ours."""
        self.assertEqual("7", self.container({}, command_id=7).get("commandID"))

    def test_command_id_zero_is_still_sent(self):
        """Falsy, but a real value - dropping it strands the first request."""
        self.assertEqual("0", self.container({}, command_id=0).get("commandID"))

    def test_playing_timeline_carries_position_and_controls(self):
        container = self.container({
            "video": {
                "state": "playing", "time": 12345, "duration": 60000,
                "ratingKey": "42", "key": "/library/metadata/42",
                "controllable": "playPause,stop,seekTo",
            }
        })
        video = container.find("Timeline")
        self.assertEqual("12345", video.get("time"))
        self.assertEqual("60000", video.get("duration"))
        self.assertEqual("playPause,stop,seekTo", video.get("controllable"))

    def test_empty_attributes_are_dropped(self):
        """
        An attribute present but empty is not the same as absent - the apps read
        containerKey="" as a play queue that exists and then fail to fetch it.
        """
        container = self.container({
            "video": {"state": "playing", "time": 1, "containerKey": "", "guid": None}
        })
        video = container.find("Timeline")
        self.assertNotIn("containerKey", video.keys())
        self.assertNotIn("guid", video.keys())

    def test_location_defaults_to_navigation(self):
        self.assertEqual("navigation", self.container({}).get("location"))


class CommandResponseTest(KodiTestCase):
    def test_success(self):
        response = ElementTree.fromstring(protocol.command_response())
        self.assertEqual("200", response.get("code"))
        self.assertEqual("OK", response.get("status"))

    def test_failure_carries_the_code(self):
        response = ElementTree.fromstring(protocol.command_response(404, "Not Found"))
        self.assertEqual("404", response.get("code"))
