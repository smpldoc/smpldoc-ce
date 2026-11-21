import json
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from smpldoc.adapters.aws_creds import CredentialError, CredentialProvider

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


class Metadata:
    """A local stand-in for the ECS task-role endpoint and the EC2 metadata service (IMDSv2)."""

    def __init__(self, expires_in=3600):
        self.expires_in, self.seen, self.imds_token = expires_in, [], "imds-token-1"
        m = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body=b""):
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _creds(self):
                exp = (NOW + timedelta(seconds=m.expires_in)).strftime("%Y-%m-%dT%H:%M:%SZ")
                return json.dumps({"AccessKeyId": "ASIAEXAMPLE", "SecretAccessKey": "secret-from-role", "Token": "role-token", "Expiration": exp}).encode()

            def do_PUT(self):
                m.seen.append(("PUT", self.path, self.headers.get("X-aws-ec2-metadata-token-ttl-seconds")))
                self._send(200, m.imds_token.encode()) if self.path == "/latest/api/token" else self._send(404)

            def do_GET(self):
                m.seen.append(("GET", self.path, self.headers.get("X-aws-ec2-metadata-token")))
                if self.path == "/v2/credentials/abc":  # ECS
                    return self._send(200, self._creds())
                if self.headers.get("X-aws-ec2-metadata-token") != m.imds_token:
                    return self._send(401)
                if self.path == "/latest/meta-data/iam/security-credentials/":
                    return self._send(200, b"my-role")
                if self.path == "/latest/meta-data/iam/security-credentials/my-role":
                    return self._send(200, self._creds())
                self._send(404)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class CredsTest(unittest.TestCase):
    def setUp(self):
        self.md = Metadata()
        self.addCleanup(self.md.close)
        self.now = [NOW]

    def provider(self, env, **kw):
        return CredentialProvider(env, ecs_base=self.md.url, imds_base=self.md.url, now=lambda: self.now[0], timeout=2, **kw)

    def test_static_keys_from_the_environment(self):
        c = self.provider({"AWS_ACCESS_KEY_ID": "AKIAx", "AWS_SECRET_ACCESS_KEY": "s", "AWS_SESSION_TOKEN": "t"}).get()
        self.assertEqual((c.access_key, c.secret_key, c.token), ("AKIAx", "s", "t"))
        self.assertEqual(self.md.seen, [], "static keys never call a metadata service")

    def test_half_a_static_pair_is_an_error_not_a_silent_fallback(self):
        with self.assertRaises(CredentialError):
            self.provider({"AWS_ACCESS_KEY_ID": "AKIAx"}).get()

    def test_ecs_task_role(self):
        c = self.provider({"AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": "/v2/credentials/abc"}).get()
        self.assertEqual((c.access_key, c.secret_key, c.token), ("ASIAEXAMPLE", "secret-from-role", "role-token"))
        self.assertEqual(self.md.seen[0][:2], ("GET", "/v2/credentials/abc"))

    def test_an_ecs_uri_that_is_not_a_path_is_refused(self):
        for bad in ("http://evil.example/x", "//evil.example/x", "v2/credentials/abc", "/../x"):
            with self.assertRaises(CredentialError, msg=bad):
                self.provider({"AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": bad}).get()
        self.assertEqual(self.md.seen, [])

    def test_ec2_instance_role_uses_imdsv2(self):
        c = self.provider({}).get()
        self.assertEqual(c.access_key, "ASIAEXAMPLE")
        self.assertEqual(self.md.seen[0][:2], ("PUT", "/latest/api/token"))  # token first: IMDSv2 only
        self.assertTrue(all(s[2] == "imds-token-1" for s in self.md.seen[1:]))

    def test_credentials_are_cached_and_refreshed_before_they_expire(self):
        p = self.provider({"AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": "/v2/credentials/abc"})
        p.get()
        p.get()
        self.assertEqual(len(self.md.seen), 1)
        self.now[0] = NOW + timedelta(seconds=3600 - 200)  # inside the 5-minute safety window
        p.get()
        self.assertEqual(len(self.md.seen), 2)

    def test_nothing_available_is_a_clear_error_that_names_no_secret(self):
        dead = CredentialProvider({}, ecs_base="http://127.0.0.1:1", imds_base="http://127.0.0.1:1", now=lambda: NOW, timeout=1)
        with self.assertRaises(CredentialError) as ctx:
            dead.get()
        self.assertIn("no AWS credentials", str(ctx.exception))

    def test_redirects_are_not_followed(self):
        class R(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", self.server.target)
                self.end_headers()

        redirect = ThreadingHTTPServer(("127.0.0.1", 0), R)
        redirect.target = self.md.url + "/v2/credentials/abc"
        threading.Thread(target=redirect.serve_forever, daemon=True).start()
        self.addCleanup(redirect.server_close)
        self.addCleanup(redirect.shutdown)
        p = CredentialProvider({"AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": "/v2/credentials/abc"},
                               ecs_base=f"http://127.0.0.1:{redirect.server_address[1]}", imds_base="http://127.0.0.1:1", now=lambda: NOW, timeout=2)
        with self.assertRaises(CredentialError):
            p.get()
        self.assertEqual(self.md.seen, [])


if __name__ == "__main__":
    unittest.main()
