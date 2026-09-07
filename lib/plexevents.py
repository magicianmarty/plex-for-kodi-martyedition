# coding=utf-8
"""
Server-sent events from Plex, so the client hears about new content instead of
waiting to notice it.

Without this the only way a new film reaches the screen is the five minute hub
staleness window, or a manual refresh - which is why something you added
minutes ago is not there yet.

Plex offers the same notifications over a WebSocket and over SSE. SSE is used
here because it is a plain streaming GET: requests already ships with the
add-on, where a WebSocket client would have to be vendored and stubbed.

What the stream actually looks like, recorded off PMS 1.43.3 during one scan of
a movie section:

    1556  event: activity     ActivityNotification, mostly 'updated'
       4  event: status       StatusNotification, LIBRARY_UPDATE
       2  event: timeline     TimelineEntry, one per item that changed
       2  event: ping         keepalive

So `activity` is a firehose - one message per file scanned - with exactly one
useful message in it: the 'ended' of a library.update.section, which carries the
section id. That is the refresh trigger. `timeline` is rare and precise, and
carries the item's title, which is what a notification can name.
"""

from __future__ import absolute_import

import json
import threading
import time

import requests

from plexnet import plexapp

from . import util

# The stream is only interesting for these; asking for the rest just adds noise.
FILTERS = "timeline,activity,status"

SECTION_SCAN = "library.update.section"
LIBRARY_UPDATE = "LIBRARY_UPDATE"

# TimelineEntry.state 5 is "done with this item".
TIMELINE_FINAL = 5

# How long the same itemID is treated as old news. The server re-emits state 5
# for it every ~40 seconds while it is still working, and each emission arrives
# twice - once carrying mediaState, once without. Nothing here notifies any
# more (that comes from the download services\' own import history), so this
# only has to stop pointless redraws, and a short window does that.
SEEN_TTL = 300
SEEN_MAX = 500

# A scan emits its 'ended' per section, but metadata and analysis land after it,
# so collapse a burst into one refresh rather than redrawing repeatedly.
DEBOUNCE_SECONDS = 3.0

# Longer than the server's keepalive: a silent stream is a dead stream, but
# pings arrive every ~15s so this only fires when something really broke.
READ_TIMEOUT = 60
CONNECT_TIMEOUT = 10

RECONNECT_MIN = 5
RECONNECT_MAX = 120


def parseStream(lines):
    """
    Turn raw SSE lines into (event name, payload dict).

    Written against the recorded stream: 'event: <name>', then 'data: <json>',
    then a blank line. Anything that does not fit that shape is skipped rather
    than killing the listener - this is a long-lived connection and one odd
    frame must not end it.
    """
    name = None
    for line in lines:
        if line is None:
            continue
        line = line.strip()
        if not line:
            name = None
            continue
        if line.startswith("event:"):
            name = line[len("event:"):].strip()
        elif line.startswith("data:"):
            raw = line[len("data:"):].strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except ValueError:
                continue
            if isinstance(payload, dict):
                yield name or "message", payload


def readEvent(name, payload):
    """
    What one event means to us: (kind, section id, title, item id).

    kind is 'scan' when a section finished scanning, 'item' when a single thing
    changed, and None for the 1500 messages per scan that mean nothing to a
    client.
    """
    if name == "activity" or "ActivityNotification" in payload:
        notification = payload.get("ActivityNotification") or {}
        activity = notification.get("Activity") or {}
        if activity.get("type") != SECTION_SCAN:
            return None, None, None, None
        if notification.get("event") != "ended":
            return None, None, None, None
        context = activity.get("Context") or {}
        return "scan", context.get("librarySectionID"), activity.get("title"), None

    if name == "timeline" or "TimelineEntry" in payload:
        entry = payload.get("TimelineEntry") or {}
        if entry.get("state") != TIMELINE_FINAL:
            return None, None, None, None
        # Every settled entry arrives twice, once with mediaState ("analyzing")
        # and once without. The one still naming a media operation is the
        # server telling us it is mid-job, not that something arrived.
        if entry.get("mediaState"):
            return None, None, None, None
        return "item", entry.get("sectionID"), entry.get("title"), str(entry.get("itemID") or "")

    # StatusNotification/LIBRARY_UPDATE is deliberately not a trigger. Watching
    # a live server shows it firing at the *start* of a scan ("Scanning the
    # Movies section") as well as at the end, and it names no section - so
    # acting on it refreshes everything before anything has changed. The
    # section-scoped events above already cover the end of a scan.
    return None, None, None, None


