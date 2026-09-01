# coding=utf-8
"""
Where the credentials come from.

Two sources, on purpose. downloads.json in the add-on's profile directory is
the one that matters: an API key is 32 hex characters and entering it with a
remote is miserable, so it can be dropped in over SSH/SMB once and survives a
reinstall. The settings screen overrides it per field for anyone without a
shell, and is where discovery writes what it finds.
"""

from __future__ import absolute_import

import json
import os

from kodi_six import xbmcvfs

from .arr import ArrClient, RADARR, SONARR
from .qbittorrent import QBITTORRENT, QbClient
from ..util import ADDON, DEBUG_LOG, ERROR, getSetting, setSetting, translatePath

CONFIG_FILE = "downloads.json"

SETTING_KEYS = {
    SONARR: ("downloads_sonarr_url", "downloads_sonarr_key"),
    RADARR: ("downloads_radarr_url", "downloads_radarr_key"),
    QBITTORRENT: ("downloads_qbt_url", "downloads_qbt_user", "downloads_qbt_pass"),
}


def configPath():
    return os.path.join(translatePath(ADDON.getAddonInfo("profile")), CONFIG_FILE)


def readFile(path=None):
    path = path or configPath()
    if not xbmcvfs.exists(path):
        return {}
    f = xbmcvfs.File(path)
    try:
        raw = f.read()
    except Exception:
        ERROR("downloads: could not read {0}".format(CONFIG_FILE))
        return {}
    finally:
        f.close()

    try:
        data = json.loads(raw)
    except ValueError:
        ERROR("downloads: {0} is not valid JSON".format(CONFIG_FILE))
        return {}
    return data if isinstance(data, dict) else {}


def writeFile(data, path=None):
    path = path or configPath()
    f = xbmcvfs.File(path, "w")
    try:
        f.write(json.dumps(data, indent=2, sort_keys=True))
    except Exception:
        ERROR("downloads: could not write {0}".format(CONFIG_FILE))
        return False
    finally:
        f.close()
    return True


class DownloadsConfig(object):
    def __init__(self, data=None, settings=None):
        self.data = data if data is not None else readFile()
        # Injectable so the tests do not need Kodi's settings store.
        self._settings = settings if settings is not None else getSetting

    def _setting(self, key):
        try:
            return (self._settings(key, "") or "").strip()
        except Exception:
            return ""

    def service(self, name):
        """File first, then any setting that has actually been filled in."""
        entry = self.data.get(name) or {}
        if not isinstance(entry, dict):
            entry = {}
        merged = dict(entry)
        keys = SETTING_KEYS.get(name, ())
        for setting_key in keys:
            field = setting_key.rsplit("_", 1)[-1]
            value = self._setting(setting_key)
            if value:
                merged[field] = value
        return merged

    def enabled(self, name):
        entry = self.service(name)
        if entry.get("enabled") is False:
            return False
        return bool(entry.get("url"))

    def clients(self):
        """Every configured service, as something that can be polled."""
        built = []
        for name in (SONARR, RADARR):
            if not self.enabled(name):
                continue
            entry = self.service(name)
            built.append(ArrClient(entry["url"], entry.get("key"), flavour=name))
        if self.enabled(QBITTORRENT):
            entry = self.service(QBITTORRENT)
            built.append(QbClient(entry["url"], entry.get("user"), entry.get("pass")))
        return built

    def remember(self, found):
        """Persist what discovery turned up, without touching known secrets."""
        changed = False
        for name, url in (found or {}).items():
            entry = self.data.setdefault(name, {})
            if entry.get("url") != url:
                entry["url"] = url
                changed = True
        if changed:
            DEBUG_LOG("downloads: remembering discovered services {0}", sorted(found))
            writeFile(self.data)
        return changed


def storeSetting(key, value):
    setSetting(key, value)
