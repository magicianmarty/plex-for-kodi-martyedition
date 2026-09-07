# coding=utf-8
"""
Visibility of what the download stack is doing, from the couch.

The clients here talk to Sonarr/Radarr and qBittorrent and normalise both into
one list of Download objects. Nothing in this package imports Kodi, so it is
all reachable from the tests; the Kodi side lives in lib/windows/downloads.py.
"""
