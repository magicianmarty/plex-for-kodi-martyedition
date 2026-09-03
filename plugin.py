# coding=utf-8
"""
Plugin entry point.

Two jobs. Launching the add-on, which is what it has always done and what
shortcut tools rely on - that stays on the root path. And serving the Plex
hubs as browsable directories under /hubs, so a skin can put "Continue
Watching" on a home screen beside anything else.

Browsing deliberately avoids starting plexnet. Kodi creates and destroys a
plugin process for every listing, and booting the whole client each time to
ask the server one question would make a home screen row too slow to use.
"""

from __future__ import absolute_import

import sys

try:
    from urllib.parse import parse_qsl, urlencode, urlsplit
except ImportError:
    from urlparse import parse_qsl, urlsplit
    from urllib import urlencode

from lib.kodi_util import ensureHome, xbmc

import xbmcaddon
import xbmcgui
import xbmcplugin

ADDON_ID = 'script.plexmod'
SERVER_SETTING = 'None.PlexServerManager'


def launch():
    """What this entry point has always done."""
    ensureHome()
    xbmc.executebuiltin('RunScript(script.plexmod,fromplugin)')


def connection():
    from lib import plexhubs
    value = xbmcaddon.Addon(ADDON_ID).getSetting(SERVER_SETTING)
    return plexhubs.connection(value)


def uri(**params):
    return 'plugin://{0}/hubs?{1}'.format(ADDON_ID, urlencode(params))


def list_hubs(handle):
    from lib import plexhubs
    address, token = connection()
    xbmcplugin.setContent(handle, 'videos')
    for hub in plexhubs.hubs(address, token):
        item = xbmcgui.ListItem(label=hub['title'])
        item.setArt({'icon': 'DefaultFolder.png'})
        xbmcplugin.addDirectoryItem(
            handle, uri(hub=hub['key'], title=hub['title']), item, True)
    xbmcplugin.endOfDirectory(handle)


def list_hub(handle, key, title):
    from lib import plexhubs
    address, token = connection()
    xbmcplugin.setContent(handle, 'videos')
    if title:
        xbmcplugin.setPluginCategory(handle, title)

    for entry in plexhubs.hub_items(address, token, key):
        item = xbmcgui.ListItem(label=entry['label'])
        item.setArt({
            'thumb': entry['thumb'],
            'icon': entry['thumb'],
            'poster': entry['thumb'],
            'fanart': entry['art'],
        })
        item.setProperty('IsPlayable', 'true')
        # The channel-equivalent for Plex: which show an episode belongs to,
        # so a row can say it without the title having to carry it.
        if entry['show']:
            item.setProperty('Artist', entry['show'])
        info = item.getVideoInfoTag()
        info.setTitle(entry['label'])
        info.setPlot(entry['plot'])
        if entry['duration']:
            info.setDuration(entry['duration'])
        # Resume, so "Continue Watching" continues rather than restarts.
        if entry['view_offset'] and entry['duration']:
            info.setResumePoint(entry['view_offset'], entry['duration'])
        xbmcplugin.addDirectoryItem(
            handle, uri(play=entry['rating_key']), item, False)
    xbmcplugin.endOfDirectory(handle)


def play(handle, rating_key):
    from lib import plexhubs
    address, token = connection()
    url = plexhubs.stream_url(address, token, rating_key)
    item = xbmcgui.ListItem(path=url)
    xbmcplugin.setResolvedUrl(handle, bool(url), item)


def main():
    argv = sys.argv
    try:
        data = argv[2].lstrip('?')
        if data == 'stub':
            return
    except IndexError:
        data = ''

    path = urlsplit(argv[0]).path.rstrip('/')
    if not path:
        # This is a hack since it's both a plugin and a script. My Addons and
        # Shortcuts otherwise can't launch the add-on.
        launch()
        return

    handle = int(argv[1])
    params = dict(parse_qsl(data))
    try:
        if 'play' in params:
            play(handle, params['play'])
        elif 'hub' in params:
            list_hub(handle, params['hub'], params.get('title', ''))
        else:
            list_hubs(handle)
    except Exception as error:
        xbmc.log('script.plexmod: hub listing failed: {0!r}'.format(error),
                 xbmc.LOGERROR)
        xbmcplugin.endOfDirectory(handle, succeeded=False)


main()
