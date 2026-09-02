# coding=utf-8
"""
lib/companion/commands.py - what a Companion request actually does.

The split these test is the important one. Navigation and transport run on the
HTTP thread because Kodi marshals executebuiltin and JSON-RPC itself; anything
that opens a window is queued for the Cron thread instead, because driving the
window stack from an arbitrary thread is how add-ons deadlock Kodi. Getting a
command on the wrong side of that line does not fail visibly - it works until
the box is busy - so the routing is asserted rather than assumed.
"""

from __future__ import absolute_import

from kodienv import ENV

from lib.companion import commands

from .base import KodiTestCase, import_player


class NavigationTest(KodiTestCase):
    def test_the_arrows_become_kodi_actions(self):
        for command, action in (("moveUp", "Up"), ("moveDown", "Down"),
                                ("moveLeft", "Left"), ("moveRight", "Right")):
            with self.subTest(command=command):
                ENV.builtins[:] = []
                self.assertTrue(commands.execute("navigation", command, {}))
                self.assertEqual(["Action({0})".format(action)], ENV.builtins)

    def test_select_and_back(self):
        commands.execute("navigation", "select", {})
        commands.execute("navigation", "back", {})
        self.assertEqual(["Action(Select)", "Action(Back)"], ENV.builtins)

    def test_context_menu(self):
        self.assertTrue(commands.execute("navigation", "contextMenu", {}))
        self.assertEqual(["Action(ContextMenu)"], ENV.builtins)

    def test_an_unknown_navigation_command_is_refused(self):
        self.assertFalse(commands.execute("navigation", "moonwalk", {}))
        self.assertEqual([], ENV.builtins)

    def test_home_is_deferred_rather_than_run_inline(self):
        """
        actionHome() rebuilds the hub screen, so it must not run on an HTTP
        worker.
        """
        self.assertTrue(commands.execute("navigation", "home", {}))
        self.assertEqual([], ENV.builtins)
        self.assertEqual(1, commands.DEFERRED.queue.qsize())
        commands.DEFERRED.drain()


class PlaybackTest(KodiTestCase):
    def setUp(self):
        KodiTestCase.setUp(self)
        ENV.jsonrpc_responses["Player.GetActivePlayers"] = [
            {"playerid": 1, "type": "video"}]
        ENV.jsonrpc_responses["Player.PlayPause"] = {"speed": 1}
        ENV.jsonrpc_responses["Player.Seek"] = {}

    def jsonrpc(self, method):
        return [params for name, params in ENV.jsonrpc_calls if name == method]

    def test_play_and_pause_are_explicit_not_a_toggle(self):
        """
        Companion sends play and pause separately. Mapping both onto a toggle
        makes the phone's button disagree with the screen the moment one is
        missed.
        """
        commands.execute("playback", "play", {})
        commands.execute("playback", "pause", {})
        calls = self.jsonrpc("Player.PlayPause")
        self.assertEqual([True, False], [call["play"] for call in calls])

    def test_play_pause_is_a_toggle(self):
        commands.execute("playback", "playPause", {})
        self.assertNotIn("play", self.jsonrpc("Player.PlayPause")[0])

    def test_transport_with_nothing_playing_is_refused(self):
        ENV.jsonrpc_responses["Player.GetActivePlayers"] = []
        self.assertFalse(commands.execute("playback", "pause", {}))

    def test_stop(self):
        import xbmc
        xbmc.Player.calls = []
        self.assertTrue(commands.execute("playback", "stop", {}))
        self.assertIn("stop", [call for call, _ in xbmc.Player.calls])

    def test_skip(self):
        commands.execute("playback", "skipNext", {})
        commands.execute("playback", "skipPrevious", {})
        self.assertEqual(["Action(SkipNext)", "Action(SkipPrevious)"], ENV.builtins)

    def test_volume(self):
        self.assertTrue(commands.execute("playback", "setParameters", {"volume": "40"}))
        self.assertEqual(["SetVolume(40)"], ENV.builtins)

    def test_a_non_numeric_volume_is_refused_rather_than_crashing(self):
        self.assertFalse(commands.execute("playback", "setParameters", {"volume": "loud"}))

    def test_setparameters_without_a_volume_is_still_acknowledged(self):
        """The apps send it for things this player does not implement."""
        self.assertTrue(commands.execute("playback", "setParameters", {}))
        self.assertEqual([], ENV.builtins)

    def test_a_non_numeric_offset_is_refused(self):
        self.assertFalse(commands.execute("playback", "seekTo", {"offset": "soon"}))

    def test_play_media_is_deferred(self):
        """Fetches a play queue and opens a window; neither belongs on HTTP."""
        self.assertTrue(commands.execute("playback", "playMedia", {"key": "/library/metadata/1"}))
        self.assertEqual(1, commands.DEFERRED.queue.qsize())
        commands.DEFERRED.drain()

    def test_an_unknown_playback_command_is_refused(self):
        self.assertFalse(commands.execute("playback", "hyperspeed", {}))


