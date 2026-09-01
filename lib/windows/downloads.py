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
from lib.downloads import arr, discovery, model, qbittorrent
from lib.downloads.config import DownloadsConfig
from lib.downloads.manager import DownloadsManager
from lib.i18n import T

from . import arrsearch
from . import busy
from . import dropdown
from . import kodigui
from . import optionsdialog
from . import windowutils

STATE_COLOURS = {
    model.DOWNLOADING: "FFE5A00D",
    model.IMPORTING: "FF5CD05C",
    model.STALLED: "FFCC7B19",
    model.FAILED: "FFE54B4B",
}
DEFAULT_STATE_COLOUR = "FFB4B4B4"

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


class CallTask(backgroundthread.Task):
    """Runs one service call off the UI thread and keeps whatever it returned."""

    def setup(self, call):
        self.call = call
        self.result = None
        self.failed = None
        return self

    def run(self):
        if self.isCanceled():
            return
        try:
            self.result = self.call()
        except Exception as e:
            self.failed = e


def runOffThread(call, message=None):
    """
    Do something slow without freezing Kodi.

    An interactive search takes tens of seconds - the *arr asks every indexer -
    and the UI thread cannot simply block for that: the spinner would freeze
    with it. Hand it to a worker and pump the UI while waiting.
    """
    task = CallTask().setup(call)
    backgroundthread.BGThreader.addTask(task)
    with busy.BusyContext(delay=True, delay_time=0.2):
        while not task.finished and not util.MONITOR.abortRequested():
            xbmc.sleep(100)
    if task.failed:
        util.ERROR('downloads: {0}'.format(message or 'call failed'))
        return None
    return task.result


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
    """
    Tell the user what landed, and optionally point Plex at it.

    Two rules, both learned the hard way: only things the service actually
    imported get announced, and nothing interrupts playback - a popup over a
    film is worse than finding out afterwards.
    """
    if not finished or not util.getSetting("downloads_notify", True):
        return
    if xbmc.getCondVisibility("Player.HasVideo"):
        util.DEBUG_LOG("Downloads: {0} finished, not announcing over playback", len(finished))
        return

    for item in finished[:3]:
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


def fetchOption(call, heading):
    """A service call that must not take the UI down if it fails."""
    got = []
    with busy.BusyContext(delay=True, delay_time=0.2):
        got.append(call())
    if not got:
        util.ERROR("downloads: could not read {0}".format(heading))
        return None
    return got[0]


def chooseOption(options, heading, setting, index):
    """
    One of the service's options, asked once and then remembered - nobody wants
    to answer "which quality profile" on every add. `index` picks which half of
    the (id, label) pair the caller needs: a profile is added by id, a root
    folder by path.
    """
    if not options:
        return None
    if len(options) == 1:
        return options[0][index]

    remembered = util.getSetting(setting, '')
    for value, label in options:
        if str(value) == remembered or label == remembered:
            return (value, label)[index]

    entries = [{'key': value, 'display': u'{0}'.format(label), 'label': label}
               for value, label in options]
    choice = dropdown.showDropdown(entries, (600, 300), header=heading, with_indicator=False)
    if not choice:
        return None
    util.setSetting(setting, str(choice['key']))
    return choice['key'] if index == 0 else choice['label']


def addCandidate(client, candidate):
    """Ask the two questions that matter, then add it and start the search."""
    heading = T(35098, "Quality")
    profile = chooseOption(fetchOption(client.profiles, heading), heading,
                           'downloads_profile', 0)
    if profile is None:
        return False

    heading = T(35099, "Where to put it")
    root = chooseOption(fetchOption(client.rootFolders, heading), heading,
                        'downloads_root', 1)
    if root is None:
        return False

    if optionsdialog.show(T(35100, "Download {0}?").format(candidate.display),
                          T(35101, "It will be added and searched for straight away."),
                          T(32328, 'Yes'), T(32329, 'No')) != 0:
        return False

    added = []
    with busy.BusyContext(delay=True, delay_time=0.2):
        client.add(candidate, profile, root)
        added.append(True)

    if not added:
        util.showNotification(T(35093, "That did not work"), header=T(35059, "Downloads"))
        return False

    util.showNotification(T(35102, "Looking for {0}").format(candidate.title),
                          header=T(35059, "Downloads"))
    return True


