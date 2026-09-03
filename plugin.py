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
    from urllib.parse import parse_qsl, quote, urlencode, urlsplit
except ImportError:
    from urlparse import parse_qsl, urlsplit
    from urllib import quote, urlencode

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


def search_uri(**params):
    return 'plugin://{0}/search?{1}'.format(ADDON_ID, urlencode(params))


# One prompt, both libraries. Plex answers inline; YouTube is one click away
# on the same query, because merging two plugins' results into a single Kodi
# listing is not something a plugin can do.
YOUTUBE_SEARCH = 'plugin://plugin.video.youtube/kodion/search/query/?q={0}'


def add_entry(handle, entry):
    """One Plex item as a playable directory entry."""
    item = xbmcgui.ListItem(label=entry['label'])
    item.setArt({
        'thumb': entry['thumb'],
        'icon': entry['thumb'],
        'poster': entry['thumb'],
        'landscape': entry['landscape'],
        'fanart': entry['art'],
    })
    item.setProperty('IsPlayable', 'true')
    # One property, not three. An item layout only binds ListItem per row for
    # image and label controls, so these have to be drawn as a single label -
    # three separate ones would need a container to lay them out, and a
    # container in an item layout reads the focused row for every tile.
    badges = ' \u00b7 '.join(
        entry[name] for name in ('quality', 'range', 'audio') if entry[name])
    if badges:
        item.setProperty('badge_line', badges)
    # The channel-equivalent for Plex: which show an episode belongs to, so a
    # row can say it without the title having to carry it.
    if entry['show']:
        item.setProperty('Artist', entry['show'])
    info = item.getVideoInfoTag()
    info.setTitle(entry['label'])
    info.setPlot(entry['plot'])
    if entry['year'].isdigit():
        info.setYear(int(entry['year']))
    if entry['duration']:
        info.setDuration(entry['duration'])
    # Resume, so "Continue Watching" continues rather than restarts.
    if entry['view_offset'] and entry['duration']:
        info.setResumePoint(entry['view_offset'], entry['duration'])
        # And as a plain property, because a skin needs something it can test
        # and draw. Whether Kodi derives PercentPlayed for a plugin item is not
        # something to depend on.
        item.setProperty('resume_percent', str(
            int(100 * entry['view_offset'] / entry['duration'])))
    xbmcplugin.addDirectoryItem(
        handle, uri(play=entry['rating_key']), item, False)


def do_search(handle, query):
    from lib import plexhubs

    if not query:
        query = xbmcgui.Dialog().input(
            xbmcaddon.Addon(ADDON_ID).getAddonInfo('name') + ': search')
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        if query:
            xbmc.executebuiltin('Container.Update({0},replace)'.format(
                search_uri(q=query)))
        return

    address, token = connection()
    xbmcplugin.setContent(handle, 'videos')
    xbmcplugin.setPluginCategory(handle, 'Search: ' + query)

    item = xbmcgui.ListItem(label='YouTube results for "{0}"'.format(query))
    item.setArt({'icon': 'DefaultAddonVideo.png'})
    xbmcplugin.addDirectoryItem(
        handle, YOUTUBE_SEARCH.format(quote(query.encode('utf-8'))), item, True)

    entries = plexhubs.add_ranges(
        address, token, plexhubs.search(address, token, query))
    for entry in entries:
        add_entry(handle, entry)
    xbmcplugin.endOfDirectory(handle)
    set_view()


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


# Kodi picks a view from the content type, and a skin can lay movies out as
# posters and episodes as stills only if it is told which it has. 'videos' -
# the safe generic - tells it nothing.
def content_for(key):
    if 'type=2' in key or 'type%3D2' in key:
        return 'tvshows'
    if 'type=1' in key or 'type%3D1' in key:
        return 'movies'
    if 'onDeck' in key or 'continueWatching' in key:
        return 'episodes'
    return 'videos'


# The skin cannot do this for us. A window's onload runs before the directory
# has any content, so the view it wants is not selectable yet, and Kodi's
# remembered viewmode for the path wins over the skin's <views> order - which
# is how a first visit landed in the stock text list.
WALL_VIEW = 500


def set_view():
    if xbmc.getSkinDir() != 'skin.martyedition':
        return
    xbmc.executebuiltin('Container.SetViewMode({0})'.format(WALL_VIEW))


def list_hub(handle, key, title):
    from lib import plexhubs
    address, token = connection()
    xbmcplugin.setContent(handle, content_for(key))
    if title:
        xbmcplugin.setPluginCategory(handle, title)

    entries = plexhubs.add_ranges(address, token,
                                  plexhubs.hub_items(address, token, key))
    for entry in entries:
        add_entry(handle, entry)
    xbmcplugin.endOfDirectory(handle)
    set_view()


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
    try:
        handle = int(argv[1])
    except (IndexError, ValueError):
        handle = -1

    if not path:
        # This is a hack since it's both a plugin and a script. My Addons and
        # Shortcuts otherwise can't launch the add-on.
        #
        # Only when there is no handle, though. Browsing walks up to the plugin
        # root to build its breadcrumb, and launching the full app in answer to
        # that took over the screen and dropped the window it came from.
        if handle < 0:
            launch()
            return
        list_hubs(handle)
        return
    params = dict(parse_qsl(data))
    try:
        if 'play' in params:
            play(handle, params['play'])
        elif path.endswith('/search'):
            do_search(handle, params.get('q', ''))
        elif 'hub' in params:
            list_hub(handle, params['hub'], params.get('title', ''))
        else:
            list_hubs(handle)
    except Exception as error:
        xbmc.log('script.plexmod: hub listing failed: {0!r}'.format(error),
                 xbmc.LOGERROR)
        xbmcplugin.endOfDirectory(handle, succeeded=False)


main()
