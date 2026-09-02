# coding=utf-8
"""
The GDM side of Companion: answering "is there a player out there?".

plexnet/gdm.py already speaks the other half of GDM - it *sends* discovery to
find servers. This is the mirror image, and the Roku original it is ported from
is the commented-out GDMAdvertiser at the bottom of that same file.

The exchange is one packet each way. A controller broadcasts

    M-SEARCH * HTTP/1.1

to UDP 32412 and every player answers, unicast, with a block of headers naming
the port its control server is on. Plex Media Server does the same search every
few seconds, so this socket is busy even when no phone is involved - which is
why nothing here logs per packet.

A player that does not answer this is simply not in the cast picker; there is no
error and no other route in. So when a device will not appear, this is the first
thing to check, with:

    nc -u -l 32412        # on another host, to see the broadcasts arrive
"""

from __future__ import absolute_import

import socket
import threading

from . import protocol

from .. import util

RECV_SIZE = 4096

# The socket is only read to notice shutdown, so this is just how long a stop()
# can take, not a poll interval.
SOCKET_TIMEOUT = 1.0


class GDMAdvertiser(threading.Thread):
    """Answers M-SEARCH on UDP 32412 for as long as it is running."""

    def __init__(self, describe, port=protocol.GDM_PORT):
        threading.Thread.__init__(self, name="PLEX:COMPANION:GDM")
        self.daemon = True
        self.describe = describe
        # Injectable only so the tests can bind an ephemeral port; controllers
        # search 32412 and nowhere else.
        self.port = port
        self.socket = None
        self.bound = threading.Event()
        self._stop_event = threading.Event()

    def _bind(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(SOCKET_TIMEOUT)
            sock.bind(("0.0.0.0", self.port))
        except Exception:
            # The descriptor exists as soon as socket() returns, so a failed
            # bind leaks one unless it is closed on the way out.
            sock.close()
            raise
        return sock

    def run(self):
        try:
            self.socket = self._bind()
        except Exception:
            # Nearly always another Plex player already holding the port. It is
            # not recoverable and not fatal: everything except discovery works.
            util.ERROR("Companion: could not bind GDM port {0}".format(self.port))
            self.bound.set()
            return

        util.LOG("Companion: GDM advertiser listening on {0}", self.port)
        self.bound.set()

        while not self._stop_event.is_set():
            try:
                message, sender = self.socket.recvfrom(RECV_SIZE)
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                if self._is_search(message):
                    self.socket.sendto(self.describe().encode("utf-8"), sender)
            except Exception:
                util.ERROR("Companion: failed to answer GDM search")

        try:
            self.socket.close()
        except Exception:
            pass
        util.DEBUG_LOG("Companion: GDM advertiser stopped")

    @staticmethod
    def _is_search(message):
        """
        Plex sends HTTP/1.1 and the Roku code expected 1.0, so match on the verb
        alone rather than the version - a version check here would silently
        stop answering a future controller.
        """
        try:
            first = message.split(b"\r\n", 1)[0].strip()
        except Exception:
            return False
        return first.upper().startswith(b"M-SEARCH")

    def stop(self):
        self._stop_event.set()
        # recvfrom() holds the thread for up to SOCKET_TIMEOUT; closing under it
        # turns that into an immediate OSError instead of a wait on shutdown.
        try:
            if self.socket:
                self.socket.close()
        except Exception:
            pass
