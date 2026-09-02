# coding=utf-8
"""
Plex Companion: letting a Plex app drive this player.

Without it a phone can only reach the box through a generic Kodi remote, which
gives a d-pad and nothing else - the Kodi library it browses is empty, because
everything lives in Plex. Companion is what makes the box appear in the Plex
app's cast picker, so the library on the phone is the real one and an item
tapped there starts here.

Three threads, started together and stopped together:

    GDMAdvertiser   answers discovery on UDP 32412, which is the only thing
                    that puts this player in the cast picker
    ControlServer   the HTTP server the app then talks to
    TimelinePusher  posts playback state to controllers that subscribed

Off by default. The protocol has no authentication of any kind - anyone who can
reach the port can drive the player - so this is opt-in, in the same way Kodi
makes you turn its own remote control on.

Failing to start is not fatal anywhere: without this the add-on is exactly what
it was before, so every entry point here logs and carries on rather than taking
the add-on down with it.
"""

from __future__ import absolute_import

import threading

from . import commands
from . import protocol
from . import subscribers
from .gdm import GDMAdvertiser
from .server import ControlServer

from .. import util

SETTING_ENABLED = "companion"
SETTING_PORT = "companion_port"


class Companion(object):
    def __init__(self):
        self.advertiser = None
        self.server = None
        self.pusher = None
        self.identity = {}
        self.port = protocol.DEFAULT_HTTP_PORT
        self._lock = threading.Lock()

    @property
    def running(self):
        return self.server is not None

    def _build_identity(self):
        from plexnet import plexapp

        interface = plexapp.util.INTERFACE
        return {
            "machine_identifier": interface.getGlobal("clientIdentifier", ""),
            "name": interface.getGlobal("friendlyName", "Kodi"),
            "product": interface.getGlobal("product", "PM4K"),
            "version": interface.getGlobal("appVersionStr", ""),
            "platform": interface.getGlobal("platform", "Kodi"),
            "platform_version": interface.getGlobal("platformVersion", ""),
        }

    def _describe(self):
        """The GDM reply, rebuilt per search so a rename is picked up live."""
        return protocol.gdm_response(
            name=self.identity.get("name", "Kodi"),
            port=self.port,
            product=self.identity.get("product", "PM4K"),
            version=self.identity.get("version", ""),
            resource_identifier=self.identity.get("machine_identifier", ""),
        )

    def start(self):
        with self._lock:
            if self.running:
                return True

            if not util.getSetting(SETTING_ENABLED, False):
                return False

            self.port = int(util.getSetting(SETTING_PORT, protocol.DEFAULT_HTTP_PORT))
            self.identity = self._build_identity()

            if not self.identity.get("machine_identifier"):
                util.LOG("Companion: no client identifier yet, not starting")
                return False

            self.server = ControlServer(self.port, self.identity)
            self.server.start()
            self.server.started.wait(5)

            if not self.server.bound:
                # Without the control server there is nothing for a controller
                # to talk to, so advertising would only offer a dead player.
                util.LOG("Companion: control server did not bind, not advertising")
                self.server = None
                return False

            commands.start()

            self.advertiser = GDMAdvertiser(self._describe)
            self.advertiser.start()

            self.pusher = subscribers.TimelinePusher(
                self.identity.get("machine_identifier"))
            self.pusher.start()

            util.LOG("Companion: started as {0!r} on port {1}",
                     self.identity.get("name"), self.port)
            return True

    def stop(self):
        with self._lock:
            for component in (self.advertiser, self.pusher, self.server):
                if component is None:
                    continue
                try:
                    component.stop()
                except Exception:
                    util.ERROR("Companion: error stopping {0}".format(component))

            self.advertiser = self.pusher = self.server = None

            try:
                commands.stop()
                subscribers.REGISTRY.clear()
            except Exception:
                util.ERROR("Companion: error clearing state")


COMPANION = Companion()


def start():
    try:
        return COMPANION.start()
    except Exception:
        util.ERROR("Companion: could not start")
        return False


def stop():
    try:
        COMPANION.stop()
    except Exception:
        util.ERROR("Companion: could not stop cleanly")
