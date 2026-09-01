# coding=utf-8

from kodi_six import xbmcgui
from plexnet import plexapp
from lib import util
from .. import busy
from .. import optionsdialog
from lib.i18n import T


class CommonMixin(object):
    @classmethod
    def isWatchedAction(cls, action):
        return action == xbmcgui.ACTION_NONE and action.getButtonCode() == 61527

    def toggleWatched(self, item, state=None, **kw):
        """

        :param item:
        :param state: the state we want to set watched to
        :param kw:
        :return:
        """
        if state is None:
            state = not item.isFullyWatched

        if util.getSetting('home_confirm_actions') and item.TYPE in ('season', 'show'):
            if item.TYPE == 'season':
                title = u"{} - {}".format(item.parentTitle, item.title)
            else:
                title = item.title
            button = optionsdialog.show(
                T(32319, "Mark Played") if state else T(32318, "Mark Unplayed"),  title,
                T(32328, 'Yes'),
                T(32329, 'No'),
                dialog_props=getattr(self, "carriedProps", getattr(self, "dialogProps", None))
            )

            if button != 0:
                return

        util.DEBUG_LOG("Toggling watched for {} to: {}", item, state)

        if state:
            item.markWatched(**kw)
            return True
        else:
            item.markUnwatched(**kw)
            return False

    @staticmethod
    def canManageLibrary(section):
        """
        Whether to offer the jobs the server runs on a section - scan, analyze,
        empty trash.

        Only the server's owner may start them; for anyone else the request
        comes back 403 and there is nothing the viewer can do about it, so the
        option should not be there at all. isAdmin on its own is not enough - it
        says this account is not a managed user, not that it owns the server the
        section lives on.

        The numeric key is the positive test for "a real library section": the
        server only addresses scannable sections by id, while the pseudo
        sections the client invents (home, playlists, watchlist) carry names.
        """
        if section is None or not getattr(section, "key", None):
            return False
        if not str(section.key).isdigit():
            return False
        # ACCOUNT stays None until plexapp.init() has run: building a menu
        # should not be the thing that raises on a half-signed-in client.
        return bool(getattr(plexapp.ACCOUNT, "isAdmin", False)
                    and getattr(getattr(section, "server", None), "owned", False))

    def scanLibrary(self, section):
        """
        Ask the server to scan the section's files for changes.

        The server answers as soon as it has queued the job, not when the scan
        is done, so the notification says it started. Without one there is no
        feedback at all: a scan that never ran and a scan that found nothing
        look identical from here.
        """
        heading = T(33082, "Scan Library Files")

        # BusyContext.__exit__ returns True, so it swallows whatever its body
        # raised (having logged it) - wrapping the `with` in try/except would
        # never fire. Carry the outcome out of the block instead.
        started = []
        with busy.BusyContext(delay=True, delay_time=0.2):
            section.refresh()
            started.append(True)

        if not started:
            util.showNotification(T(35051, "Could not start the scan"), header=heading)
            return False

        util.DEBUG_LOG("Scanning library section {0} ({1})", section.key, section.title)
        util.showNotification(T(35050, "Scanning {0}").format(section.title), header=heading)
        return True
