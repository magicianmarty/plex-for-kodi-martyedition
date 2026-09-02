# coding=utf-8
"""
Telling controllers what the player is doing.

A Plex app finds out the state of a player one of two ways, and expects both to
work:

  polling      GET /player/timeline/poll, answered with the current timeline.

  subscription GET /player/timeline/subscribe, after which the *player* posts a
               timeline to the controller every second or so, and on every
               state change. The controller stops asking and waits to be told.

The state itself is not gathered here. NowPlayingManager already tracks it, per
timeline type, because it has to report the same numbers to the server at
/:/timeline - so this reads what is already there rather than watching the
player a second time and drifting from it.

Subscriptions are dropped after SUBSCRIBER_TIMEOUT without the controller
renewing, which is what stops a phone that walked out of the house from
collecting posts forever.
"""

from __future__ import absolute_import

import threading
import time

import requests

from . import protocol

from .. import util

# How often a subscribed controller is posted to while something is playing.
PUSH_INTERVAL = 1.0

# A controller re-subscribes roughly every 30s; this is generous enough to ride
# out a missed renewal without keeping a dead phone on the list.
SUBSCRIBER_TIMEOUT = 90.0

PUSH_TIMEOUT = 5.0


class Subscriber(object):
    def __init__(self, uuid, host, port, command_id=0, protocol_name="http"):
        self.uuid = uuid
        self.host = host
        self.port = int(port)
        self.command_id = int(command_id or 0)
        self.protocol = protocol_name
        self.last_seen = time.time()
        self.failures = 0

    @property
    def url(self):
        return "{0}://{1}:{2}/:/timeline".format(self.protocol, self.host, self.port)

    def renew(self, command_id=None):
        self.last_seen = time.time()
        if command_id is not None:
            self.command_id = int(command_id)

    @property
    def expired(self):
        return time.time() - self.last_seen > SUBSCRIBER_TIMEOUT


class SubscriberRegistry(object):
    def __init__(self):
        self._subscribers = {}
        self._lock = threading.Lock()

    def add(self, uuid, host, port, command_id=0, protocol_name="http"):
        with self._lock:
            existing = self._subscribers.get(uuid)
            if existing:
                existing.host = host
                existing.port = int(port)
                existing.renew(command_id)
                return existing
            subscriber = Subscriber(uuid, host, port, command_id, protocol_name)
            self._subscribers[uuid] = subscriber
            util.DEBUG_LOG("Companion: subscriber added {0} at {1}", uuid, subscriber.url)
            return subscriber

    def remove(self, uuid):
        with self._lock:
            if self._subscribers.pop(uuid, None):
                util.DEBUG_LOG("Companion: subscriber removed {0}", uuid)

    def all(self):
        with self._lock:
            return list(self._subscribers.values())

    def prune(self):
        with self._lock:
            for uuid in [u for u, s in self._subscribers.items() if s.expired]:
                util.DEBUG_LOG("Companion: subscriber {0} timed out", uuid)
                del self._subscribers[uuid]

    def clear(self):
        with self._lock:
            self._subscribers.clear()


REGISTRY = SubscriberRegistry()


def _controllable(timeline):
    """
    What the apps are allowed to offer for this item.

    NowPlayingManager keeps this as a set of flags because the Roku client built
    the string lazily; updateControllableStr() is what turns it into the
    comma-separated form the wire wants.
    """
    try:
        timeline.updateControllableStr()
        return timeline.controllableStr or ""
    except Exception:
        return ""


def _timeline_kwargs(timeline, server_identifier=None):
    """One NowPlayingManager TimelineData rendered as Timeline attributes."""
    state = timeline.state or "stopped"
    if state == "stopped" or not timeline.itemData:
        return {"state": "stopped"}

    item = timeline.itemData
    data = {
        "state": state,
        "time": timeline.attrs.get("time", "0"),
        "duration": item.get("duration") or timeline.get("duration") or 0,
        "ratingKey": item.get("ratingKey"),
        "key": item.get("key"),
        "guid": item.get("guid"),
        "controllable": _controllable(timeline),
        "machineIdentifier": server_identifier,
    }

    play_queue = timeline.playQueue
    if play_queue is not None:
        data["playQueueID"] = getattr(play_queue, "id", None)
        data["playQueueItemID"] = getattr(play_queue, "selectedId", None)
        data["playQueueVersion"] = getattr(play_queue, "version", None)
        data["containerKey"] = "/playQueues/{0}".format(getattr(play_queue, "id", ""))

    duration = data.get("duration")
    if duration:
        data["seekRange"] = "0-{0}".format(duration)

    return data


def current_location():
    """
    Whether the user is browsing or watching. The apps show a remote for
    "navigation" and a now-playing screen for the fullScreen* values.
    """
    try:
        from kodi_six import xbmc
        if xbmc.Player().isPlayingVideo():
            return protocol.LOCATION_FULLSCREEN_VIDEO
        if xbmc.Player().isPlayingAudio():
            return protocol.LOCATION_FULLSCREEN_MUSIC
    except Exception:
        pass
    return protocol.LOCATION_NAVIGATION


def build_timelines():
    """The three timelines as protocol.timeline_xml wants them."""
    from plexnet import plexapp

    manager = plexapp.util.APP.nowplayingmanager
    server = getattr(plexapp.SERVERMANAGER, "selectedServer", None)
    server_identifier = getattr(server, "uuid", None) if server else None

    timelines = {}
    for timeline_type in protocol.TIMELINE_TYPES:
        timeline = manager.timelines.get(timeline_type)
        if timeline is None:
            timelines[timeline_type] = {"state": "stopped"}
            continue
        timelines[timeline_type] = _timeline_kwargs(timeline, server_identifier)
    return timelines


def timeline_document(command_id=0, machine_identifier=None):
    return protocol.timeline_xml(
        build_timelines(),
        command_id=command_id,
        location=current_location(),
        machine_identifier=machine_identifier,
    )


class TimelinePusher(threading.Thread):
    """
    Posts timelines to subscribed controllers.

    A subscriber that refuses three posts in a row is dropped: a phone that
    closed the app leaves its socket refusing connections, and retrying it
    forever would hold up the posts to everyone else on the list.
    """

    MAX_FAILURES = 3

    def __init__(self, machine_identifier):
        threading.Thread.__init__(self, name="PLEX:COMPANION:TIMELINE")
        self.daemon = True
        self.machine_identifier = machine_identifier
        self._stop_event = threading.Event()

    def run(self):
        while not self._stop_event.is_set():
            try:
                REGISTRY.prune()
                subscribers = REGISTRY.all()
                if subscribers:
                    self._push(subscribers)
            except Exception:
                util.ERROR("Companion: timeline push failed")
            self._stop_event.wait(PUSH_INTERVAL)

    def _push(self, subscribers):
        for subscriber in subscribers:
            try:
                body = timeline_document(
                    command_id=subscriber.command_id,
                    machine_identifier=self.machine_identifier)
                requests.post(
                    subscriber.url,
                    data=body.encode("utf-8"),
                    headers={"Content-Type": "text/xml;charset=utf-8"},
                    timeout=PUSH_TIMEOUT,
                )
                subscriber.failures = 0
            except Exception:
                subscriber.failures += 1
                if subscriber.failures >= self.MAX_FAILURES:
                    REGISTRY.remove(subscriber.uuid)

    def stop(self):
        self._stop_event.set()
