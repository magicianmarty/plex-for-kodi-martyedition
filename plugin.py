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

import json
import os
import sys

try:
    from urllib.parse import parse_qsl, quote, urlencode, urlsplit
except ImportError:
    from urlparse import parse_qsl, urlsplit
    from urllib import quote, urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

ADDON_ID = 'script.plexmod'
SERVER_SETTING = 'None.PlexServerManager'


# plexhubs needs nothing from the lib package - only json and urllib - so it
# is loaded straight from its file. Importing it as lib.plexhubs would run
# lib/__init__.py first and drag requests and plexnet in behind it.
_PLEXHUBS = None


def plexhubs():
    global _PLEXHUBS
    if _PLEXHUBS is None:
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'lib', 'plexhubs.py')
        spec = importlib.util.spec_from_file_location('plexhubs', path)
        _PLEXHUBS = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_PLEXHUBS)
    return _PLEXHUBS


def launch():
    """What this entry point has always done."""
    # Imported here, not at the top. Importing anything from lib runs the
    # package __init__, which pulls in requests and the whole bundled plexnet
    # tree - seconds of import on this hardware, paid on every listing and
    # every play, for something only launching needs.
    from lib.kodi_util import ensureHome
    ensureHome()
    xbmc.executebuiltin('RunScript(script.plexmod,fromplugin)')


def connection():
    plexhubs_ = plexhubs()
    value = xbmcaddon.Addon(ADDON_ID).getSetting(SERVER_SETTING)
    return plexhubs_.connection(value)


def uri(**params):
    return 'plugin://{0}/hubs?{1}'.format(ADDON_ID, urlencode(params))


def search_uri(**params):
    return 'plugin://{0}/search?{1}'.format(ADDON_ID, urlencode(params))


def open_uri(rating_key, kind):
    return 'plugin://{0}/open?{1}'.format(
        ADDON_ID, urlencode({'key': rating_key, 'type': kind}))


# One prompt, both libraries. Plex answers inline; YouTube is one click away
# on the same query, because merging two plugins' results into a single Kodi
# listing is not something a plugin can do.
YOUTUBE_SEARCH = 'plugin://plugin.video.youtube/kodion/search/query/?q={0}'


# Sections are numbered per server, so the skin asks for a type and the
# add-on resolves it. Hard-coding "Movies is section 3" would be true of
# exactly this one server.
def section_for(address, token, kind):
    plexhubs_ = plexhubs()
    for section in plexhubs_.sections(address, token):
        if section['type'] == kind:
            return section
    return None


CONTENT_FOR_TYPE = {'movie': 'movies', 'show': 'tvshows'}


# Two rows sit above the library in the container: the parent entry Kodi puts
# at the top of every plugin listing, and this add-on's own Search row. The
# alphabet's jump positions have to count both.
PARENT_ITEMS = 2


def list_library(handle, kind):
    plexhubs_ = plexhubs()

    address, token = connection()
    section = section_for(address, token, kind)
    if section is None:
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    xbmcplugin.setContent(handle, CONTENT_FOR_TYPE.get(kind, 'videos'))
    remember_origin()
    xbmcplugin.setPluginCategory(handle, section['title'])

    # The whole library in one listing. Paging it meant the alphabet could only
    # ever reach the page you were on, and a letter had to re-fetch to show
    # anything - so jumping to Z left you in a listing containing only Z.
    items, _total = plexhubs_.section_items(address, token, section['key'])
    xbmcplugin.setProperty(handle, 'total_label', str(len(items)))
    xbmcplugin.setProperty(handle, 'alphabet', '1')

    item = xbmcgui.ListItem(label='Search {0}'.format(section['title']))
    item.setArt({'icon': 'DefaultAddonsSearch.png'})
    xbmcplugin.addDirectoryItem(handle, search_uri(), item, True)

    cache = load_badges()
    missing = apply_badges(items, cache)

    # Where each letter starts, so the skin can jump to it rather than filter
    # to it. Offset by the parent entry Kodi puts at the top of every plugin
    # listing, which occupies position zero.
    seen = {}
    for index, entry in enumerate(items):
        first = (entry['sort_title'] or '?')[0].upper()
        if not first.isalpha():
            first = '#'
        seen.setdefault(first, index + PARENT_ITEMS)
        add_entry(handle, entry)
    for name, index in seen.items():
        xbmcplugin.setProperty(handle, 'letter_index_' + name, str(index))

    xbmcplugin.endOfDirectory(handle)
    set_view(current_url())
    # After the directory is served, so the page is on screen while this runs.
    if missing:
        fill_badges(address, token, missing, cache)


# Badges the listing does not carry are looked up after the directory has
# already been handed to Kodi, and kept. The page is on screen while that
# happens, and the next visit has them without asking again.
BADGE_FIELDS = ('quality', 'range', 'audio')