def addForPlexItem(item):
    """
    Send something you are already looking at to the stack.

    No keyboard and no fuzzy matching: a Plex item carries tmdb:// and tvdb://
    ids alongside its own guid, and that is exactly what lookup takes.
    """
    services = manager().services()
    if not services:
        util.showNotification(T(35060, "No download services configured"),
                              header=T(35059, "Downloads"))
        return False

    flavour = arr.flavourFor(item)
    client = services.get(flavour)
    if not client:
        return False

    term = arr.lookupTerm(item, flavour)
    found = []
    with busy.BusyContext(delay=True, delay_time=0.2):
        found.extend(client.lookup(term))

    if not found:
        util.showNotification(T(35095, "Nothing found for {0}").format(term),
                              header=T(35059, "Downloads"))
        return False

    candidate = found[0]
    if candidate.added:
        util.showNotification(T(35097, "{0} is already in your library").format(candidate.title),
                              header=T(35059, "Downloads"))
        return False
    return addCandidate(client, candidate)


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
        finished = self.mgr.finished()
        count, percent = snapshot.summary()
        util.setGlobalProperty("downloads.count", count and str(count) or "")
        util.setGlobalProperty("downloads.percent", count and str(percent) or "")
        announce(finished)
        plexapp.util.APP.trigger("downloads:updated", count=count)


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
    SCAN_BUTTON_ID = 205
    ADD_BUTTON_ID = 206

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
        self.focusBest()

    def focusBest(self):
        """
        Focus something that exists.

        The list is hidden while it is empty, and a window whose focus lands on
        a hidden control backs straight out again - which is exactly what
        happened on the first open, before any poll had filled the cache.
        """
        if self.listControl.size():
            self.setFocusId(self.LIST_ID)
        else:
            self.setFocusId(self.SCAN_BUTTON_ID)

    def onAction(self, action):
        try:
            if action == xbmcgui.ACTION_CONTEXT_MENU and self.getFocusId() == self.LIST_ID:
                self.itemMenu()
                return
            if time.time() - self.lastRefresh > REFRESH_SECONDS:
                self.refresh()
        except Exception:
            util.ERROR()
        kodigui.ControlledWindow.onAction(self, action)

    def selected(self):
        mli = self.listControl.getSelectedItem()
        return mli.dataSource if mli else None

    def itemMenu(self):
        """
        What you can do to the row you are looking at. Everything here writes
        to the service, so everything here is confirmed first.
        """
        item = self.selected()
        if not item:
            return
        client = self.manager.clientFor(item)
        if not client:
            return

        torrent = item.source == qbittorrent.QBITTORRENT
        options = []
        if torrent:
            # A torrent client has no notion of searching again; it has a tap.
            options.append({'key': 'pause', 'display': T(35105, "Pause")})
            options.append({'key': 'resume', 'display': T(35106, "Resume")})
        options.append({'key': 'remove', 'display': T(35087, "Remove from queue")})
        if not torrent:
            options.append({'key': 'blocklist',
                            'display': T(35088, "Remove and never take that release")})
        if getattr(item, 'parent_id', None):
            options.append({'key': 'search', 'display': T(35089, "Search again")})
            options.append({'key': 'releases', 'display': T(35107, "Choose a release yourself")})

        choice = dropdown.showDropdown(options, (600, 400), with_indicator=False)
        if not choice:
            return
        if choice['key'] == 'search':
            self.runWrite(client.searchAgain, item, T(35090, "Searching again for {0}"))
            return
        if choice['key'] == 'releases':
            self.pickRelease(client, item)
            return
        if choice['key'] == 'pause':
            self.runWrite(client.pause, item, T(35108, "Paused {0}"), forget=False)
            return
        if choice['key'] == 'resume':
            self.runWrite(client.resume, item, T(35109, "Resumed {0}"), forget=False)
            return

        blocklist = choice['key'] == 'blocklist'
        heading = (T(35088, "Remove and never take that release") if blocklist
                   else T(35087, "Remove from queue"))
        # Say what happens to the files, because the answer is "nothing" and
        # people reasonably assume otherwise.
        if optionsdialog.show(heading, T(35091, "{0}\n\nThe downloaded files are left alone.").format(item.title),
                              T(32328, 'Yes'), T(32329, 'No')) != 0:
            return

        self.runWrite(lambda i: client.remove(i, blocklist=blocklist), item,
                      T(35092, "Removed {0}"))

    def pickRelease(self, client, item):
        """
        Take over from the *arr and choose the file yourself.

        This is the fix for a grab that keeps failing: the list says what each
        release is, how well seeded it is, and - for the ones the *arr already
        turned down - why.
        """
        found = runOffThread(lambda: client.releases(item), 'release search')
        if not found:
            util.showNotification(T(35110, "No releases found"), header=T(35059, "Downloads"))
            return False

        options = [{'key': index, 'display': release.display}
                   for index, release in enumerate(found[:40])]
        choice = dropdown.showDropdown(options, (400, 200), with_indicator=False,
                                       header=item.title)
        if not choice:
            return False

        release = found[choice['key']]
        warning = T(35111, "The service rejected this one:\n{0}").format(
            release.rejections[0] if release.rejections else "") if release.rejected else ""
        if optionsdialog.show(T(35107, "Choose a release yourself"),
                              u"{0}\n\n{1}".format(release.title, warning).strip(),
                              T(32328, 'Yes'), T(32329, 'No')) != 0:
            return False

        return self.runWrite(lambda _i: client.grab(release), item,
                             T(35112, "Grabbing {0}"), forget=False)

    def runWrite(self, call, item, message, forget=True):
        """Every write reports what happened: a silent failure looks like a bug."""
        ok = []
        with busy.BusyContext(delay=True, delay_time=0.2):
            call(item)
            ok.append(True)

        if not ok:
            util.showNotification(T(35093, "That did not work"), header=T(35059, "Downloads"))
            return False

        util.showNotification(message.format(item.title), header=T(35059, "Downloads"))
        if forget:
            self.draw(self.manager.forget(item))
        self.refresh(force=True)
        return True

    def onClick(self, controlID):
        if controlID == self.HOME_BUTTON_ID:
            self.goHome()
        elif controlID == self.REFRESH_BUTTON_ID:
            self.refresh(force=True)
        elif controlID == self.SCAN_BUTTON_ID:
            self.scanLibraries()
        elif controlID == self.ADD_BUTTON_ID:
            self.addSomething()
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
        announce(self.manager.finished())
        had = self.listControl.size()
        self.draw(snapshot)
        # First rows to arrive: move focus onto them, since it is parked on the
        # action row while there is nothing to look at.
        if not had and self.listControl.size():
            self.focusBest()

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

    def addSomething(self, term=None, candidates=None, service=None):
        """
        Find something and put it in the stack.

        Built out of the dialogs the add-on already has rather than a new
        window: a keyboard, a dropdown of results, a dropdown of profiles. It
        is also why adding from the Plex watchlist can reuse all of this - it
        just arrives with the term already known.
        """
        services = self.manager.services()
        if not services:
            util.showNotification(T(35060, "No download services configured"),
                                  header=T(35059, "Downloads"))
            return False

        if term is None and candidates is None:
            # Search as you type rather than a keyboard that hands back a
            # string you cannot check until after you commit to it.
            chosen = arrsearch.search(services)
            if not chosen:
                return False
            if chosen.added:
                util.showNotification(T(35097, "{0} is already in your library").format(chosen.title),
                                      header=T(35059, "Downloads"))
                return False
            if addCandidate(services[chosen.source], chosen):
                self.refresh(force=True)
                return True
            return False

        if candidates is None:
            candidates = self.findCandidates(services, term, service)
        if not candidates:
            util.showNotification(T(35095, "Nothing found for {0}").format(term),
                                  header=T(35059, "Downloads"))
            return False

        options = []
        for index, candidate in enumerate(candidates[:20]):
            label = candidate.display
            if candidate.added:
                label = u"{0}  -  {1}".format(label, T(35096, "already added"))
            options.append({'key': index, 'display': label})
        choice = dropdown.showDropdown(options, (600, 300), with_indicator=False)
        if not choice:
            return False

        candidate = candidates[choice['key']]
        if candidate.added:
            util.showNotification(T(35097, "{0} is already in your library").format(candidate.title),
                                  header=T(35059, "Downloads"))
            return False
        if addCandidate(services[candidate.source], candidate):
            self.refresh(force=True)
            return True
        return False

    def findCandidates(self, services, term, service=None):
        """Ask the services that could plausibly own it, newest question first."""
        wanted = [service] if service else list(services)
        found = []
        for flavour in wanted:
            client = services.get(flavour)
            if not client:
                continue
            found.extend(runOffThread(lambda c=client: c.lookup(term),
                                      'lookup on {0}'.format(flavour)) or [])
        return found

    def scanLibraries(self):
        """
        Ask Plex to look for new files in every video library you own. The same
        action as the one in a library's own menu, but here it needs no menu
        dive - this is the screen you are on when you are waiting for something
        to show up.
        """
        server = getattr(plexapp.SERVERMANAGER, "selectedServer", None)
        if not server or not getattr(server, "owned", False):
            util.showNotification(T(35060, "No download services configured"),
                                  header=T(33082, "Scan Library Files"))
            return

        scanned = []
        for section in server.library.sections():
            if getattr(section, "TYPE", None) not in ("movie", "show", "movies_shows"):
                continue
            try:
                section.refresh()
                scanned.append(section.title)
            except Exception:
                util.ERROR("Downloads: scan failed for {0}".format(section.key))

        util.showNotification(T(35050, "Scanning {0}").format(", ".join(scanned) or "-"),
                              header=T(33082, "Scan Library Files"))

    def draw(self, snapshot):
        items = [self.createListItem(item) for item in snapshot.items]
        self.listControl.replaceItems(items)
        self.setBoolProperty('no.content', not items)

        count, percent = snapshot.summary()
        self.setProperty('summary.count', count and str(count) or '')
        self.setProperty('summary.percent', count and "{0}%".format(percent) or '')

        if snapshot.errors:
            self.setProperty('status', T(35061, "Not answering: {0}").format(
                ", ".join(sorted(snapshot.errors))))
        elif snapshot.updated:
            self.setProperty('status', self.summaryLine(snapshot) if count or snapshot.seeding
                             else T(35063, "Nothing downloading"))
        if not items and not snapshot.errors and snapshot.updated:
            self.drawEmpty(T(35063, "Nothing downloading"))

    @staticmethod
    def detailLine(item):
        """
        The one line under the state. Percent and ETA while it moves, size when
        it does not - a paused item showing "0s left" is worse than silence.
        """
        parts = []
        if item.state in (model.DOWNLOADING, model.STALLED):
            parts.append("{0}%".format(item.percent))
            if item.etaDisplay():
                parts.append(item.etaDisplay())
        if item.sizeDisplay():
            parts.append(item.sizeDisplay())
        return "  ·  ".join(parts)

    @staticmethod
    def summaryLine(snapshot):
        """e.g. "3 downloading - 2 importing - 47%"."""
        parts = []
        for state, (ident, default) in ((model.DOWNLOADING, STATE_LABELS[model.DOWNLOADING]),
                                        (model.IMPORTING, STATE_LABELS[model.IMPORTING]),
                                        (model.QUEUED, STATE_LABELS[model.QUEUED]),
                                        (model.FAILED, STATE_LABELS[model.FAILED])):
            hits = [i for i in snapshot.active if i.state == state]
            if hits:
                parts.append("{0} {1}".format(len(hits), T(ident, default).lower()))
        _count, percent = snapshot.summary()
        if percent:
            parts.append("{0}%".format(percent))
        if snapshot.seeding:
            parts.append(T(35113, "{0} seeding").format(snapshot.seeding))
        return "  -  ".join(parts)

    def drawEmpty(self, message):
        self.listControl.reset()
        self.setBoolProperty('no.content', True)
        self.setProperty('status', message)

    def createListItem(self, item):
        state_id, state_default = STATE_LABELS.get(item.state, STATE_LABELS[model.QUEUED])
        mli = kodigui.ManagedListItem(
            item.title,
            item.subtitle,
            thumbnailImage=item.poster or '',
            data_source=item,
        )
        mli.setProperty('thumb.fallback',
                        'script.plex/thumb_fallbacks/{0}.png'.format(
                            'show' if item.section_type == 'show' else 'movie'))
        mli.setProperty('state', T(state_id, state_default))
        mli.setProperty('state.key', item.state)
        mli.setProperty('state.colour', STATE_COLOURS.get(item.state, DEFAULT_STATE_COLOUR))
        mli.setProperty('percent', str(item.percent))
        mli.setProperty('percent.display', "{0}%".format(item.percent))
        mli.setProperty('source', item.source)
        mli.setProperty('detail', self.detailLine(item))
        mli.setProperty('message', item.message or '')
        # The bar is only meaningful while something is actually moving.
        mli.setProperty('has.progress', item.state in (model.DOWNLOADING, model.STALLED,
                                                       model.PAUSED) and '1' or '')
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
