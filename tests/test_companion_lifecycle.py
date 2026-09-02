# coding=utf-8
"""
lib/companion/__init__.py - starting and stopping the three threads.

The behaviour worth pinning down is what happens when things are not ideal,
because all of it is on the path the add-on takes every time it starts:

  * off unless asked for, since the protocol has no authentication at all
  * no half-started state - advertising a player whose control server did not
    bind puts a dead device in everyone's cast picker
  * nothing here may raise, because this runs inside main()'s startup and an
    exception would cost the user the whole add-on for a feature they may not
    even use
"""

from __future__ import absolute_import

import socket

from kodienv import ENV

from lib import companion
from lib.companion import protocol, subscribers

from .base import KodiTestCase, ensure_plex_interface


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class LifecycleTest(KodiTestCase):
    def setUp(self):
        KodiTestCase.setUp(self)
        ensure_plex_interface()
        self.companion = companion.Companion()
        ENV.settings["companion_port"] = str(free_port())

    def tearDown(self):
        self.companion.stop()
        subscribers.REGISTRY.clear()
        KodiTestCase.tearDown(self)

    def enable(self):
        ENV.settings["companion"] = "true"

    def test_it_is_off_unless_the_setting_is_on(self):
        self.assertFalse(self.companion.start())
        self.assertFalse(self.companion.running)

    def test_it_starts_when_enabled(self):
        self.enable()
        self.assertTrue(self.companion.start())
        self.assertTrue(self.companion.running)

    def test_starting_twice_is_a_no_op(self):
        self.enable()
        self.companion.start()
        server = self.companion.server
        self.assertTrue(self.companion.start())
        self.assertIs(server, self.companion.server)

    def test_stop_releases_everything(self):
        self.enable()
        self.companion.start()
        self.companion.stop()
        self.assertFalse(self.companion.running)
        self.assertIsNone(self.companion.advertiser)
        self.assertIsNone(self.companion.pusher)

    def test_stop_before_start_is_harmless(self):
        self.companion.stop()

    def test_stop_clears_subscribers(self):
        """Otherwise a restart posts to phones that subscribed to the old run."""
        self.enable()
        self.companion.start()
        subscribers.REGISTRY.add("phone", "10.0.0.5", 32500)
        self.companion.stop()
        self.assertEqual([], subscribers.REGISTRY.all())

    def test_the_port_setting_is_honoured(self):
        self.enable()
        port = free_port()
        ENV.settings["companion_port"] = str(port)
        self.companion.start()
        self.assertEqual(port, self.companion.port)

    def test_it_defaults_to_the_plex_port(self):
        self.assertEqual(3005, protocol.DEFAULT_HTTP_PORT)
        self.assertEqual(protocol.DEFAULT_HTTP_PORT, companion.Companion().port)

    def test_it_does_not_advertise_if_the_control_port_is_taken(self):
        """
        Advertising a player with no control server behind it puts a device in
        the cast picker that cannot be cast to.
        """
        holder = socket.socket()
        holder.bind(("0.0.0.0", 0))
        holder.listen(1)
        try:
            self.enable()
            ENV.settings["companion_port"] = str(holder.getsockname()[1])
            self.assertFalse(self.companion.start())
            self.assertIsNone(self.companion.advertiser)
            self.assertFalse(self.companion.running)
        finally:
            holder.close()

    def test_the_gdm_reply_describes_this_player(self):
        self.enable()
        self.companion.start()
        reply = self.companion._describe()
        self.assertIn("Port: {0}".format(self.companion.port), reply)
        self.assertIn("plex/media-player", reply)

    def test_the_gdm_reply_is_rebuilt_each_time(self):
        """So a device rename reaches the cast picker without a restart."""
        self.enable()
        self.companion.start()
        self.companion.identity["name"] = "Renamed"
        self.assertIn("Name: Renamed", self.companion._describe())


class ModuleEntryPointTest(KodiTestCase):
    """
    main() calls these directly, so neither may ever raise.
    """

    def tearDown(self):
        companion.stop()
        KodiTestCase.tearDown(self)

    def test_start_reports_false_rather_than_raising(self):
        self.assertFalse(companion.start())

    def test_start_survives_a_broken_identity(self):
        original = companion.COMPANION._build_identity

        def explode():
            raise RuntimeError("boom")

        companion.COMPANION._build_identity = explode
        try:
            ENV.settings["companion"] = "true"
            self.assertFalse(companion.start())
        finally:
            companion.COMPANION._build_identity = original

    def test_stop_survives_being_called_cold(self):
        companion.stop()
