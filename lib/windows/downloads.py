# coding=utf-8
"""
The Downloads window: what the stack still owes you.

Polling happens on a background thread and the window only ever draws from the
last snapshot, so a slow or dead service costs a redraw, never the UI thread.
"""

from __future__ import absolute_import

import time

from kodi_six import xbmc
from kodi_six import xbmcgui

from plexnet import plexapp

from lib import backgroundthread
from lib import util
from lib.downloads import discovery, model
from lib.downloads.config import DownloadsConfig
from lib.downloads.manager import DownloadsManager
from lib.i18n import T

from . import kodigui
from . import windowutils

STATE_LABELS = {
    model.DOWNLOADING: (35052, "Downloading"),
    model.IMPORTING: (35053, "Importing"),
    model.QUEUED: (35054, "Queued"),
    model.STALLED: (35055, "Stalled"),
    model.PAUSED: (35056, "Paused"),
    model.FAILED: (35057, "Failed"),
    model.DONE: (35058, "Done"),
}

REFRESH_SECONDS = 20

# The home screen polls at this interval so the notification about a finished
# grab arrives while you are sitting in front of it, not on next open.
AMBIENT_SECONDS = 60

MANAGER = None
_lastAmbient = 0


def manager():
    """One manager for the whole add-on: two of them would poll twice and
    notify twice about the same finished download."""
    global MANAGER
    if MANAGER is None:
        MANAGER = DownloadsManager()
    return MANAGER


def reset():
    global MANAGER
    MANAGER = None


class RefreshTask(backgroundthread.Task):
    def setup(self, manager, callback):
        self.manager = manager
        self.callback = callback
        return self

    def run(self):
        if self.isCanceled():
            return
        snapshot = self.manager.refresh()
        if not self.isCanceled():
            self.callback(snapshot)


class DiscoveryTask(backgroundthread.Task):
    def setup(self, config, callback):
        self.config = config
        self.callback = callback
        return self

    def run(self):
        if self.isCanceled():
            return
        server = getattr(plexapp.SERVERMANAGER, "selectedServer", None)
        found = discovery.discover(server)
        if found:
            self.config.remember(found)
        if not self.isCanceled():
            self.callback(found)


def announce(finished):
    """Tell the user what landed, and optionally point Plex at it."""
    for item in finished:
        util.showNotification(T(35077, "{0} finished downloading").format(item.title),
                              header=T(35059, "Downloads"))
    if not util.getSetting("downloads_scan_on_finish", False):
        return

    types = set(item.section_type for item in finished if item.section_type)
    if not types:
        return
    server = getattr(plexapp.SERVERMANAGER, "selectedServer", None)
    if not server or not getattr(server, "owned", False):
        return
    for section in server.library.sections():
        if getattr(section, "TYPE", None) in types:
            try:
                section.refresh()
            except Exception:
                util.ERROR("downloads: scan after finish failed")


def tick(force=False):
    """
    Called from the home screen's cron. Polls at most every AMBIENT_SECONDS and
    only when something is configured, so an unused feature costs nothing.
    """
    global _lastAmbient
    # Runs on the cron thread that drives the whole home screen: whatever goes
    # wrong in here must not stop the rest of it ticking.
    try:
        mgr = manager()
        if not mgr.configured():
            return False
        if not force and time.time() - _lastAmbient < AMBIENT_SECONDS:
            return False
        _lastAmbient = time.time()
        backgroundthread.BGThreader.addTask(AmbientTask().setup(mgr))
        return True
    except Exception:
        util.ERROR("downloads: ambient poll failed")
        return False


class AmbientTask(backgroundthread.Task):
    def setup(self, mgr):
        self.mgr = mgr
        return self

    def run(self):
        if self.isCanceled():
            return
        snapshot = self.mgr.refresh()
        finished = [self.mgr.finishedItems(key) for key in self.mgr.finished()]
        count, percent = snapshot.summary()
        util.setGlobalProperty("downloads.count", count and str(count) or "")
        util.setGlobalProperty("downloads.percent", count and str(percent) or "")
        announce([item for item in finished if item])