def badge_cache_path():
    profile = xbmcvfs.translatePath(
        xbmcaddon.Addon(ADDON_ID).getAddonInfo('profile'))
    if not xbmcvfs.exists(profile):
        xbmcvfs.mkdirs(profile)
    return os.path.join(profile, 'badges.json')


def load_badges():
    try:
        with open(badge_cache_path(), 'r') as handle:
            return json.load(handle)
    except Exception:
        return {}


def save_badges(cache):
    # Bounded, because a big library browsed end to end would otherwise grow
    # this without limit.
    if len(cache) > 4000:
        for key in list(cache)[:len(cache) - 4000]:
            del cache[key]
    try:
        with open(badge_cache_path(), 'w') as handle:
            json.dump(cache, handle)
    except Exception as error:
        xbmc.log('script.plexmod: badge cache write failed: {0!r}'.format(error),
                 xbmc.LOGWARNING)


def apply_badges(entries, cache):
    """Fill in what is already known, and say which items still need asking."""
    missing = []
    for entry in entries:
        known = cache.get(entry['rating_key'])
        if known is None:
            missing.append(entry)
            continue
        for field in BADGE_FIELDS:
            if not entry[field]:
                entry[field] = known.get(field, '')
    return missing


def fill_badges(address, token, entries, cache):
    plexhubs_ = plexhubs()
    plexhubs_.add_ranges(address, token, entries)
    plexhubs_.add_child_quality(address, token, entries)
    for entry in entries:
        cache[entry['rating_key']] = {
            field: entry[field] for field in BADGE_FIELDS
        }
    save_badges(cache)


def add_entry(handle, entry):
    """One Plex item as a playable directory entry."""
    item = xbmcgui.ListItem(label=entry['label'])
    item.setArt({
        'thumb': entry['thumb'],
        'icon': entry['thumb'],
        'poster': entry['poster'],
        'landscape': entry['landscape'],
        'fanart': entry['art'],
    })
    if not use_plex_player():
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
    # Composed here rather than in the skin: a skin can only concatenate, so
    # separators end up stranded when a field is missing.
    badges = entry['quality'] and ' '.join(
        f for f in (entry['quality'], entry['range'], entry['audio']) if f)
    facts = [f for f in (entry['year'], badges, entry['content_rating'],
                         entry['score'] and entry['score'] + '/10',
                         ', '.join(entry['genres'])) if f]
    if facts:
        item.setProperty('facts_line', '   \u00b7   '.join(facts))
    people = []
    if entry['directors']:
        people.append('Directed by ' + entry['directors'][0])
    if entry['cast']:
        people.append(', '.join(entry['cast']))
    if people:
        item.setProperty('people_line', '   \u00b7   '.join(people))
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
    if use_plex_player():
        # A folder, not a playable file: selecting it opens the item in the
        # Plex add-on rather than asking Kodi to play anything.
        xbmcplugin.addDirectoryItem(
            handle, open_uri(entry['rating_key'], entry['type']), item, True)
    else:
        xbmcplugin.addDirectoryItem(
            handle, uri(play=entry['rating_key']), item, False)


def do_search(handle, query):
    plexhubs_ = plexhubs()

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
    remember_origin()

    item = xbmcgui.ListItem(label='YouTube results for "{0}"'.format(query))
    item.setArt({'icon': 'DefaultAddonVideo.png'})
    xbmcplugin.addDirectoryItem(
        handle, YOUTUBE_SEARCH.format(quote(query.encode('utf-8'))), item, True)

    entries = plexhubs_.add_ranges(
        address, token, plexhubs_.search(address, token, query))
    for entry in entries:
        add_entry(handle, entry)
    xbmcplugin.endOfDirectory(handle)
    set_view(current_url())


def list_hubs(handle):
    plexhubs_ = plexhubs()
    address, token = connection()
    xbmcplugin.setContent(handle, 'videos')
    for hub in plexhubs_.hubs(address, token):
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


def current_url():
    """The path Kodi asked this process for, as it will report it."""
    argv = sys.argv
    return argv[0] + (argv[2] if len(argv) > 2 else '')


def set_view(expected):
    if xbmc.getSkinDir() != 'skin.martyedition':
        return
    # A letter jump is a Container.Update, which re-enters this plugin and
    # replaces the listing in place. Asking for the view before that listing
    # is the active one does nothing, and Kodi then settles on whatever it
    # remembers - the stock list. Waiting for items to exist is not enough:
    # the previous listing's items are still there, so the wait ends
    # immediately and the view is set against the page being replaced.
    monitor = xbmc.Monitor()
    for _ in range(40):
        if xbmc.getInfoLabel('Container.FolderPath') == expected:
            break
        if monitor.waitForAbort(0.1):
            return
    else:
        return
    monitor.waitForAbort(0.2)
    xbmc.executebuiltin('Container.SetViewMode({0})'.format(WALL_VIEW))


