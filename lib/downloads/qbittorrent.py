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
        # Finished torrents still sitting there seeding. Not worth a row each,
        # but worth saying, or a client with nothing downloading looks broken.
        self.seeding = 0

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

    def torrents(self, filter="all"):
        try:
            data = self._torrents(filter)
        except ServiceError as e:
            # The session cookie expires quietly; one re-login, then give up.
            if not e.unauthorized or not (self.username and self.password):
                raise
            self.login()
            data = self._torrents(filter)

        # Everything, then decide here: what the stack still owes you, plus
        # anything that has gone wrong. A library's worth of finished torrents
        # seeding away is not a to-do list - but a torrent whose files have
        # vanished is exactly the thing you want to be told about.
        rows, seeding = [], 0
        for record in data or []:
            state = str(record.get("state") or "").lower()
            done = (record.get("progress") or 0) >= 1
            if done and state not in ("error", "missingfiles"):
                seeding += 1
                continue
            rows.append(self._download(record))
        self.seeding = seeding
        return rows

    def _torrents(self, filter):
        if not self._authenticated:
            self.login()
        return self.http.request("/api/v2/torrents/info", params={"filter": filter})

    # ------------------------------------------------------------- controls

    def pause(self, download):
        return self._control(download, "pause", "stop")

    def resume(self, download):
        return self._control(download, "resume", "start")

    def remove(self, download, delete_files=False):
        """
        Drop a torrent. Files are kept unless asked otherwise, same rule as the
        *arr queue: deleting someone's download should take a deliberate press.
        """
        return self._control(download, "delete", None,
                             extra={"deleteFiles": "true" if delete_files else "false"})

    def _control(self, download, action, renamed, extra=None):
        """
        qBittorrent 5 renamed pause and resume to stop and start. Try what this
        one is likely to want, and fall back rather than making the user care
        which version they run.
        """
        torrent = getattr(download, "service_id", None)
        if not torrent:
            raise ServiceError("nothing to act on")
        data = {"hashes": torrent}
        data.update(extra or {})

        try:
            self._post(action, data)
        except ServiceError as e:
            if not renamed or e.status != 404:
                raise
            self._post(renamed, data)
        return True

    def _post(self, action, data):
        if not self._authenticated:
            self.login()
        self.http.request("/api/v2/torrents/{0}".format(action), method="post",
                          expect_json=False, data=data)

    @staticmethod
    def _download(record):
        state = STATES.get(str(record.get("state") or "").lower(), model.DOWNLOADING)
        return model.Download(
            service_id=record.get("hash"),
            key="{0}:{1}".format(QBITTORRENT, record.get("hash") or record.get("name")),
            title=record.get("name") or "Unknown",
            subtitle=record.get("category") or "",
            source=QBITTORRENT,
            state=state,
            progress=record.get("progress") or 0.0,
            size=record.get("size") or 0,
            eta=record.get("eta"),
        )
