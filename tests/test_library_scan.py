# coding=utf-8
"""
Scan Library Files.

Asking the server to look for new files is the one server-side job people
reach for from a client, and the failure modes are all silent: a request that
never went anywhere, a request that came back 403 because the server is not
yours, or a scan that started and said nothing. So the tests are about the
exact URL, who gets offered the option, and what the user is told afterwards.
"""

from __future__ import absolute_import

from plexnet import plexapp, plexlibrary

from .base import KodiTestCase, ensure_plex_interface, import_window_module

common = import_window_module("lib.windows.mixins.common")
library = import_window_module("lib.windows.library")
busy = import_window_module("lib.windows.busy")


class FakeServer(object):
    def __init__(self, owned=True):
        self.owned = owned
        self.calls = []

    def query(self, path, method=None, **kwargs):
        self.calls.append(path)
        return None


class FakeSection(object):
    """A library section as the mixin sees it, with a recording refresh()."""

    def __init__(self, key="3", title="Movies", owned=True, raises=None, type_="movie"):
        self.key = key
        self.title = title
        self.TYPE = type_
        self.server = FakeServer(owned=owned)
        self.refreshed = 0
        self._raises = raises

    def refresh(self):
        self.refreshed += 1
        if self._raises:
            raise self._raises


class FakeBusyContext(object):
    """
    Stands in for busy.BusyContext, which needs a real window manager.

    Swallowing the exception is not a shortcut - it is what the real one does,
    and scanLibrary() is written around it. BusyContextContractTest keeps that
    assumption honest.
    """

    entered = 0
    exited = 0
    swallowed = None

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        FakeBusyContext.entered += 1
        return self

    def __exit__(self, exc_type, exc_value, tb):
        FakeBusyContext.exited += 1
        FakeBusyContext.swallowed = exc_type
        return True

    @classmethod
    def reset(cls):
        cls.entered = cls.exited = 0
        cls.swallowed = None


class FakeAccount(object):
    """plexapp.ACCOUNT, which is None until plexapp.init() has run."""

    def __init__(self, is_admin=True):
        self.isAdmin = is_admin


class Scanner(common.CommonMixin):
    """The mixin on its own - both windows get it the same way."""


class MixinTestCase(KodiTestCase):
    def setUp(self):
        KodiTestCase.setUp(self)
        ensure_plex_interface()
        self._account = plexapp.ACCOUNT
        plexapp.ACCOUNT = FakeAccount()
        self._busy = busy.BusyContext
        busy.BusyContext = FakeBusyContext
        FakeBusyContext.reset()

    def tearDown(self):
        busy.BusyContext = self._busy
        plexapp.ACCOUNT = self._account
        KodiTestCase.tearDown(self)

    def notifications(self):
        from kodienv import ENV
        return [call for call in ENV.builtins if call.startswith("Notification(")]


class LibrarySectionRefreshTest(KodiTestCase):
    def setUp(self):
        KodiTestCase.setUp(self)
        ensure_plex_interface()

    def section(self, key="3"):
        server = FakeServer()
        section = plexlibrary.LibrarySection(None, server=server)
        section.key = key
        return section, server

    def test_a_scan_hits_this_sections_refresh_endpoint(self):
        """
        PlexObject.refresh() - what LibrarySection would inherit - builds
        '<key>/refresh', and a section's key is the bare id, so the URL would
        come out as '3/refresh'. Nothing in the response tells you it went
        nowhere.
        """
        section, server = self.section("3")
        section.refresh()
        self.assertEqual(["/library/sections/3/refresh"], server.calls)

    def test_a_scan_does_not_force_a_metadata_refresh(self):
        """
        force=1 is a different, far heavier operation: it re-downloads metadata
        for every item in the section and overwrites local edits.
        """
        section, server = self.section("7")
        section.refresh()
        self.assertNotIn("force", server.calls[0])


