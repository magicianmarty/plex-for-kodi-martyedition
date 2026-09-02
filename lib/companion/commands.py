# coding=utf-8
"""
Turning a Companion request into something the add-on actually does.

Commands arrive on HTTP worker threads, and what they are allowed to touch from
there differs:

  immediately   Navigation and transport. `xbmc.executebuiltin` and JSON-RPC are
                marshalled by Kodi itself, so calling them off-thread is safe and
                a keypress lands with no perceptible delay.

  on the Cron   Anything that opens a window - playMedia, and going home, which
  thread        rebuilds the hub screen. Driving the window stack from an
                arbitrary thread is how add-ons deadlock Kodi.

The Cron thread is the add-on's own established place for deferred UI work:
HomeWindow is a CronReceiver and repopulates hubs from its tick(). Queued work
is not left waiting for the next scheduled tick, though - forceTick() wakes Cron
within about 100ms, which is below the threshold where a remote feels laggy.

Seeks deliberately go through SeekPlayerHandler rather than Kodi's own seek.
That handler is where this fork's playback policy lives, so a seek driven from a
phone behaves exactly like one driven from the on-screen scrub bar.
"""

from __future__ import absolute_import

import threading

from six.moves import queue

from .. import util
from ..kodijsonrpc import rpc

# Companion navigation command -> Kodi action. Everything absent from here is
# either unimplemented or handled as a special case in _navigate().
NAVIGATION_ACTIONS = {
    "moveUp": "Up",
    "moveDown": "Down",
    "moveLeft": "Left",
    "moveRight": "Right",
    "select": "Select",
    "back": "Back",
    "contextMenu": "ContextMenu",
    "toggleOSD": "OSD",
    "pageUp": "PageUp",
    "pageDown": "PageDown",
    "nextLetter": "NextLetter",
    "previousLetter": "PrevLetter",
}

# How far stepForward/stepBack move, in milliseconds. Plex's apps send no
# distance with these, so the player picks; this matches Kodi's own small skip.
STEP_MS = 30000


class DeferredCommands(util.CronReceiver):
    """
    Work that has to happen on the Cron thread rather than an HTTP one.

    Failures are logged and dropped rather than raised: this runs inside Cron's
    receiver loop, and an exception escaping here would take out the tick that
    HomeWindow also depends on.
    """

    def __init__(self):
        self.queue = queue.Queue()
        self.registered = False

    def register(self):
        if util.CRON and not self.registered:
            util.CRON.registerReceiver(self)
            self.registered = True

    def unregister(self):
        if util.CRON and self.registered:
            util.CRON.cancelReceiver(self)
        self.registered = False

    def put(self, func):
        self.queue.put(func)
        try:
            if util.CRON:
                util.CRON.forceTick()
        except Exception:
            pass

    def tick(self):
        while True:
            try:
                func = self.queue.get_nowait()
            except queue.Empty:
                return
            try:
                func()
            except Exception:
                util.ERROR("Companion: deferred command failed")

    def drain(self):
        """Discard anything queued but not yet run, on shutdown."""
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                return


DEFERRED = DeferredCommands()


def _active_player_id():
    try:
        players = rpc.Player.GetActivePlayers()
    except Exception:
        return None
    return players[0]["playerid"] if players else None


def _navigate(command):
    from kodi_six import xbmc

    if command == "home":
        # Rebuilds the hub screen, so it belongs on the Cron thread.
        DEFERRED.put(lambda: util.MONITOR.actionHome())
        return True

    action = NAVIGATION_ACTIONS.get(command)
    if not action:
        return False

    xbmc.executebuiltin("Action({0})".format(action))
    return True


