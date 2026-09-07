# coding=utf-8
"""
In-player subtitle size.

subtitles.fontsize styles text through libass. Bitmap subtitles - PGS on any
Blu-ray rip, VOBSUB on a DVD one - are overlay images with no font, so the
setting reaches them not at all. Writing it anyway is what made the control
look broken: it accepted the choice, saved it, and nothing on screen moved.
"""

from __future__ import absolute_import

from unittest import mock

from .base import KodiTestCase, import_window_module

seekdialog = import_window_module("lib.windows.seekdialog")


class FakeStream(object):
    def __init__(self, codec, title=""):
        self.codec = codec
        self.title = title or codec

    def __str__(self):
        return self.title


class FakeVideo(object):
    def __init__(self, streams=None, selected=None):
        self.subtitleStreams = streams or []
        self._selected = selected
        self.selected = []

    def selectedSubtitleStream(self):
        return self._selected

    def selectStream(self, stream, **kwargs):
        self.selected.append(stream)


class FakePlayer(object):
    def __init__(self, video):
        self.video = video


class FakeHandler(object):
    """SeekDialog.player is a read-only property reading through the handler."""

    def __init__(self, video):
        self.player = FakePlayer(video)


def make_dialog(streams=None, selected=None):
    dialog = seekdialog.SeekDialog.__new__(seekdialog.SeekDialog)
    dialog.handler = FakeHandler(FakeVideo(streams, selected))
    dialog.subtitleButtonLeft = 0
    dialog.isTranscoded = False
    dialog.messages = []
    dialog.subtitlesApplied = 0
    dialog.setSubtitles = lambda **kwargs: setattr(
        dialog, "subtitlesApplied", dialog.subtitlesApplied + 1)
    return dialog


class Recorder(object):
    """Stands in for the module globals subtitleSizeClicked reaches through."""

    def __init__(self, choice=None):
        self.choice = choice
        self.written = []
        self.messages = []
        self.dropdowns = []

    def showDropdown(self, options, *args, **kwargs):
        self.dropdowns.append((options, kwargs))
        return self.choice

    def SetSettingValue(self, setting=None, value=None):
        self.written.append((setting, value))

    def GetSettingValue(self, setting=None):
        return {"value": 42}

    def messageDialog(self, heading="", msg=""):
        self.messages.append(msg)


class SubtitleSizeTest(KodiTestCase):
    def setUp(self):
        super(SubtitleSizeTest, self).setUp()
        self.recorder = Recorder()
        self._patch()

    def _patch(self, choice=None):
        """
        util and rpc are shared modules. Assigning onto them directly leaks
        into every later test in the run - it took out 14 of them once - so
        each stub is installed through mock and torn down again.
        """
        self.recorder.choice = choice
        for target, attr, replacement in (
            (seekdialog.dropdown, "showDropdown", self.recorder.showDropdown),
            (seekdialog.rpc.Settings, "SetSettingValue", self.recorder.SetSettingValue),
            (seekdialog.rpc.Settings, "GetSettingValue", self.recorder.GetSettingValue),
            (seekdialog.util, "messageDialog", self.recorder.messageDialog),
            (seekdialog.util, "showNotification", lambda *a, **k: None),
        ):
            patcher = mock.patch.object(target, attr, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_codec_comes_from_the_selected_plex_stream(self):
        dialog = make_dialog(selected=FakeStream("PGS"))
        self.assertEqual(dialog.currentSubtitleCodec(), "pgs")

    def test_the_codec_falls_back_to_kodi_when_plex_does_not_name_one(self):
        """
        Plex does not always populate codec on the stream - an externally
        loaded subtitle has none - so the player is asked directly. rpc.Player
        and rpc.Settings are the same shared handler object, hence patching
        either reaches both.
        """
        patcher = mock.patch.object(
            seekdialog.rpc.Settings, "GetActivePlayers",
            lambda **kw: [{"playerid": 1}])
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(
            seekdialog.rpc.Settings, "GetProperties",
            lambda **kw: {"currentsubtitle": {"codec": "PGS"}})
        patcher.start()
        self.addCleanup(patcher.stop)

        dialog = make_dialog(selected=FakeStream(""))
        self.assertEqual(dialog.currentSubtitleCodec(), "pgs")

    def test_no_subtitle_at_all_is_not_treated_as_a_bitmap(self):
        dialog = make_dialog(selected=None)
        self.assertEqual(dialog.currentSubtitleCodec(), "")
        self.assertNotIn("", seekdialog.SeekDialog.BITMAP_SUBTITLE_CODECS)

    def test_bitmap_tracks_are_not_offered_as_text_alternatives(self):
        streams = [FakeStream("pgs"), FakeStream("srt", "English"),
                   FakeStream("vobsub"), FakeStream("ass", "Signs")]
        dialog = make_dialog(streams=streams)

        titles = [str(s) for s in dialog.textSubtitleStreams()]
        self.assertEqual(titles, ["English", "Signs"])

    def test_a_pgs_track_never_writes_a_font_size(self):
        """
        The regression. The size was written and persisted, so the setting
        genuinely changed - it just could not reach a bitmap, and the control
        gave no sign of it.

        The choice has to be primed, or the size dropdown returns None and the
        write is skipped for the wrong reason - which is how this test first
        passed against the unfixed code.
        """
        self._patch(choice={"key": 74})
        dialog = make_dialog(streams=[FakeStream("pgs")],
                             selected=FakeStream("pgs"))
        dialog.subtitleSizeClicked()

        self.assertEqual(self.recorder.written, [])

    def test_a_text_track_still_writes_the_font_size(self):
        self._patch(choice={"key": 52})
        dialog = make_dialog(streams=[FakeStream("srt")],
                             selected=FakeStream("srt"))
        dialog.subtitleSizeClicked()

        self.assertEqual(self.recorder.written, [("subtitles.fontsize", 52)])

    def test_pgs_with_no_text_track_explains_rather_than_switching(self):
        dialog = make_dialog(streams=[FakeStream("pgs")],
                             selected=FakeStream("pgs"))
        dialog.subtitleSizeClicked()

        self.assertEqual(len(self.recorder.messages), 1)
        self.assertIn("PGS", self.recorder.messages[0])
        self.assertEqual(dialog.player.video.selected, [])

    def test_choosing_a_text_track_selects_and_applies_it(self):
        english = FakeStream("srt", "English")
        self._patch(choice={"key": english})
        dialog = make_dialog(streams=[FakeStream("pgs"), english],
                             selected=FakeStream("pgs"))
        dialog.subtitleSizeClicked()

        self.assertEqual(dialog.player.video.selected, [english])
        self.assertEqual(dialog.subtitlesApplied, 1)
        self.assertEqual(self.recorder.written, [])

    def test_declining_the_switch_leaves_the_stream_alone(self):
        dialog = make_dialog(streams=[FakeStream("pgs"), FakeStream("srt", "English")],
                             selected=FakeStream("pgs"))
        dialog.subtitleSizeClicked()

        self.assertEqual(dialog.player.video.selected, [])
        self.assertEqual(dialog.subtitlesApplied, 0)

    def test_every_offered_size_is_inside_kodis_own_range(self):
        for value, _label in seekdialog.SeekDialog.SUBTITLE_SIZES:
            with self.subTest(value=value):
                self.assertGreaterEqual(value, 12)
                self.assertLessEqual(value, 74)
                self.assertEqual(value % 2, 0)