class DownloadsWindow(kodigui.ControlledWindow, windowutils.UtilMixin):
    xmlFile = 'script-plex-downloads.xml'
    path = util.ADDON.getAddonInfo('path')
    theme = 'Main'
    res = '1080i'
    width = 1920
    height = 1080

    LIST_ID = 101
    OPTIONS_GROUP_ID = 200
    HOME_BUTTON_ID = 201
    REFRESH_BUTTON_ID = 203
    PLAYER_STATUS_BUTTON_ID = 204

    def __init__(self, *args, **kwargs):
        kodigui.ControlledWindow.__init__(self, *args, **kwargs)
        self.manager = kwargs.get('manager') or manager()
        self.exitCommand = None
        self.lastRefresh = 0
        self.task = None

    def onFirstInit(self):
        self.listControl = kodigui.ManagedControlList(self, self.LIST_ID, 10)
        self.setProperty('heading', T(35059, "Downloads"))
        self.draw(self.manager.snapshot)
        self.refresh(force=True)
        self.setFocusId(self.LIST_ID)

    def onAction(self, action):
        try:
            if time.time() - self.lastRefresh > REFRESH_SECONDS:
                self.refresh()
        except Exception:
            util.ERROR()
        kodigui.ControlledWindow.onAction(self, action)

    def onClick(self, controlID):
        if controlID == self.HOME_BUTTON_ID:
            self.goHome()
        elif controlID == self.REFRESH_BUTTON_ID:
            self.refresh(force=True)
        elif controlID == self.PLAYER_STATUS_BUTTON_ID:
            self.showAudioPlayer()

    def onClosed(self):
        if self.task:
            self.task.cancel()

    def refresh(self, force=False):
        if not self.manager.configured():
            self.discover()
            return
        if self.task and not self.task.isValid():
            self.task = None
        if self.task and not force:
            return

        self.lastRefresh = time.time()
        self.setBoolProperty('refreshing', True)
        self.task = RefreshTask().setup(self.manager, self.onRefreshed)
        backgroundthread.BGThreader.addTask(self.task)

    def onRefreshed(self, snapshot):
        self.task = None
        self.setBoolProperty('refreshing', False)
        finished = [self.manager.finishedItems(key) for key in self.manager.finished()]
        announce([item for item in finished if item])
        self.draw(snapshot)

    def discover(self):
        """
        Nothing configured: go and look, rather than sending someone to a
        settings screen to type an address with a remote.
        """
        self.drawEmpty(T(35064, "Refreshing"))
        self.setBoolProperty('refreshing', True)
        self.task = DiscoveryTask().setup(DownloadsConfig(), self.onDiscovered)
        backgroundthread.BGThreader.addTask(self.task)

    def onDiscovered(self, found):
        self.task = None
        self.setBoolProperty('refreshing', False)
        reset()
        self.manager = manager()
        if not found:
            self.drawEmpty(T(35075, "No services found"))
            return
        util.showNotification(T(35074, "Found: {0}").format(", ".join(sorted(found))),
                              header=T(35059, "Downloads"))
        if self.manager.configured():
            self.refresh(force=True)
        else:
            # Found them, but they still want a key we do not have.
            self.drawEmpty(T(35074, "Found: {0}").format(", ".join(sorted(found))))

    def draw(self, snapshot):
        items = [self.createListItem(item) for item in snapshot.items]
        self.listControl.replaceItems(items)
        self.setBoolProperty('no.content', not items)

        if snapshot.errors:
            self.setProperty('status', T(35061, "Not answering: {0}").format(
                ", ".join(sorted(snapshot.errors))))
        elif snapshot.updated:
            count, percent = snapshot.summary()
            self.setProperty('status', T(35062, "{0} active").format(count) if count
                             else T(35063, "Nothing downloading"))
        if not items and not snapshot.errors and snapshot.updated:
            self.drawEmpty(T(35063, "Nothing downloading"))

    def drawEmpty(self, message):
        self.listControl.reset()
        self.setBoolProperty('no.content', True)
        self.setProperty('status', message)

    def createListItem(self, item):
        state_id, state_default = STATE_LABELS.get(item.state, STATE_LABELS[model.QUEUED])
        mli = kodigui.ManagedListItem(
            item.title,
            item.subtitle,
            data_source=item,
        )
        mli.setProperty('state', T(state_id, state_default))
        mli.setProperty('state.key', item.state)
        mli.setProperty('percent', str(item.percent))
        mli.setProperty('percent.display', "{0}%".format(item.percent))
        mli.setProperty('eta', item.etaDisplay())
        mli.setProperty('size', item.sizeDisplay())
        mli.setProperty('source', item.source)
        mli.setProperty('message', item.message or '')
        return mli


def show(parent=None, manager=None):
    window = DownloadsWindow.open(manager=manager)
    del window


def configured():
    """Cheap enough to ask before offering the menu entry."""
    try:
        return bool(DownloadsConfig().clients())
    except Exception:
        util.ERROR("downloads: could not read configuration")
        return False