def list_hub(handle, key, title):
    plexhubs_ = plexhubs()
    address, token = connection()
    xbmcplugin.setContent(handle, content_for(key))
    remember_origin()
    if title:
        xbmcplugin.setPluginCategory(handle, title)

    entries = plexhubs_.hub_items(address, token, key)
    cache = load_badges()
    missing = apply_badges(entries, cache)
    if missing:
        fill_badges(address, token, missing, cache)
    for entry in entries:
        add_entry(handle, entry)
    xbmcplugin.endOfDirectory(handle)
    set_view(current_url())


# Whether selecting something opens its page or just plays it. 'always' is the
# Plex app's behaviour; 'tv' gives the page only where there is a choice to
# make - which episode - and lets a film start on one press; 'never' keeps the
# old one-press-plays behaviour throughout.
ITEM_PAGE_SETTING = 'plugin.item_page'
PAGED_TYPES = ('show', 'season', 'episode')


def wants_page(kind):
    mode = xbmcaddon.Addon(ADDON_ID).getSetting(ITEM_PAGE_SETTING) or 'always'
    if mode == 'never':
        return False
    if mode == 'tv':
        return kind in PAGED_TYPES
    return True


def open_item(handle, rating_key, kind):
    """
    Hand an item to the Plex add-on and get out of the way.

    Ending the directory as failed is deliberate. Kodi shows a dialog when
    *playback* is refused - which is what the previous approach did, and what
    put "Playback failed" on screen - but a directory that refuses only writes
    a line to the log, leaves the viewer where they were, and lets the add-on
    open over the top.
    """
    remember_origin()
    # 'open' shows the item's page; 'play' starts it straight away.
    command = 'open' if wants_page(kind) else 'play'
    xbmc.executebuiltin('RunScript({0},{1},{2})'.format(
        ADDON_ID, command, rating_key))
    xbmcplugin.endOfDirectory(handle, succeeded=False)


# Plex content plays with the Plex player. Kodi's own player gets a bare
# stream and none of what this add-on knows about the item: no resume dialog,
# no BIF thumbnails while seeking, no subtitle picker, and nothing reported
# back to the server about what was watched.
PLEX_PLAYER_SETTING = 'plugin.use_plex_player'


def remember_origin():
    """
    Note where this listing is being shown, so playback can come back to it.

    Recorded here rather than when something is played: by then Kodi has
    already switched to its fullscreen video window, and the origin came out
    as the player rather than the screen the viewer was on.
    """
    window = xbmcgui.Window(10000)
    window.setProperty('plexmod.return_window',
                       str(xbmcgui.getCurrentWindowId()))
    window.setProperty('plexmod.return_path',
                       xbmc.getInfoLabel('Container.FolderPath') or '')


def use_plex_player():
    return xbmcaddon.Addon(ADDON_ID).getSetting(PLEX_PLAYER_SETTING) != 'false'


def play(handle, rating_key):
    if use_plex_player():
        # Hand off, then tell Kodi this was not resolved, because the add-on
        # is doing the playing. Kodi logs that as a failure; the viewer sees
        # nothing because the Plex player takes the screen straight after.
        xbmc.executebuiltin('RunScript({0},play,{1})'.format(
            ADDON_ID, rating_key))
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return

    play_with_kodi(handle, rating_key)


def play_with_kodi(handle, rating_key):
    plexhubs_ = plexhubs()
    address, token = connection()
    url = plexhubs_.stream_url(address, token, rating_key)
    if not url:
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return

    # The resolved item is what the player OSD reads. Handing over a bare path
    # left it with nothing to show, so the OSD titled the film 'hubs' - the
    # name of the plugin route - with no artwork, plot or runtime.
    entry = plexhubs_.metadata(address, token, rating_key)
    item = xbmcgui.ListItem(label=entry['label'] if entry else '', path=url)
    if entry:
        item.setArt({
            'thumb': entry['thumb'],
            'poster': entry['poster'],
            'landscape': entry['landscape'],
            'fanart': entry['art'],
        })
        info = item.getVideoInfoTag()
        info.setTitle(entry['label'])
        info.setPlot(entry['plot'])
        if entry['year'].isdigit():
            info.setYear(int(entry['year']))
        if entry['duration']:
            info.setDuration(entry['duration'])
        if entry['genres']:
            info.setGenres(entry['genres'])
        if entry['show']:
            info.setTvShowTitle(entry['show'])
    xbmcplugin.setResolvedUrl(handle, True, item)


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
        elif path.endswith('/open'):
            open_item(handle, params.get('key', ''), params.get('type', ''))
        elif path.endswith('/library'):
            list_library(handle, params.get('type', 'movie'))
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
