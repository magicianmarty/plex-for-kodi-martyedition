# coding=utf-8
"""
Wire format for Plex Companion - the protocol a Plex app speaks to a player it
is casting to.

None of this is published by Plex; it is reconstructed from what the apps
actually send, and from the Roku implementation this add-on descends from,
which still sits commented out at the bottom of plexnet/gdm.py.

Two conversations make up the protocol:

  discovery   The controller broadcasts "M-SEARCH * HTTP/1.0" on UDP 32412 and
              every player on the subnet answers with an HTTP-shaped block of
              headers naming its HTTP port. That is all that puts a device in
              the app's cast picker.

  control     The controller then talks HTTP to that port: /resources to
              identify the player, /player/... to drive it, and
              /player/timeline/... to find out what it is doing.

Everything here is pure - strings in, strings out, no Kodi and no sockets - so
the wire format can be tested without either.

Two details are worth knowing before changing anything:

  * A timeline reply must always carry all three of video, music and photo,
    even when two of them are stopped. Send one and the apps show a player
    stuck on a spinner.

  * commandID is echoed, not generated. The controller numbers its own
    requests and matches replies on that number; a reply carrying the wrong one
    is dropped silently, which looks exactly like the player having crashed.
"""

from __future__ import absolute_import

from xml.sax.saxutils import quoteattr

# The controller broadcasts discovery here. Plex's own players answer on this
# port, so it is not ours to choose.
GDM_PORT = 32412

# What Plex's own clients use for the control server. Configurable, because the
# player advertises it in the GDM reply, but there is no reason to move it.
DEFAULT_HTTP_PORT = 3005

# Claimed in both the GDM reply and /resources, and they must agree. Anything
# listed here the apps will actually try to use, so this is a promise: adding
# "mirror" means agreeing to serve /player/mirror/details.
PROTOCOL_CAPABILITIES = "timeline,playback,navigation,playqueues"

TIMELINE_TYPES = ("video", "music", "photo")

# Where the user is, as opposed to what is playing. The apps use this to decide
# whether to show a remote or a now-playing screen.
LOCATION_NAVIGATION = "navigation"
LOCATION_FULLSCREEN_VIDEO = "fullScreenVideo"
LOCATION_FULLSCREEN_MUSIC = "fullScreenMusic"
LOCATION_FULLSCREEN_PHOTO = "fullScreenPhoto"

# Sent on every reply. The apps are browser-based in places and will not read a
# response that omits these; the header list is what Plex Web actually asks for
# in its preflight, and a missing entry there fails the whole request.
CORS_HEADERS = (
    ("Access-Control-Allow-Origin", "*"),
    ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
    ("Access-Control-Allow-Headers",
     "x-plex-version, x-plex-platform-version, x-plex-username, x-plex-client-identifier, "
     "x-plex-target-client-identifier, x-plex-device-name, x-plex-platform, x-plex-product, "
     "x-plex-device, x-plex-model, x-plex-device-screen-resolution, x-plex-token, "
     "x-plex-session-identifier, x-plex-client-capabilities, x-plex-provides, accept, "
     "content-type"),
    ("Access-Control-Max-Age", "1209600"),
)

XML_DECLARATION = '<?xml version="1.0" encoding="utf-8"?>\n'


def _attrs(pairs):
    """
    Attribute string from (name, value) pairs, dropping empties.

    Order is preserved rather than sorted: the apps do not care, but a stable
    order makes the tests readable and diffs meaningful.
    """
    out = []
    for name, value in pairs:
        if value is None or value == "":
            continue
        out.append("{0}={1}".format(name, quoteattr(str(value))))
    return " ".join(out)


