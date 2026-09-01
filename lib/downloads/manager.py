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
from .arr import ArrClient, RADARR, SONARR
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
        # Newest import we have already seen, per service. Set on the first
        # poll from what history already holds, so starting the add-on never
        # announces a backlog of things that landed days ago.
        self._historySeen = {}
        self._finished = []

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
        finished = []
        for client in self.clients():
            name = getattr(client, "flavour", None) or "qbittorrent"
            try:
                items.extend(self._poll(client))
                finished.extend(self._imported(client, name))
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
            self._finished = finished
        return self.snapshot

    def _imported(self, client, name):
        """
        What this service imported since we last looked.

        The first poll only records where history stands; it announces nothing,
        because everything in it finished before the add-on was even started.
        """
        if not isinstance(client, ArrClient):
            return []

        # "Never looked" and "looked, saw nothing" are different: only the
        # first is a reason to stay quiet, and an empty history on the first
        # poll must not leave us permanently unbaselined.
        first = name not in self._historySeen
        since = self._historySeen.get(name)
        records = client.history(since=since)
        dates = [r.at for r in records if r.at]
        self._historySeen[name] = (max(dates) if dates else None) or since
        return [] if first else records

    @staticmethod
    def _poll(client):
        if isinstance(client, ArrClient):
            return client.queue()
        if isinstance(client, QbClient):
            return client.torrents()
        return []

    def finished(self):
        """
        What genuinely landed since the last poll, straight from the services'
        own import history. Consumed, so each is reported once.

        Deliberately not "it left the queue": a queue entry also disappears
        when it is removed, blocked or fails, and calling those "finished
        downloading" is how notifications stop being believed.
        """
        with self.lock:
            finished, self._finished = self._finished, []
            return finished

    def clientFor(self, item):
        """The service a row came from, so it can be acted on."""
        for client in self.clients():
            if getattr(client, "flavour", None) == getattr(item, "source", None):
                return client
        return None

    def services(self):
        """{flavour: client} for the *arrs, which are the ones you can add to."""
        found = {}
        for client in self.clients():
            flavour = getattr(client, "flavour", None)
            if flavour in (SONARR, RADARR):
                found[flavour] = client
        return found

    def forget(self, item):
        """Drop a row from the snapshot now, rather than waiting for a poll."""
        with self.lock:
            items = [i for i in self.snapshot.items if i.key != item.key]
            self.snapshot = Snapshot(items, self.snapshot.errors, self.snapshot.updated)
        return self.snapshot

    def item(self, key):
        with self.lock:
            for item in self.snapshot.items:
                if item.key == key:
                    return item
        return None
