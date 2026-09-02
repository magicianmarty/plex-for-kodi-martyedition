# coding=utf-8
"""
The Companion control server.

One small threaded HTTP server, on the port advertised over GDM. Everything a
controller does after discovery arrives here:

    GET /resources                      who are you
    GET /player/timeline/poll           what are you doing
    GET /player/timeline/subscribe      tell me, repeatedly, without my asking
    GET /player/timeline/unsubscribe    stop
    GET /player/navigation/<command>    move the selection
    GET /player/playback/<command>      transport, and start playing something
    GET /player/application/<command>   remote keyboard

No handler here does slow work. The apps treat a slow reply as a dead player,
and the two things that genuinely take time - fetching a play queue and opening
the video window - are queued by commands.py and run on the Cron thread, so the
call that acknowledges them returns immediately. State catches up through the
timeline the controller is already watching.

The server binds all interfaces because that is the point of it, and it is
unauthenticated because the protocol has no authentication to offer. That is the
same exposure as Kodi's own remote-control port, but it is a real one, so the
setting that starts this defaults to off.
"""

from __future__ import absolute_import

import socket
import threading

from six.moves import BaseHTTPServer
from six.moves import socketserver
from six.moves.urllib.parse import urlparse, parse_qs

from . import commands
from . import protocol
from . import subscribers

from .. import util


class CompanionHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    # The apps send HTTP/1.1 and reuse the connection; answering 1.0 makes them
    # reconnect for every button press, which is slow enough to feel like lag.
    protocol_version = "HTTP/1.1"

    server_version = "PM4K-Companion"

    def log_message(self, format, *args):
        """
        Silenced deliberately. PMS polls this server every few seconds and a
        subscribed phone posts every second; at DEBUG that is thousands of
        useless lines an hour in a log people actually read.
        """
        pass

    def _identity(self):
        return self.server.identity

    def _send(self, body, content_type="text/xml;charset=utf-8", code=200):
        payload = body.encode("utf-8") if not isinstance(body, bytes) else body
        try:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("X-Plex-Client-Identifier",
                             self._identity().get("machine_identifier", ""))
            for name, value in protocol.CORS_HEADERS:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(payload)
        except (socket.error, OSError):
            # Controller hung up mid-reply. Routine; it moved on or went to
            # sleep, and there is nothing to recover.
            pass

    def do_OPTIONS(self):
        self._send("", content_type="text/plain", code=200)

    def do_POST(self):
        self.do_GET()

    def do_GET(self):
        try:
            self._route()
        except Exception:
            util.ERROR("Companion: error handling {0}".format(self.path))
            try:
                self._send(protocol.command_response(500, "Internal Server Error"), code=500)
            except Exception:
                pass

    def _route(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        # A controller talking to several players on one subnet addresses each
        # by identifier; answering one aimed at a different device would have
        # two boxes react to the same keypress.
        target = self.headers.get("X-Plex-Target-Client-Identifier")
        if target and target != self._identity().get("machine_identifier"):
            self._send(protocol.command_response(404, "Not Found"), code=404)
            return

        if path in ("/resources", "/player/resources"):
            self._send(self._resources())
            return

        if path.startswith("/player/timeline/"):
            self._timeline(path.rsplit("/", 1)[-1], params)
            return

        if path.startswith("/player/"):
            parts = path.split("/")
            if len(parts) >= 4:
                self._command(parts[2], parts[3], params)
                return

        self._send(protocol.command_response(404, "Not Found"), code=404)

    def _resources(self):
        identity = self._identity()
        return protocol.resources_xml(
            machine_identifier=identity.get("machine_identifier", ""),
            name=identity.get("name", "Kodi"),
            product=identity.get("product", "PM4K"),
            version=identity.get("version", ""),
            platform=identity.get("platform", ""),
            platform_version=identity.get("platform_version", ""),
        )

    def _command_id(self, params):
        try:
            return int(params.get("commandID", 0))
        except (TypeError, ValueError):
            return 0

    def _timeline(self, action, params):
        identity = self._identity()
        command_id = self._command_id(params)
        uuid = (params.get("X-Plex-Client-Identifier")
                or self.headers.get("X-Plex-Client-Identifier"))

        if action == "subscribe":
            if uuid:
                subscribers.REGISTRY.add(
                    uuid,
                    self.client_address[0],
                    params.get("port", 32400),
                    command_id,
                    params.get("protocol", "http"),
                )
            self._send(protocol.command_response())
            return

        if action == "unsubscribe":
            if uuid:
                subscribers.REGISTRY.remove(uuid)
            self._send(protocol.command_response())
            return

        if action == "poll":
            # A polling controller is also announcing it is still there; without
            # this a phone that only ever polls is pruned out from under itself.
            if uuid:
                existing = {s.uuid: s for s in subscribers.REGISTRY.all()}.get(uuid)
                if existing:
                    existing.renew(command_id)
            self._send(subscribers.timeline_document(
                command_id=command_id,
                machine_identifier=identity.get("machine_identifier")))
            return

        self._send(protocol.command_response(404, "Not Found"), code=404)

    def _command(self, section, command, params):
        handled = commands.execute(section, command, params)
        if handled:
            self._send(protocol.command_response())
        else:
            util.DEBUG_LOG("Companion: unhandled command {0}/{1}", section, command)
            self._send(protocol.command_response(404, "Not Found"), code=404)


class CompanionHTTPServer(socketserver.ThreadingMixIn, BaseHTTPServer.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, identity):
        self.identity = identity
        BaseHTTPServer.HTTPServer.__init__(self, address, handler)

    def handle_error(self, request, client_address):
        """
        Connection resets are the normal way a controller goes away, and the
        base class prints a traceback for each one.
        """
        pass


class ControlServer(threading.Thread):
    def __init__(self, port, identity):
        threading.Thread.__init__(self, name="PLEX:COMPANION:HTTP")
        self.daemon = True
        self.port = port
        self.identity = identity
        self.httpd = None
        self.started = threading.Event()

    def run(self):
        try:
            self.httpd = CompanionHTTPServer(("0.0.0.0", self.port), CompanionHandler,
                                             self.identity)
        except Exception:
            util.ERROR("Companion: could not bind control port {0}".format(self.port))
            self.started.set()
            return

        util.LOG("Companion: control server listening on {0}", self.port)
        self.started.set()
        try:
            self.httpd.serve_forever(poll_interval=0.5)
        except Exception:
            util.ERROR("Companion: control server stopped unexpectedly")
        finally:
            util.DEBUG_LOG("Companion: control server stopped")

    @property
    def bound(self):
        return self.httpd is not None

    def stop(self):
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
            self.httpd = None