def gdm_response(name, port, product, version, resource_identifier,
                 device_class="stb", protocol_capabilities=PROTOCOL_CAPABILITIES):
    """
    The reply to an M-SEARCH, which is HTTP-shaped without being HTTP.

    CRLF line endings and the trailing blank line are both load-bearing - the
    controllers parse this with a header parser, and one that ends without the
    blank line is treated as truncated and ignored.
    """
    lines = [
        "HTTP/1.0 200 OK",
        "Name: {0}".format(name),
        "Port: {0}".format(port),
        "Product: {0}".format(product),
        "Content-Type: plex/media-player",
        "Protocol: plex",
        "Protocol-Version: 1",
        "Protocol-Capabilities: {0}".format(protocol_capabilities),
        "Version: {0}".format(version),
        "Resource-Identifier: {0}".format(resource_identifier),
        "Device-Class: {0}".format(device_class),
    ]
    return "\r\n".join(lines) + "\r\n\r\n"


def resources_xml(machine_identifier, name, product, version, platform,
                  platform_version, device_class="stb",
                  protocol_capabilities=PROTOCOL_CAPABILITIES):
    """The player identifying itself, served at /resources."""
    player = _attrs((
        ("title", name),
        ("machineIdentifier", machine_identifier),
        ("product", product),
        ("productVersion", version),
        ("protocol", "plex"),
        ("protocolVersion", "1"),
        ("protocolCapabilities", protocol_capabilities),
        ("deviceClass", device_class),
        ("platform", platform),
        ("platformVersion", platform_version),
    ))
    return "{0}<MediaContainer>\n  <Player {1} />\n</MediaContainer>\n".format(
        XML_DECLARATION, player)


def command_response(code=200, status="OK"):
    """Acknowledgement for every /player/... command."""
    return '{0}<Response code="{1}" status="{2}" />\n'.format(
        XML_DECLARATION, code, status)


def timeline_entry(timeline_type, state, **kwargs):
    """
    One <Timeline>. A stopped one carries type and state and nothing else -
    sending a ratingKey with state="stopped" makes the apps offer to resume
    something that is not on screen.
    """
    if state == "stopped":
        return _attrs((("type", timeline_type), ("state", "stopped")))

    return _attrs((
        ("type", timeline_type),
        ("state", state),
        ("time", kwargs.get("time")),
        ("duration", kwargs.get("duration")),
        ("ratingKey", kwargs.get("ratingKey")),
        ("key", kwargs.get("key")),
        ("containerKey", kwargs.get("containerKey")),
        ("guid", kwargs.get("guid")),
        ("playQueueID", kwargs.get("playQueueID")),
        ("playQueueItemID", kwargs.get("playQueueItemID")),
        ("playQueueVersion", kwargs.get("playQueueVersion")),
        ("machineIdentifier", kwargs.get("machineIdentifier")),
        ("address", kwargs.get("address")),
        ("port", kwargs.get("port")),
        ("protocol", kwargs.get("protocol", "http")),
        ("token", kwargs.get("token")),
        ("seekRange", kwargs.get("seekRange")),
        ("controllable", kwargs.get("controllable")),
        ("volume", kwargs.get("volume")),
        ("shuffle", kwargs.get("shuffle")),
        ("repeat", kwargs.get("repeat")),
        ("audioStreamID", kwargs.get("audioStreamID")),
        ("subtitleStreamID", kwargs.get("subtitleStreamID")),
    ))


def timeline_xml(timelines, command_id=0, location=LOCATION_NAVIGATION,
                 machine_identifier=None):
    """
    The full timeline reply.

    `timelines` maps a type in TIMELINE_TYPES to the kwargs for its entry. Any
    type left out is emitted as stopped rather than omitted, because the apps
    require all three.
    """
    container = _attrs((
        ("commandID", command_id),
        ("location", location),
        ("machineIdentifier", machine_identifier),
    ))

    rows = []
    for timeline_type in TIMELINE_TYPES:
        data = dict(timelines.get(timeline_type) or {})
        state = data.pop("state", "stopped")
        rows.append("  <Timeline {0} />".format(
            timeline_entry(timeline_type, state, **data)))

    return "{0}<MediaContainer {1}>\n{2}\n</MediaContainer>\n".format(
        XML_DECLARATION, container, "\n".join(rows))
