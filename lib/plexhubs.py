# coding=utf-8
"""
Plex hubs as browsable directories.

The add-on is a script: it draws its own windows and nothing else can see
inside it. That is fine until you want a skin to put "Continue Watching" on a
home screen next to something else, because a skin can only show what it can
browse - and a script has nothing to browse.

So this exposes the hubs the server already publishes as ordinary plugin
paths. It deliberately does not start plexnet: a plugin process is created
and destroyed for every listing, and booting the full client each time to ask
one question would make the rows too slow to sit on a home screen. The
server address and token are read from the add-on's own stored connection
instead, which is the same thing plexnet would hand back.
"""

from __future__ import absolute_import

import json

try:
    from urllib.parse import quote, urlencode
    from urllib.request import Request, urlopen
except ImportError:
    from urllib import quote, urlencode
    from urllib2 import Request, urlopen

TIMEOUT = 15

# Hubs worth putting on a home screen, in the order a person would want them.
# The server returns others - photos, empty rows - that are noise here.
PREFERRED = (
    'home.continue',
    'home.ondeck',
    'home.television.recent',
    'home.movies.recent',
    'home.music.recent',
    'home.playlists',
)


class NoServer(Exception):
    pass


def connection(settings_value):
    """
    The server address and token, from the add-on's stored server manager.

    Returns (address, token). Raises NoServer when the add-on has never
    connected, which is the honest answer - there is nothing to browse until
    the user has signed in through the add-on itself.
    """
    if not settings_value:
        raise NoServer('the add-on has no stored server')
    try:
        data = json.loads(settings_value)
    except ValueError:
        raise NoServer('stored server details could not be read')

    for server in data.get('servers') or ():
        connections = server.get('connections') or ()
        # A local connection first: it is the one that works when the
        # internet does not, and it is faster.
        for wanted_local in (True, False):
            for entry in connections:
                is_local = str(entry.get('isLocal')) == 'True'
                if is_local != wanted_local:
                    continue
                address = entry.get('address')
                token = entry.get('token')
                if address and token:
                    return address.rstrip('/'), token
    raise NoServer('no usable connection in the stored server details')


def get_json(address, token, path, params=None):
    query = dict(params or {})
    query['X-Plex-Token'] = token
    url = '{0}{1}{2}{3}'.format(address, path,
                                '&' if '?' in path else '?',
                                urlencode(query))
    request = Request(url, headers={'Accept': 'application/json'})
    response = urlopen(request, timeout=TIMEOUT)
    try:
        return json.loads(response.read().decode('utf-8'))
    finally:
        response.close()


def hubs(address, token):
    """The home hubs, best-first, with the empty ones dropped."""
    data = get_json(address, token, '/hubs')
    found = []
    for hub in (data.get('MediaContainer', {}).get('Hub') or ()):
        if not hub.get('size'):
            continue
        found.append({
            'identifier': hub.get('hubIdentifier') or '',
            'title': hub.get('title') or '',
            'key': hub.get('key') or '',
            'size': hub.get('size') or 0,
            'type': hub.get('type') or '',
        })

    def rank(hub):
        identifier = hub['identifier']
        for index, name in enumerate(PREFERRED):
            if identifier.startswith(name):
                return index
        return len(PREFERRED)

    found.sort(key=rank)
    return found


# A home row shows about ten tiles. "Recently Added Movies" on this server is
# 1368 of them, and fetching the lot to draw ten would make the row too slow
# to sit on a home screen - which is the whole reason this exists.
ROW_LIMIT = 30


def hub_items(address, token, key, limit=ROW_LIMIT):
    """What is in one hub, capped to what a row can show."""
    data = get_json(address, token, key,
                    {'X-Plex-Container-Start': 0,
                     'X-Plex-Container-Size': limit})
    container = data.get('MediaContainer', {})
    items = []
    for entry in (container.get('Metadata') or ()):
        items.append(item_details(address, token, entry))
    return items


