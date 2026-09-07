# coding=utf-8
"""
Search-as-you-type for things to download.

A keyboard dialog that hands back a string is the wrong shape here: you cannot
tell whether "severence" was a typo until after you have pressed OK, and half
the point of adding from the couch is not knowing the exact title. So this is
PM4K's own live-search pattern - an edit control, a debounce, and a worker -
pointed at Sonarr and Radarr's lookup instead of at the Plex server.

Results say what they are and whether you already have them, so the answer to
"is this in my library" arrives before you act rather than after.
"""

from __future__ import absolute_import

import threading
import time

from kodi_six import xbmc
from kodi_six import xbmcgui

from lib import util
from lib.i18n import T

from . import kodigui
from . import windowutils

# Long enough that typing does not fire a request per keystroke, short enough
# that pausing feels like it answered immediately.
DEBOUNCE = 0.6


class ArrSearchDialog(kodigui.BaseDialog, windowutils.UtilMixin):
    xmlFile = 'script-plex-arr_search.xml'
    path = util.ADDON.getAddonInfo('path')
    theme = 'Main'
    res = '1080i'
    width = 1920
    height = 1080

    EDIT_CONTROL_ID = 650
    EDIT_LABEL_ID = 651
    LIST_ID = 101

    def __init__(self, *args, **kwargs):
        kodigui.BaseDialog.__init__(self, *args, **kwargs)
        self.services = kwargs.get('services') or {}
        self.chosen = None
        self.candidates = []
        self.searchThread = None
        self.searchUntil = 0
        self.lastQuery = None

    def onFirstInit(self):
        self.listControl = kodigui.ManagedControlList(self, self.LIST_ID, 10)
        self.edit = kodigui.SafeControlEdit(self.EDIT_CONTROL_ID, self.EDIT_LABEL_ID, self,
                                            key_callback=self.onTyped, grab_focus=True)
        self.setProperty('status', T(35114, "Type to search"))
        self.setFocusId(self.EDIT_CONTROL_ID)

    def onTyped(self, actionID=None, oldVal=None, newVal=None):
        if actionID == xbmcgui.ACTION_PREVIOUS_MENU:
            self.doClose()
            return
        self.scheduleSearch()

    def onClick(self, controlID):
        if controlID == self.LIST_ID:
            mli = self.listControl.getSelectedItem()
            if mli and mli.dataSource:
                self.chosen = mli.dataSource
                self.doClose()

    def scheduleSearch(self):
        """
        Every keystroke pushes the deadline out; the worker waits for it to
        stop moving. One request per pause, not one per letter.
        """
        self.searchUntil = time.time() + DEBOUNCE
        if self.searchThread and self.searchThread.is_alive():
            return
        self.searchThread = threading.Thread(target=self._search, name='arr.search')
        self.searchThread.daemon = True
        self.searchThread.start()

    def _search(self):
        while time.time() < self.searchUntil:
            if util.MONITOR.waitForAbort(0.1):
                return

        query = self.edit.getText().strip()
        if query == self.lastQuery:
            return
        self.lastQuery = query
        if len(query) < 2:
            self.candidates = []
            self.draw(T(35114, "Type to search"))
            return

        self.setProperty('status', T(35115, "Searching..."))
        found = []
        for flavour, client in sorted(self.services.items()):
            try:
                found.extend(client.lookup(query))
            except Exception:
                util.DEBUG_LOG("ArrSearch: {0} did not answer", flavour)

        # The query may have moved on while the services were thinking.
        if query != self.edit.getText().strip():
            return
        self.candidates = found
        self.draw(T(35116, "{0} found").format(len(found)) if found
                  else T(35095, "Nothing found for {0}").format(query))

    def draw(self, status):
        items = []
        for candidate in self.candidates[:50]:
            mli = kodigui.ManagedListItem(candidate.display,
                                          candidate.overview[:120],
                                          thumbnailImage=candidate.poster or '',
                                          data_source=candidate)
            mli.setProperty('thumb.fallback', 'script.plex/thumb_fallbacks/{0}.png'.format(
                'show' if candidate.source == 'sonarr' else 'movie'))
            if candidate.added:
                mli.setProperty('state', T(35096, "already added"))
                mli.setProperty('state.colour', 'FF5CD05C')
            items.append(mli)
        self.listControl.replaceItems(items)
        self.setProperty('status', status)

    def onAction(self, action):
        try:
            if action == xbmcgui.ACTION_NAV_BACK and self.getFocusId() != self.EDIT_CONTROL_ID:
                self.setFocusId(self.EDIT_CONTROL_ID)
                return
        except Exception:
            util.ERROR()
        kodigui.BaseDialog.onAction(self, action)


def search(services):
    """Run the dialog and hand back whatever was chosen, or None."""
    dialog = ArrSearchDialog.open(services=services)
    chosen = dialog.chosen
    del dialog
    xbmc.sleep(100)
    return chosen