class SeekTest(KodiTestCase):
    """
    Seeks go through the add-on's own handler, not Kodi's.

    That handler is where this fork's playback policy lives, so a seek from a
    phone has to take the same route as one from the on-screen scrub bar - if it
    does not, phone-driven seeking quietly behaves differently from every other
    seek in the add-on.
    """

    def setUp(self):
        KodiTestCase.setUp(self)
        player = import_player()
        self.player = player
        self.original = getattr(player.PLAYER, "handler", None)
        self.seeks = []

        class Handler(object):
            trueTime = 100.0

            def seek(_self, offset, **kwargs):
                self.seeks.append(offset)

        player.PLAYER.handler = Handler()

    def tearDown(self):
        self.player.PLAYER.handler = self.original
        KodiTestCase.tearDown(self)

    def test_seek_to_uses_the_addon_handler(self):
        self.assertTrue(commands.execute("playback", "seekTo", {"offset": "90000"}))
        self.assertEqual([90000], self.seeks)
        self.assertEqual([], [c for c, _ in ENV.jsonrpc_calls if c == "Player.Seek"])

    def test_step_forward_seeks_relative_to_the_current_position(self):
        commands.execute("playback", "stepForward", {})
        self.assertEqual([100000 + commands.STEP_MS], self.seeks)

    def test_step_back_seeks_backwards(self):
        commands.execute("playback", "stepBack", {})
        self.assertEqual([100000 - commands.STEP_MS], self.seeks)

    def test_stepping_back_past_the_start_clamps_to_zero(self):
        self.player.PLAYER.handler.trueTime = 5.0
        commands.execute("playback", "stepBack", {})
        self.assertEqual([0], self.seeks)


class DeferredCommandsTest(KodiTestCase):
    def setUp(self):
        KodiTestCase.setUp(self)
        self.deferred = commands.DeferredCommands()

    def test_tick_runs_everything_queued_in_order(self):
        ran = []
        for n in range(3):
            self.deferred.put(lambda n=n: ran.append(n))
        self.deferred.tick()
        self.assertEqual([0, 1, 2], ran)

    def test_tick_on_an_empty_queue_is_harmless(self):
        self.deferred.tick()

    def test_one_failing_command_does_not_stop_the_rest(self):
        """
        This drains inside Cron's receiver loop, which HomeWindow also uses. An
        exception escaping here would stop the hub screen refreshing.
        """
        ran = []

        def explode():
            raise RuntimeError("boom")

        self.deferred.put(explode)
        self.deferred.put(lambda: ran.append("after"))
        self.deferred.tick()
        self.assertEqual(["after"], ran)

    def test_drain_discards_without_running(self):
        ran = []
        self.deferred.put(lambda: ran.append("nope"))
        self.deferred.drain()
        self.deferred.tick()
        self.assertEqual([], ran)


class UnknownSectionTest(KodiTestCase):
    def test_an_unknown_section_is_refused(self):
        self.assertFalse(commands.execute("mirror", "details", {}))

    def test_an_exception_is_contained(self):
        self.assertFalse(commands.execute("playback", "seekTo", {"offset": object()}))
