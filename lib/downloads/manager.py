# coding=utf-8
"""
Polls the services and holds the last good answer.

Everything here runs on a background thread. The rule it exists to enforce: a
service that is down, slow or wrong must cost the UI nothing - the previous
answer stays on screen, marked stale, and the window keeps drawing.
"""

from __future__ import absolute_import

import threading
import time

from . import model
from .arr import ArrClient, SONARR
from .config import DownloadsConfig
from .net import ServiceError, describe
from .qbittorrent import QbClient


class Snapshot(object):
    def __init__(self, items=None, errors=None, updated=0.0):
        self.items = items or []
        # {service name: reason}, for the line under the list
        self.errors = errors or {}
        self.updated = updated

    @property
    def active(self):
        return [item for item in self.items if item.active]

    @property
    def stale(self):
        return bool(self.errors)

    def summary(self):
        """What the ambient indicator says: '3 downloading - 47%'."""
        active = self.active
        if not active:
            return 0, 0
        downloading = [i for i in active if i.state in (model.DOWNLOADING, model.STALLED)]
        if not downloading:
            return len(active), 0
        percent = sum(i.progress for i in downloading) / float(len(downloading))
        return len(active), int(percent * 100)


class DownloadsManager(object):
    def __init__(self, config=None):
        self.config = config or DownloadsConfig()
        self.snapshot = Snapshot()
        self.lock = threading.RLock()
        self._clients = None
        self._lastKeys = set()
        self._known = {}
        self._finished = {}

    def clients(self):
        if self._clients is None:
            self._clients = self.config.clients()
        return self._clients

    def configured(self):
        return bool(self.clients())

    def refresh(self):
        """
        Poll every service and replace the snapshot. Blocking - background
        thread only.
        """
        items = []
        errors = {}
        for client in self.clients():
            name = getattr(client, "flavour", None) or "qbittorrent"
            try:
                items.extend(self._poll(client))
            except ServiceError as e:
                errors[name] = describe(e)
            except Exception as e:  # a service answering nonsense is not fatal
                errors[name] = describe(e)

        items.sort(key=lambda item: item.sortKey)

        with self.lock:
            previous = self.snapshot
            # Keep what a broken service last told us rather than blanking the
            # list; a down Sonarr should not look like an empty queue.
            if errors:
                kept = [item for item in previous.items if item.source in errors]
                items = sorted(items + kept, key=lambda item: item.sortKey)
            self.snapshot = Snapshot(items, errors, time.time())
        return self.snapshot

    @staticmethod
    def _poll(client):
        if isinstance(client, ArrClient):
            return client.queue()
        if isinstance(client, QbClient):
            return client.torrents()
        return []

    def finished(self):
        """
        Keys that were active last time and are gone now - i.e. things that
        landed. Consumed, so each is reported once.
        """
        with self.lock:
            current = dict((item.key, item) for item in self.snapshot.items)
            previous = self._lastKeys
            self._lastKeys = set(current)
            self._known.update(current)
            if not previous:
                return []
            gone = [key for key in previous if key not in current]
            # Keep the last known record so the notification can name it.
            self._finished = dict((key, self._known.get(key)) for key in gone)
            self._known = current
            return gone

    def finishedItems(self, key):
        """The last thing we knew about a key that has since gone."""
        return self._finished.get(key)

    def item(self, key):
        with self.lock:
            for item in self.snapshot.items:
                if item.key == key:
                    return item
        return None