class EventListener(threading.Thread):
    """
    Holds the connection to one server and fires plexapp signals.

    Signals raised, both on the listener's own thread:
        library:updated   sectionID, titles
        library:events    connected (bool), for anything that wants to know
                          whether it is still on the polling fallback
    """

    def __init__(self, server, debounce=DEBOUNCE_SECONDS):
        threading.Thread.__init__(self, name="PLEX:EVENTS")
        self.daemon = True
        self.server = server
        self.debounce = debounce
        self.stopped = threading.Event()
        self.connected = False
        self._pending = {}
        self._pendingSince = 0
        self._seen = {}

    @property
    def url(self):
        return self.server.buildUrl("/:/eventsource/notifications?filters={0}".format(FILTERS),
                                    includeToken=True)

    def stop(self):
        self.stopped.set()

    def run(self):
        backoff = RECONNECT_MIN
        while not self.stopped.is_set() and not util.MONITOR.abortRequested():
            try:
                self.listen()
                backoff = RECONNECT_MIN
            except Exception as e:
                self.setConnected(False)
                util.DEBUG_LOG("PlexEvents: {0}; retrying in {1}s", e, backoff)
                if util.MONITOR.waitForAbort(backoff):
                    break
                backoff = min(backoff * 2, RECONNECT_MAX)
        self.setConnected(False)
        util.DEBUG_LOG("PlexEvents: stopped")

    def listen(self):
        response = requests.get(self.url, stream=True,
                                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                                headers={"Accept": "text/event-stream"})
        if response.status_code != 200:
            raise IOError("HTTP {0}".format(response.status_code))

        self.setConnected(True)
        util.DEBUG_LOG("PlexEvents: listening to {0}", self.server.name)
        try:
            for name, payload in parseStream(response.iter_lines(decode_unicode=True)):
                if self.stopped.is_set() or util.MONITOR.abortRequested():
                    break
                self.handle(name, payload)
                self.flush()
            self.flush(force=True)
        finally:
            response.close()

    def handle(self, name, payload):
        kind, section, title, itemID = readEvent(name, payload)
        if not kind:
            return
        if kind == "item" and not self.firstSighting(itemID):
            return

        titles = self._pending.setdefault(section, [])
        if kind == "item" and title and title not in titles:
            titles.append(title)
        if not self._pendingSince:
            self._pendingSince = time.time()

    def firstSighting(self, itemID):
        """
        Whether this item is news. The same itemID comes back every time the
        server touches it again, and announcing each one is the difference
        between "Conan the Barbarian arrived" and being told so all evening.
        """
        if not itemID:
            return True
        now = time.time()
        if now - self._seen.get(itemID, 0) < SEEN_TTL:
            return False
        if len(self._seen) >= SEEN_MAX:
            for key, seen in sorted(self._seen.items(), key=lambda kv: kv[1])[:SEEN_MAX // 2]:
                del self._seen[key]
        self._seen[itemID] = now
        return True

    def flush(self, force=False):
        if not self._pending:
            return
        if not force and time.time() - self._pendingSince < self.debounce:
            return
        pending, self._pending = self._pending, {}
        self._pendingSince = 0
        for section, titles in pending.items():
            util.DEBUG_LOG("PlexEvents: section {0} changed ({1} named items)", section, len(titles))
            plexapp.util.APP.trigger("library:updated", sectionID=section, titles=titles)

    def setConnected(self, state):
        if state == self.connected:
            return
        self.connected = state
        plexapp.util.APP.trigger("library:events", connected=state)


class EventManager(object):
    """Keeps one listener pointed at whichever server is selected."""

    def __init__(self):
        self.listener = None

    def start(self, server=None):
        if not util.getSetting("library_events", True):
            return False
        server = server or getattr(plexapp.SERVERMANAGER, "selectedServer", None)
        if not server:
            return False
        self.stop()
        self.listener = EventListener(server)
        self.listener.start()
        return True

    def stop(self):
        if not self.listener:
            return
        self.listener.stop()
        self.listener = None

    @property
    def connected(self):
        return bool(self.listener and self.listener.connected)

    def onServerChange(self, *args, **kwargs):
        self.start()


MANAGER = EventManager()


def start():
    """
    Fails quietly on purpose: without the stream the client still refreshes on
    its five minute staleness window, so this is an improvement, never a
    dependency.
    """
    try:
        plexapp.util.APP.on("change:selectedServer", MANAGER.onServerChange)
        return MANAGER.start()
    except Exception:
        util.ERROR("PlexEvents: could not start")
        return False


def stop():
    try:
        plexapp.util.APP.off("change:selectedServer", MANAGER.onServerChange)
        MANAGER.stop()
    except Exception:
        util.ERROR("PlexEvents: could not stop cleanly")
