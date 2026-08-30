# coding=utf-8
"""
SeekDialog progress bars.

updateProgress() runs on every tick of video playback, so an exception in it
takes out the seek OSD for the rest of the session. It is also the one part of
the dialog that is pure arithmetic - offsets in and control widths out - so it
is reachable without a Kodi window manager as long as the controls it writes to
are stood in for.
"""

from __future__ import absolute_import

from .base import KodiTestCase, import_window_module

seekdialog = import_window_module("lib.windows.seekdialog")

DURATION = 100000


class FakeControl(object):
    def __init__(self):
        self.position = (0, 0)
        self.width = 0

    def setPosition(self, x, y):
        self.position = (x, y)

    def getPosition(self):
        return self.position

    def setWidth(self, width):
        self.width = width

    def getWidth(self):
        return self.width


class FakePlayerObject(object):
    # seconds; SeekDialog.DPPlayerOffset scales it to milliseconds
    startOffset = 0

    def getBifUrl(self, offset):
        return "bif://{0}".format(offset)


class FakePlayer(object):
    def __init__(self):
        self.playerObject = FakePlayerObject()


class FakeHandler(object):
    def __init__(self):
        self.player = FakePlayer()


def make_dialog(offset=0, selected_offset=None, duration=DURATION):
    dialog = seekdialog.SeekDialog.__new__(seekdialog.SeekDialog)
    dialog.initialized = True
    dialog.handler = FakeHandler()
    dialog._duration = duration
    dialog.offset = offset
    dialog.selectedOffset = selected_offset
    dialog.baseOffset = 0
    dialog.isDirectPlay = True
    dialog.forceNextTimeAsChapter = None
    dialog.hasBif = False
    dialog.no_spoilers = ""
    dialog.no_time_no_osd_spoilers = False

    dialog.properties = {}
    dialog.setProperty = lambda key, value: dialog.properties.__setitem__(key, value)

    for name in ("selectionIndicator", "selectionBox", "selectionIndicatorImage",
                 "selectionIndicatorText", "seekbarControl", "positionControl",
                 "bifImageControl"):
        setattr(dialog, name, FakeControl())
    return dialog


class UpdateProgressTest(KodiTestCase):
    def test_the_bars_follow_the_offset(self):
        dialog = make_dialog(offset=DURATION // 4)
        dialog.updateProgress()

        expected = seekdialog.SeekDialog.SEEK_IMAGE_WIDTH // 4
        self.assertEqual(dialog.seekbarControl.getWidth(), expected)
        self.assertEqual(dialog.positionControl.getWidth(), expected)
        self.assertTrue(dialog.properties["time.selection"])

    def test_an_explicit_offset_wins_over_the_current_position(self):
        dialog = make_dialog(offset=0)
        dialog.updateProgress(offset=DURATION // 2)

        self.assertEqual(dialog.seekbarControl.getWidth(),
                         seekdialog.SeekDialog.SEEK_IMAGE_WIDTH // 2)

    def test_no_offset_yet_is_treated_as_the_start_of_the_file(self):
        """
        Regression: self.offset is None until the first tick lands, and
        updateProgress() used to divide by it and take the seek OSD out with a
        TypeError for the rest of playback. trueOffset() has always guarded the
        same attribute.
        """
        dialog = make_dialog(offset=None)
        dialog.updateProgress(offset=DURATION // 2)

        self.assertEqual(dialog.seekbarControl.getWidth(),
                         seekdialog.SeekDialog.SEEK_IMAGE_WIDTH // 2)

    def test_no_offset_yet_on_the_time_indicator_path(self):
        dialog = make_dialog(offset=None)
        dialog.updateProgress(offset=DURATION // 2, onlyTimeIndicator=True)

        self.assertTrue(dialog.properties["time.selection"])

    def test_nothing_is_drawn_before_the_dialog_is_initialised(self):
        dialog = make_dialog(offset=None)
        dialog.initialized = False
        dialog.updateProgress()

        self.assertEqual(dialog.seekbarControl.getWidth(), 0)
        self.assertEqual(dialog.properties, {})

    def test_true_offset_guards_the_same_attribute(self):
        dialog = make_dialog(offset=None)
        dialog.baseOffset = 1500
        dialog.handler.player.playerObject.startOffset = 2.5

        self.assertEqual(dialog.trueOffset(), 2500)
        dialog.isDirectPlay = False
        self.assertEqual(dialog.trueOffset(), 1500)
