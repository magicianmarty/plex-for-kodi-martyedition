# coding=utf-8
"""qBittorrent's WebUI API, for the grabs no *arr knows about."""

from __future__ import absolute_import

from . import model
from .net import ServiceError, Session

QBITTORRENT = "qbittorrent"

# pausedDL became stoppedDL in qBittorrent 5; both spellings are live.
STATES = {
    "downloading": model.DOWNLOADING,
    "forceddl": model.DOWNLOADING,
    "metadl": model.DOWNLOADING,
    "checkingdl": model.DOWNLOADING,
    "allocating": model.DOWNLOADING,
    "stalleddl": model.STALLED,
    "queueddl": model.QUEUED,
    "pauseddl": model.PAUSED,
    "stoppeddl": model.PAUSED,
    "error": model.FAILED,
    "missingfiles": model.FAILED,
}


class QbClient(object):
    def __init__(self, url, username=None, password=None, timeout=6.0):
        self.username = username
        self.password = password
        self.http = Session(url, timeout=timeout)
        self._authenticated = not (username and password)

    @property
    def url(self):
        return self.http.base_url

    def identify(self):
        """
        403 still identifies qBittorrent - it means "there is a WebUI here and
        it wants a login", which is all discovery needs to know.
        """
        try:
            self.http.request("/api/v2/app/version", expect_json=False)
            return True
        except ServiceError as e:
            return e.unauthorized

    def login(self):
        if not (self.username and self.password):
            return False
        body = self.http.request("/api/v2/auth/login", method="post", expect_json=False,
                                 data={"username": self.username, "password": self.password},
                                 headers={"Referer": self.http.base_url})
        if "Ok" not in (body or ""):
            raise ServiceError("login rejected", status=403)
        self._authenticated = True
        return True

    def torrents(self, filter="downloading"):
        try:
            data = self._torrents(filter)
        except ServiceError as e:
            # The session cookie expires quietly; one re-login, then give up.
            if not e.unauthorized or not (self.username and self.password):
                raise
            self.login()
            data = self._torrents(filter)
        return [self._download(record) for record in data or []]

    def _torrents(self, filter):
        if not self._authenticated:
            self.login()
        return self.http.request("/api/v2/torrents/info", params={"filter": filter})

    @staticmethod
    def _download(record):
        state = STATES.get(str(record.get("state") or "").lower(), model.DOWNLOADING)
        return model.Download(
            key="{0}:{1}".format(QBITTORRENT, record.get("hash") or record.get("name")),
            title=record.get("name") or "Unknown",
            subtitle=record.get("category") or "",
            source=QBITTORRENT,
            state=state,
            progress=record.get("progress") or 0.0,
            size=record.get("size") or 0,
            eta=record.get("eta"),
        )