class CanManageLibraryTest(MixinTestCase):
    def test_an_owned_section_is_manageable(self):
        self.assertTrue(Scanner.canManageLibrary(FakeSection()))

    def test_a_managed_user_is_not_offered_it(self):
        plexapp.ACCOUNT.isAdmin = False
        self.assertFalse(Scanner.canManageLibrary(FakeSection()))

    def test_someone_elses_server_is_not_offered_it(self):
        """The request would come back 403 and the viewer could do nothing."""
        self.assertFalse(Scanner.canManageLibrary(FakeSection(owned=False)))

    def test_the_client_side_pseudo_sections_are_not_offered_it(self):
        for key in (None, "", "playlists", "watchlist", "/library/sections/watchlist"):
            self.assertFalse(Scanner.canManageLibrary(FakeSection(key=key)), repr(key))

    def test_no_section_at_all(self):
        self.assertFalse(Scanner.canManageLibrary(None))

    def test_before_the_account_has_initialised(self):
        plexapp.ACCOUNT = None
        self.assertFalse(Scanner.canManageLibrary(FakeSection()))


class ScanLibraryTest(MixinTestCase):
    def test_a_scan_is_requested_and_reported(self):
        section = FakeSection(title="Films")

        self.assertTrue(Scanner().scanLibrary(section))

        self.assertEqual(1, section.refreshed)
        self.assertEqual(1, FakeBusyContext.entered)
        self.assertTrue([n for n in self.notifications() if "Films" in n])

    def test_a_refused_scan_says_so_instead_of_claiming_it_started(self):
        section = FakeSection(title="Films", raises=Exception("(403) Forbidden"))

        self.assertFalse(Scanner().scanLibrary(section))

        self.assertEqual(1, section.refreshed)
        self.assertEqual(Exception, FakeBusyContext.swallowed)
        notifications = self.notifications()
        self.assertTrue([n for n in notifications if "Could not start the scan" in n])
        self.assertEqual([], [n for n in notifications if "Films" in n])

    def test_a_comma_in_the_title_does_not_eat_the_notification(self):
        """Kodi's builtin splits on unquoted commas; paramify() is what saves us."""
        Scanner().scanLibrary(FakeSection(title="Lock, Stock"))
        self.assertTrue([n for n in self.notifications() if "Lock, Stock" in n])


class BusyContextContractTest(KodiTestCase):
    def test_the_busy_context_swallows_what_its_body_raises(self):
        """
        scanLibrary() carries its outcome out of the with-block in a list
        because of this: a try/except around the block would never fire.
        """
        class Window(object):
            def doClose(self):
                pass

        context = busy.BusyContext.__new__(busy.BusyContext)
        context.timer = None
        context.w = Window()
        self.assertTrue(context.__exit__(ValueError, ValueError("boom"), None))


class LibraryOptionsMenuTest(MixinTestCase):
    def setUp(self):
        MixinTestCase.setUp(self)
        self._dropdown = library.dropdown.showDropdown
        self.offered = []
        library.dropdown.showDropdown = self.fakeDropdown
        self.choose = None

    def tearDown(self):
        library.dropdown.showDropdown = self._dropdown
        MixinTestCase.tearDown(self)

    def fakeDropdown(self, options, *args, **kwargs):
        self.offered = options
        for option in options:
            if option and option.get("key") == self.choose:
                return option
        return None

    def window(self, section):
        window = library.LibraryWindow.__new__(library.LibraryWindow)
        window.section = section
        return window

    def keys(self):
        return [o["key"] for o in self.offered if o]

    def test_the_option_is_offered_on_your_own_library(self):
        self.window(FakeSection()).optionsButtonClicked()
        self.assertIn("scan_library", self.keys())

    def test_it_is_not_offered_on_someone_elses(self):
        self.window(FakeSection(owned=False)).optionsButtonClicked()
        self.assertNotIn("scan_library", self.keys())

    def test_choosing_it_scans_the_library_being_browsed(self):
        section = FakeSection(title="Films")
        self.choose = "scan_library"

        self.window(section).optionsButtonClicked()

        self.assertEqual(1, section.refreshed)
        self.assertTrue([n for n in self.notifications() if "Films" in n])

    def test_dismissing_the_menu_scans_nothing(self):
        section = FakeSection()
        self.window(section).optionsButtonClicked()
        self.assertEqual(0, section.refreshed)


class BothWindowsShareItTest(KodiTestCase):
    def test_the_home_screen_and_the_library_screen_use_the_same_code(self):
        """
        The home screen has had a Scan entry in its section context menu all
        along; it now goes through the same helper, so the permission check and
        the notification cannot drift apart.
        """
        home = import_window_module("lib.windows.home")
        for window in (home.HomeWindow, library.LibraryWindow):
            self.assertTrue(issubclass(window, common.CommonMixin), window.__name__)
