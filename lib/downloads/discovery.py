# coding=utf-8
"""
Finding the stack so nobody has to type a URL with a remote.

Every service here answers *something* without credentials, which is what makes
this possible: Sonarr/Radarr/Prowlarr answer /ping, and qBittorrent's 403 is
itself proof of a qBittorrent.
"""

from __future__ import absolute_import

from .arr import ArrClient, PROWLARR, RADARR, SONARR
from .qbittorrent import QBITTORRENT, QbClient

# Default ports, and the only ones worth trying blind.
CANDIDATES = (
    (SONARR, 8989),
    (RADARR, 7878),
    (PROWLARR, 9696),
    (QBITTORRENT, 8080),
)

PROBE_TIMEOUT = 2.0


def probe(host, timeout=PROBE_TIMEOUT, candidates=CANDIDATES):
    """{service name: url} for whatever answers on `host`."""
    found = {}
    for name, port in candidates:
        url = "http://{0}:{1}".format(host, port)
        try:
            if name == QBITTORRENT:
                alive = QbClient(url, timeout=timeout).identify()
            else:
                alive = ArrClient(url, flavour=name, timeout=timeout).ping()
        except Exception:
            alive = False
        if alive:
            found[name] = url
    return found


def hosts(plex_server=None, extra=()):
    """
    Where to look, best guess first.

    The Plex server is the strongest candidate by far - a media stack almost
    always runs the *arrs on the same box that serves the library - and it
    costs one round trip to check.
    """
    ordered = []
    for host in list(extra) + [_serverHost(plex_server), "localhost"]:
        if host and host not in ordered:
            ordered.append(host)
    return ordered


def _serverHost(server):
    if not server:
        return None
    for attr in ("address", "host"):
        value = getattr(server, attr, None)
        if value:
            return str(value)
    connection = getattr(server, "activeConnection", None)
    address = getattr(connection, "address", None)
    if not address:
        return None
    address = str(address).split("//")[-1]
    return address.split(":")[0].split("/")[0] or None


def discover(plex_server=None, extra=(), timeout=PROBE_TIMEOUT):
    """First host that answers wins; services found later do not overwrite it."""
    found = {}
    for host in hosts(plex_server, extra):
        for name, url in probe(host, timeout=timeout).items():
            found.setdefault(name, url)
    return found