def _seek_to(offset_ms):
    """
    Absolute seek, in milliseconds, through the add-on's own seek handler.

    Falls back to Kodi's seek when nothing is playing through PlexPlayer - a
    music or photo timeline, say - so the command is never silently ignored.
    """
    from .. import player

    handler = getattr(player.PLAYER, "handler", None)
    if handler is not None and hasattr(handler, "seek"):
        handler.seek(offset_ms)
        return True

    player_id = _active_player_id()
    if player_id is None:
        return False

    seconds, milliseconds = divmod(int(offset_ms), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    rpc.Player.Seek(playerid=player_id, value={"time": {
        "hours": hours, "minutes": minutes, "seconds": seconds,
        "milliseconds": milliseconds}})
    return True


def _playback(command, params):
    from kodi_six import xbmc

    if command in ("play", "pause", "playPause"):
        player_id = _active_player_id()
        if player_id is None:
            return False
        if command == "playPause":
            rpc.Player.PlayPause(playerid=player_id)
        else:
            rpc.Player.PlayPause(playerid=player_id, play=(command == "play"))
        return True

    if command == "stop":
        xbmc.Player().stop()
        return True

    if command == "seekTo":
        try:
            offset = int(params.get("offset", 0))
        except (TypeError, ValueError):
            return False
        return _seek_to(offset)

    if command in ("stepForward", "stepBack"):
        from .. import player
        handler = getattr(player.PLAYER, "handler", None)
        current = getattr(handler, "trueTime", None) if handler else None
        if current is None:
            xbmc.executebuiltin(
                "Action({0})".format("StepForward" if command == "stepForward" else "StepBack"))
            return True
        delta = STEP_MS if command == "stepForward" else -STEP_MS
        return _seek_to(max(int(current * 1000) + delta, 0))

    if command in ("skipNext", "skipPrevious"):
        xbmc.executebuiltin(
            "Action({0})".format("SkipNext" if command == "skipNext" else "SkipPrevious"))
        return True

    if command == "setParameters":
        volume = params.get("volume")
        if volume is None:
            return True
        try:
            xbmc.executebuiltin("SetVolume({0})".format(int(volume)))
        except (TypeError, ValueError):
            return False
        return True

    if command == "setStreams":
        return _set_streams(params)

    if command == "playMedia":
        DEFERRED.put(lambda: play_media(params))
        return True

    if command == "refreshPlayQueue":
        return True

    return False


def _set_streams(params):
    from .. import player

    handler = getattr(player.PLAYER, "handler", None)
    if handler is None:
        return False

    changed = False
    audio = params.get("audioStreamID")
    subtitle = params.get("subtitleStreamID")

    video = getattr(handler, "currentlyPlaying", None) or getattr(player.PLAYER, "video", None)
    if video is None:
        return False

    try:
        if audio is not None:
            video.selectStream(int(audio))
            changed = True
        if subtitle is not None:
            video.selectStream(int(subtitle))
            changed = True
    except Exception:
        util.ERROR("Companion: could not set streams")
        return False

    return changed


def play_media(params):
    """
    Start playback of what the controller picked, on the Cron thread.

    The controller has already built a play queue on the server and hands us its
    containerKey, so the queue is fetched rather than recreated - recreating it
    loses the ordering and the "up next" the user just chose on their phone.
    """
    from plexnet import plexapp, playqueue
    from ..windows import videoplayer

    machine_identifier = params.get("machineIdentifier")
    server = None
    if machine_identifier:
        server = plexapp.SERVERMANAGER.getServer(machine_identifier)
    server = server or plexapp.SERVERMANAGER.selectedServer
    if not server:
        util.LOG("Companion: playMedia with no reachable server")
        return

    try:
        offset = int(params.get("offset", 0) or 0)
    except (TypeError, ValueError):
        offset = 0

    container_key = params.get("containerKey") or ""
    play_queue_id = None
    if "/playQueues/" in container_key:
        play_queue_id = container_key.split("/playQueues/", 1)[1].split("?", 1)[0].strip("/")

    if play_queue_id:
        pq = playqueue.createPlayQueueForId(play_queue_id, server=server)
        pq.waitForInitialization()
        videoplayer.play(play_queue=pq, resume=bool(offset))
        return

    key = params.get("key")
    if not key:
        util.LOG("Companion: playMedia with neither containerKey nor key")
        return

    item = server.getObject(key)
    if not item:
        util.LOG("Companion: playMedia could not resolve {0}", key)
        return

    videoplayer.play(video=item, resume=bool(offset))


def execute(section, command, params):
    """
    Run one Companion command.

    Returns False for anything unrecognised so the caller can answer 404-ish
    rather than claiming success - a controller told a command worked when it
    did not will not retry, and the user just sees a dead button.
    """
    try:
        if section == "navigation":
            return _navigate(command)
        if section == "playback":
            return _playback(command, params)
        if section == "application":
            return _application(command, params)
    except Exception:
        util.ERROR("Companion: command {0}/{1} failed".format(section, command))
        return False
    return False


def _application(command, params):
    if command == "setText":
        return _set_text(params)
    return False


def _set_text(params):
    """
    Remote keyboard input, used when the app offers to type into a search box.

    Companion sends the whole field on every keystroke, where Kodi's SendText
    only appends, so this replaces rather than accumulates. Kodi has no "clear
    the field" input call, which is why the text is sent as one shot with
    done=False - the field is rewritten by the next message anyway.
    """
    text = params.get("text", "")
    rpc.Input.SendText(text=text, done=False)
    return True


_LOCK = threading.Lock()


def start():
    with _LOCK:
        DEFERRED.register()


def stop():
    with _LOCK:
        DEFERRED.unregister()
        DEFERRED.drain()