def item_details(address, token, entry):
    """
    One row item, flattened into what a listing needs.

    Episodes carry their show's name and their own title; a home screen wants
    both, and wants the show first, because that is what someone is looking
    for when they glance at a row.
    """
    kind = entry.get('type') or ''
    title = entry.get('title') or ''
    if kind == 'episode':
        show = entry.get('grandparentTitle') or ''
        label = '{0} - {1}'.format(show, title) if show else title
        subtitle = 'S{0}E{1}'.format(entry.get('parentIndex') or 0,
                                     entry.get('index') or 0)
    else:
        label = title
        subtitle = str(entry.get('year') or '')

    art = entry.get('art') or entry.get('grandparentArt') or ''
    thumb = (entry.get('thumb') or entry.get('grandparentThumb')
             or entry.get('parentThumb') or '')

    # An episode's own thumb is a 16:9 still, which is the wrong shape for a
    # poster row. The show above it has the poster, so portrait art comes from
    # there and only falls back to the still when there is no show.
    if kind in ('episode', 'season'):
        poster = (entry.get('grandparentThumb') or entry.get('parentThumb')
                  or thumb)
    else:
        poster = thumb

    def tags(name, limit):
        return [t.get('tag') for t in (entry.get(name) or ())[:limit]
                if t.get('tag')]

    score = entry.get('rating') or entry.get('audienceRating') or ''

    # thumb is a 2:3 poster for movies and shows, but a 16:9 still for
    # episodes. Rows are landscape, and filling a landscape box with a poster
    # crops it to a middle band, so anything poster-shaped uses the backdrop.
    landscape = (thumb if kind == 'episode' else art) or art or thumb

    media = (entry.get('Media') or [{}])[0]
    resolution = media.get('videoResolution') or ''

    return {
        'rating_key': str(entry.get('ratingKey') or ''),
        # Plex sorts by titleSort, so "The Princess Bride" files under P. The
        # alphabet has to agree with the order it is jumping into.
        'sort_title': entry.get('titleSort') or title,
        'year': str(entry.get('year') or ''),
        'quality': (resolution + 'p') if resolution.isdigit() else resolution.upper(),
        'audio': 'ATMOS' if 'atmos' in (media.get('audioProfile') or '') else '',
        'range': '',
        'label': label,
        'subtitle': subtitle,
        'type': kind,
        'thumb': image_url(address, token, thumb),
        'poster': image_url(address, token, poster),
        'landscape': image_url(address, token, landscape),
        'genres': tags('Genre', 3),
        'cast': tags('Role', 4),
        'directors': tags('Director', 1),
        'score': '{0:.1f}'.format(float(score)) if score else '',
        'content_rating': entry.get('contentRating') or '',
        'art': image_url(address, token, art),
        'plot': entry.get('summary') or '',
        'duration': int(entry.get('duration') or 0) // 1000,
        'view_offset': int(entry.get('viewOffset') or 0) // 1000,
        'show': entry.get('grandparentTitle') or '',
    }


def image_url(address, token, path):
    if not path:
        return ''
    if path.startswith('http'):
        return path
    return '{0}{1}?X-Plex-Token={2}'.format(address, path, quote(token))


def stream_url(address, token, rating_key):
    """
    A playable URL for one item.

    Direct from the server rather than through a transcode: the box plays
    what Plex holds, and asking the server to re-encode it would be a
    decision made on the viewer's behalf for no reason.
    """
    data = get_json(address, token, '/library/metadata/' + str(rating_key))
    for entry in (data.get('MediaContainer', {}).get('Metadata') or ()):
        for medium in (entry.get('Media') or ()):
            for part in (medium.get('Part') or ()):
                key = part.get('key')
                if key:
                    return '{0}{1}?X-Plex-Token={2}'.format(
                        address, key, quote(token))
    return ''


# Hubs never return stream details - no combination of includeStreams,
# includeElements or checkFiles brings them back - and HDR and Dolby Vision
# live on the video stream. Asking per item would be 30 requests a row, so ask
# for the whole row at once: /library/metadata takes comma-separated keys and
# answers for all of them in a single round trip.
def add_ranges(address, token, items):
    """Fill in the HDR/DV badge, which needs stream detail the hub omits."""
    keys = [i['rating_key'] for i in items if i.get('rating_key')]
    if not keys:
        return items

    entries = []
    for at in range(0, len(keys), BATCH):
        chunk = keys[at:at + BATCH]
        try:
            data = get_json(address, token,
                            '/library/metadata/' + ','.join(chunk))
        except Exception:
            # A badge is not worth failing a listing over.
            continue
        entries.extend(data.get('MediaContainer', {}).get('Metadata') or ())

    ranges = {}
    for entry in entries:
        streams = ((entry.get('Media') or [{}])[0].get('Part') or [{}])[0]
        for stream in (streams.get('Stream') or ()):
            if stream.get('streamType') != 1:
                continue
            if stream.get('DOVIPresent'):
                ranges[str(entry.get('ratingKey'))] = 'DV'
            elif stream.get('colorTrc') in ('smpte2084', 'arib-std-b67'):
                ranges[str(entry.get('ratingKey'))] = 'HDR'
            break

    for item in items:
        item['range'] = ranges.get(item['rating_key'], '')
    return items


