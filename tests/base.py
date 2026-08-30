# coding=utf-8
"""Shared base class and helpers for the PM4K suite."""

from __future__ import absolute_import

import copy
import importlib
import os
import shutil
import tempfile
import unittest

import xbmc
import xbmcplugin
from kodienv import ENV

from . import FIXTURES_ROOT, REPO_ROOT

TEMPLATE_DIR = os.path.join(REPO_ROOT, "resources", "skins", "Main", "1080i", "templates")
MEDIA_DIR = os.path.join(REPO_ROOT, "resources", "skins", "Main", "media")
LANGUAGE_DIR = os.path.join(REPO_ROOT, "resources", "language")


def fixture(*parts):
    """Read a file from tests/fixtures/ as text."""
    with open(os.path.join(FIXTURES_ROOT, *parts), "r", encoding="utf-8") as fp:
        return fp.read()


def ensure_plex_interface():
    """
    Install PM4K's real plexnet interface.

    plexnet reaches back into the host app through util.INTERFACE for
    preferences, globals and logging. Importing plexapp installs a
    DumbInterface placeholder, so "already set" is not the same as "set to
    PM4K's" - always import lib.plex, which is what registers the real one.
    Using it rather than a fake means the plexnet tests exercise the same
    preference plumbing the addon uses.
    """
    import lib.plex  # noqa: F401
    from plexnet import util as pnUtil
    return pnUtil.INTERFACE


def import_window_module(name):
    """
    Import a module under `lib.windows.` and hand it back.

    Anything in lib/windows/ pulls in lib.player, which builds PLAYER at import
    time and starts a non-daemon PLAYER:MONITOR thread. The stub's
    waitForAbort() does not block, so that thread would spin against ENV for the
    rest of the run and then keep the interpreter alive at exit. Set the abort
    flag first so it stops on its first pass, and join it before restoring.
    """
    previous = ENV.abort_requested
    ENV.abort_requested = True
    try:
        module = importlib.import_module(name)
        from lib import player
        thread = getattr(player.PLAYER, "thread", None)
        if thread is not None:
            thread.join(timeout=30)
            assert not thread.is_alive(), "PLAYER:MONITOR did not stop"
    finally:
        ENV.abort_requested = previous
    return module


class KodiTestCase(unittest.TestCase):
    """
    Resets every piece of stub state between tests.

    Caveat worth remembering: PM4K snapshots a lot of Kodi state into module
    level constants at import time (util.timeFormat, util.DISPLAY_RESOLUTION,
    cache.CACHE_SIZE, ...). Those are *not* rolled back by resetting ENV, so
    prefer calling the function under test over asserting on a constant.
    """

    def setUp(self):
        ENV.reset()
        xbmc.Player.playing = False
        xbmc.Player.playing_video = False
        xbmc.Player.playing_audio = False
        xbmc.Player.playing_file = ""
        xbmc.Player.time = 0.0
        xbmc.Player.total_time = 0.0
        xbmc.Player.calls = []
        xbmc.PlayList.lists = {}
        del xbmcplugin.DIRECTORY_ITEMS[:]
        self._tempdirs = []

    def tearDown(self):
        for path in getattr(self, "_tempdirs", []):
            shutil.rmtree(path, ignore_errors=True)

    def mktemp(self, *parts):
        """A temp directory removed again in tearDown."""
        path = tempfile.mkdtemp(prefix="pm4k-case-")
        self._tempdirs.append(path)
        if parts:
            path = os.path.join(path, *parts)
            os.makedirs(path)
        return path


def make_engine(target_dir, template_dir=TEMPLATE_DIR, custom_template_dir=None, context=None):
    """
    A TemplateEngine writing into `target_dir` instead of into the repo.

    The addon's own render_templates() targets the installed addon directory,
    which for a test checkout is the working tree - rendering through it would
    litter resources/skins/Main/1080i with generated XML. Drive the engine
    directly instead.
    """
    from lib.templating.context import TEMPLATE_CONTEXTS
    from lib.templating.core import TemplateEngine

    engine = TemplateEngine()
    engine.init(target_dir, template_dir, custom_template_dir or os.path.join(target_dir, "custom"))
    engine.context = copy.deepcopy(TEMPLATE_CONTEXTS if context is None else context)
    engine.debug_log = lambda *args, **kwargs: None
    return engine
