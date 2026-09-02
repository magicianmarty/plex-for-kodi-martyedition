# coding=utf-8
"""
lib/companion/gdm.py - answering discovery, over a real UDP socket.

This is the half of Companion with no fallback. A player that does not answer
M-SEARCH is not in the cast picker, and nothing anywhere reports why: there is no
error, no log line on the phone, and the control server can be running perfectly.
So these tests send genuine datagrams rather than calling the parser, and check
the two things that have actually gone wrong historically - the verb match being
too strict, and the socket dying on the first bit of junk that arrives.
"""

from __future__ import absolute_import

import socket

from lib.companion import protocol
from lib.companion.gdm import GDMAdvertiser

from .base import KodiTestCase


def free_udp_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class GDMAdvertiserTest(KodiTestCase):
    def setUp(self):
        KodiTestCase.setUp(self)
        self.port = free_udp_port()
        self.advertiser = GDMAdvertiser(self.describe, port=self.port)
        self.advertiser.start()
        self.assertTrue(self.advertiser.bound.wait(5), "advertiser never bound")

    def tearDown(self):
        self.advertiser.stop()
        self.advertiser.join(5)
        KodiTestCase.tearDown(self)

    def describe(self):
        return protocol.gdm_response(
            name="Test Lounge", port=3005, product="PM4K",
            version="1.14.1", resource_identifier="test-machine-id")

    def search(self, payload, timeout=3):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.sendto(payload, ("127.0.0.1", self.port))
            data, _ = sock.recvfrom(4096)
            return data.decode("utf-8")
        finally:
            sock.close()

    def test_it_answers_a_search(self):
        reply = self.search(b"M-SEARCH * HTTP/1.0\r\n\r\n")
        self.assertIn("Content-Type: plex/media-player", reply)
        self.assertIn("Resource-Identifier: test-machine-id", reply)

    def test_it_answers_http_1_1_as_well(self):
        """
        Plex sends 1.1; the Roku code this is ported from only accepted 1.0, so
        matching on the version would have answered nobody.
        """
        reply = self.search(b"M-SEARCH * HTTP/1.1\r\n\r\n")
        self.assertIn("plex/media-player", reply)

    def test_the_advertised_port_is_the_control_port(self):
        """The only way a controller learns where to send commands."""
        self.assertIn("Port: 3005", self.search(b"M-SEARCH * HTTP/1.1\r\n\r\n"))

    def test_junk_does_not_get_a_reply(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)
        try:
            sock.sendto(b"hello?\r\n\r\n", ("127.0.0.1", self.port))
            self.assertRaises(socket.timeout, sock.recvfrom, 4096)
        finally:
            sock.close()

    def test_junk_does_not_kill_the_listener(self):
        """
        This socket sees whatever else is broadcasting on the subnet, so one
        unparseable packet must not end discovery for the session.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            for payload in (b"", b"\x00\x01\x02", b"NOTIFY * HTTP/1.1\r\n\r\n"):
                sock.sendto(payload, ("127.0.0.1", self.port))
        finally:
            sock.close()

        self.assertIn("plex/media-player",
                      self.search(b"M-SEARCH * HTTP/1.1\r\n\r\n"))

    def test_it_answers_repeatedly(self):
        """PMS searches every few seconds for as long as it is up."""
        for _ in range(3):
            self.assertIn("plex/media-player",
                          self.search(b"M-SEARCH * HTTP/1.1\r\n\r\n"))

    def test_stop_ends_the_thread(self):
        self.advertiser.stop()
        self.advertiser.join(5)
        self.assertFalse(self.advertiser.is_alive())


class GDMBindFailureTest(KodiTestCase):
    def test_a_taken_port_is_survivable(self):
        """
        Another Plex player on the box already holds 32412. Discovery is lost,
        but the add-on must not be.
        """
        holder = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        holder.bind(("0.0.0.0", 0))
        port = holder.getsockname()[1]
        try:
            advertiser = GDMAdvertiser(lambda: "", port=port)
            advertiser.start()
            self.assertTrue(advertiser.bound.wait(5))
            advertiser.join(5)
            self.assertFalse(advertiser.is_alive())
        finally:
            holder.close()
