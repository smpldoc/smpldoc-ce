import json
import threading
import unittest
import urllib.error
import urllib.request

from smpldoc.exposure import ExposureError, check_exposure, is_loopback, self_check
from smpldoc.http_server import Heartbeat, Route, build_server, default_routes

OK = lambda req: (200, {"status": "ok"})
SECRET = Route("/jobs", lambda req: (200, {"jobs": ["secret"]}), public=False)


def serve(routes, authenticator=None):
    server = build_server("127.0.0.1", 0, routes, authenticator)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def get(url, method="GET", headers=None):
    req = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


class ServerTest(unittest.TestCase):
    def start(self, routes, authenticator=None):
        server, url = serve(routes, authenticator)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return url

    def test_health_is_public_and_says_nothing_else(self):
        beat = Heartbeat()
        url = self.start(default_routes(beat))
        code, headers, body = get(url + "/healthz")
        self.assertEqual((code, json.loads(body)), (200, {"status": "ok"}))
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("Python", headers.get("Server", ""))

    def test_ready_follows_the_heartbeat(self):
        now = [100.0]
        beat = Heartbeat(clock=lambda: now[0])
        url = self.start(default_routes(beat, max_age=60))
        self.assertEqual(get(url + "/readyz")[0], 503)  # never beat
        beat.beat()
        self.assertEqual(get(url + "/readyz")[0], 200)
        now[0] += 61
        self.assertEqual(get(url + "/readyz")[0], 503)

    def test_unknown_paths_and_methods(self):
        url = self.start(default_routes(Heartbeat()))
        self.assertEqual(get(url + "/nope")[0], 404)
        self.assertEqual(get(url + "/healthz", "POST")[0], 405)
        self.assertEqual(get(url + "/healthz", "DELETE")[0], 405)
        self.assertEqual(get(url + "/healthz?x=1")[0], 200)
        self.assertEqual(get(url + "/healthz/../healthz")[0], 404)  # exact match only

    def test_protected_routes_fail_closed_without_an_authenticator(self):
        url = self.start([SECRET])
        code, _, body = get(url + "/jobs")
        self.assertEqual(code, 401)
        self.assertNotIn(b"secret", body)
        for odd in ("//jobs", "/jobs?x=/healthz", "/jobs#frag"):
            self.assertEqual(get(url + odd)[0], 401, odd)  # odd paths never skip the gate
        for other in ("/jobs/", "/JOBS", "/jobs%2f", "/./jobs"):
            self.assertEqual(get(url + other)[0], 404, other)

    def test_protected_routes_use_the_authenticator(self):
        url = self.start([SECRET], authenticator=lambda headers: headers.get("Authorization") == "Bearer good")
        self.assertEqual(get(url + "/jobs")[0], 401)
        self.assertEqual(get(url + "/jobs", headers={"Authorization": "Bearer bad"})[0], 401)
        self.assertEqual(get(url + "/jobs", headers={"Authorization": "Bearer good"})[0], 200)

    def test_a_crashing_handler_leaks_nothing(self):
        def boom(req):
            raise RuntimeError("internal detail /etc/passwd")
        url = self.start([Route("/boom", boom, public=True)])
        code, _, body = get(url + "/boom")
        self.assertEqual(code, 500)
        self.assertNotIn(b"passwd", body)


class ExposureTest(unittest.TestCase):
    def test_loopback_detection(self):
        for h in ("127.0.0.1", "::1", "localhost", "127.5.5.5"):
            self.assertTrue(is_loopback(h), h)
        for h in ("0.0.0.0", "::", "10.0.0.5", "example.com", ""):
            self.assertFalse(is_loopback(h), h)

    def test_public_bind_is_refused_when_a_protected_route_has_no_auth(self):
        with self.assertRaises(ExposureError):
            check_exposure("0.0.0.0", [SECRET], auth_configured=False)

    def test_public_bind_is_fine_with_auth_or_with_only_public_routes(self):
        check_exposure("0.0.0.0", [SECRET], auth_configured=True)
        check_exposure("0.0.0.0", default_routes(Heartbeat()), auth_configured=False)

    def test_loopback_bind_is_always_fine(self):
        check_exposure("127.0.0.1", [SECRET], auth_configured=False)

    def test_self_check_passes_when_protected_routes_refuse_anonymous_calls(self):
        server, url = serve([SECRET], authenticator=lambda h: False)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self_check(url, [SECRET])

    def test_self_check_fails_loudly_when_a_protected_route_answers(self):
        server, url = serve([SECRET], authenticator=lambda h: True)  # a wiring mistake
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with self.assertRaises(ExposureError):
            self_check(url, [SECRET])


if __name__ == "__main__":
    unittest.main()
