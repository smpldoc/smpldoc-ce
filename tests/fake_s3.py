"""A local stand-in for S3 (path style): ListObjectsV2, ranged GET, DELETE, server-side copy.
Every request must be signed; the signature is recomputed from the request as received."""
import re
import threading
from datetime import datetime, timezone
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urlparse
from xml.sax.saxutils import escape

from smpldoc.adapters.sigv4 import sign

ACCESS, SECRET, REGION = "TESTACCESSKEY", "test-secret-key", "us-east-1"


class FakeS3:
    def __init__(self, bucket="mail", list_body=None):
        self.bucket, self.objects, self.requests, self.list_body = bucket, {}, [], list_body
        s3 = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, code, body=b"", extra=()):
                self.send_response(code)
                for k, v in extra:
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _verify(self):
                auth = self.headers.get("Authorization", "")
                m = re.match(r"AWS4-HMAC-SHA256 Credential=([^/]+)/(\d{8})/([^/]+)/s3/aws4_request, SignedHeaders=([^,]+), Signature=([0-9a-f]{64})$", auth)
                s3.requests.append((self.command, self.path, auth))
                if not m or m.group(1) != ACCESS:
                    return False
                signed = {h: self.headers.get(h) for h in m.group(4).split(";") if h != "host"}
                when = datetime.strptime(self.headers["x-amz-date"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                # Re-sign from the request as received: every signed header except the ones sign() adds itself.
                others = {k: v for k, v in signed.items() if k not in ("x-amz-date", "x-amz-content-sha256", "x-amz-security-token")}
                expected = sign(self.command, f"http://{self.headers['Host']}{self.path}", others, self.headers["x-amz-content-sha256"],
                                access_key=ACCESS, secret_key=SECRET, region=REGION, now=when, token=self.headers.get("x-amz-security-token"))
                return expected["Authorization"] == auth

            def _split(self):
                u = urlparse(self.path)
                parts = unquote(u.path).lstrip("/").split("/", 1)
                return parts[0], (parts[1] if len(parts) > 1 else ""), u.query

            def do_GET(self):
                if not self._verify():
                    return self._reply(403, b"<Error><Code>SignatureDoesNotMatch</Code></Error>")
                bucket, key, query = self._split()
                if bucket != s3.bucket:
                    return self._reply(404, b"<Error><Code>NoSuchBucket</Code></Error>")
                if not key:  # ListObjectsV2
                    q = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
                    prefix = unquote(q.get("prefix", ""))
                    keys = sorted(k for k in s3.objects if k.startswith(prefix))[: int(q.get("max-keys", 1000))]
                    body = s3.list_body or (
                        '<?xml version="1.0" encoding="UTF-8"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                        f"<Name>{bucket}</Name><KeyCount>{len(keys)}</KeyCount><IsTruncated>false</IsTruncated>"
                        + "".join(f"<Contents><Key>{escape(k)}</Key><Size>{len(s3.objects[k])}</Size></Contents>" for k in keys)
                        + "</ListBucketResult>")
                    return self._reply(200, body.encode(), [("Content-Type", "application/xml")])
                if key not in s3.objects:
                    return self._reply(404, b"<Error><Code>NoSuchKey</Code></Error>")
                data = s3.objects[key]
                rng = self.headers.get("Range")
                if rng:
                    a, b = re.match(r"bytes=(\d+)-(\d+)", rng).groups()
                    return self._reply(206, data[int(a): int(b) + 1])
                self._reply(200, data)

            def do_DELETE(self):
                if not self._verify():
                    return self._reply(403)
                _, key, _ = self._split()
                s3.objects.pop(key, None)
                self._reply(204)

            def do_PUT(self):  # CopyObject only
                if not self._verify():
                    return self._reply(403)
                _, key, _ = self._split()
                src = unquote(self.headers.get("x-amz-copy-source", "")).lstrip("/")
                sb, _, sk = src.partition("/")
                if sb != s3.bucket or sk not in s3.objects:
                    return self._reply(404, b"<Error><Code>NoSuchKey</Code></Error>")
                s3.objects[key] = s3.objects[sk]
                self._reply(200, b"<CopyObjectResult><ETag>x</ETag></CopyObjectResult>")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def put(self, key, data):
        self.objects[key] = bytes(data)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