# Music hubs come back too. This is a video browser, so they are dropped
# rather than shown and then failing to play in a video window.
SEARCH_TYPES = ('movie', 'show', 'season', 'episode')

# Keys go in the URL, so they cannot all go in one request: a
# 1368-item library page built a URL the server simply dropped.
BATCH = 80
PAGE = 100


def search(address, token, query, limit=ROW_LIMIT):
    """Videos matching a query, flattened out of the per-type hubs."""
    data = get_json(address, token, '/hubs/search',
                    {'query': query, 'limit': limit})
    items = []
    for hub in (data.get('MediaContainer', {}).get('Hub') or ()):
        if hub.get('type') not in SEARCH_TYPES:
            continue
        for entry in (hub.get('Metadata') or ()):
            items.append(item_details(address, token, entry))
    return items


def sections(address, token):
    """The server's libraries."""
    data = get_json(address, token, '/library/sections')
    return [{'key': str(d.get('key') or ''),
             'type': d.get('type') or '',
             'title': d.get('title') or ''}
            for d in (data.get('MediaContainer', {}).get('Directory') or ())]


def letters(address, token, section):
    """The A-Z index for a library, with a count per bucket."""
    data = get_json(address, token,
                    '/library/sections/{0}/firstCharacter'.format(section))
    return [{'title': d.get('title') or '', 'size': int(d.get('size') or 0)}
            for d in (data.get('MediaContainer', {}).get('Directory') or ())]


def section_items(address, token, section, letter=None, start=0, size=None):
    """
    A library, sorted by title.

    size None fetches the lot. A letter narrows it to that bucket; the bucket
    keys are single characters and one of them is '#', so the path has to be
    quoted - unquoted it reads as a URL fragment and the request arrives
    unauthenticated.
    """
    if letter:
        path = '/library/sections/{0}/firstCharacter/{1}'.format(
            section, quote(letter))
    else:
        path = '/library/sections/{0}/all'.format(section)

    params = {'sort': 'titleSort'}
    if size is not None:
        params['X-Plex-Container-Start'] = start
        params['X-Plex-Container-Size'] = size

    data = get_json(address, token, path, params)
    container = data.get('MediaContainer', {})
    items = [item_details(address, token, entry)
             for entry in (container.get('Metadata') or ())]
    total = int(container.get('totalSize') or container.get('size') or 0)
    return items, total


# A show or season has no media of its own. Its quality is whichever of its
# episodes you look at, which is one cheap request away - allLeaves for a
# show, children for a season, both answered in hundredths of a second.
CHILD_PATHS = {'show': 'allLeaves', 'season': 'children'}


def add_child_quality(address, token, items):
    """Borrow an episode's quality for the shows and seasons above it."""
    for item in items:
        if item['quality'] or item['type'] not in CHILD_PATHS:
            continue
        try:
            data = get_json(
                address, token,
                '/library/metadata/{0}/{1}'.format(
                    item['rating_key'], CHILD_PATHS[item['type']]),
                {'X-Plex-Container-Start': 0, 'X-Plex-Container-Size': 1})
        except Exception:
            continue
        for entry in (data.get('MediaContainer', {}).get('Metadata') or ()):
            media = (entry.get('Media') or [{}])[0]
            resolution = media.get('videoResolution') or ''
            if resolution:
                item['quality'] = ((resolution + 'p') if resolution.isdigit()
                                   else resolution.upper())
            if 'atmos' in (media.get('audioProfile') or ''):
                item['audio'] = 'ATMOS'
            break
    return items
