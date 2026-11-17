"""A small, closed HTTP surface on the standard library. Today it serves only health checks.
Routes are public or protected. A protected route is refused unless an authenticator says yes,
and with no authenticator it is refused always (fail closed)."""
import json
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional


@dataclass(frozen=True)
class Route:
    path: str
    handler: Callable  # (headers) -> (status, json-able dict)
    public: bool = False


class Heartbeat:
    def __init__(self, clock=time.monotonic):
        self._clock, self._last = clock, None

    def beat(self):
        self._last = self._clock()

    def fresh(self, max_age):
        return self._last is not None and self._clock() - self._last <= max_age


def default_routes(beat: Heartbeat, max_age: float = 300):
    def ready(_):
        return (200, {"status": "ok"}) if beat.fresh(max_age) else (503, {"status": "stale"})
    return [Route("/healthz", lambda _: (200, {"status": "ok"}), public=True),
            Route("/readyz", ready, public=True)]


def build_server(bind, port, routes, authenticator: Optional[Callable] = None, timeout=10):
    table = {r.path: r for r in routes}

    class Handler(BaseHTTPRequestHandler):
        server_version, sys_version = "smpldoc", ""
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass  # request lines can hold identifiers; log nothing here

        def _reply(self, status, payload, head_only=False, extra=()):
            body = json.dumps(payload).encode()
            self.send_response(status)
            for k, v in (("Content-Type", "application/json"), ("Cache-Control", "no-store"),
                         ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"),
                         ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"),
                         ("Content-Length", str(len(body))), ("Connection", "close"), *extra):
                self.send_header(k, v)
            self.end_headers()
            if not head_only:
                self.wfile.write(body)

        def _serve(self, head_only):
            route = table.get(self.path.split("?", 1)[0])
            if route is None:
                return self._reply(404, {"error": "not found"}, head_only)
            if not route.public and not (authenticator and authenticator(self.headers)):
                return self._reply(401, {"error": "unauthorized"}, head_only,
                                   extra=(("WWW-Authenticate", "Bearer"),))
            try:
                status, payload = route.handler(self.headers)
            except Exception:
                return self._reply(500, {"error": "internal error"}, head_only)
            self._reply(status, payload, head_only)

        def do_GET(self):
            self._serve(False)

        def do_HEAD(self):
            self._serve(True)

        def _no(self):
            self._reply(405, {"error": "method not allowed"}, extra=(("Allow", "GET, HEAD"),))

        do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _no

    Handler.timeout = timeout
    server = ThreadingHTTPServer((bind, port), Handler)
    server.daemon_threads = True
    return server
