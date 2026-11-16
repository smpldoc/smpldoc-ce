"""A local stand-in for the hosted relay (docs/RELAY_PROTOCOL.md). Test use only."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse


class FakeRelay:
    def __init__(self, token="tok", redirect_to=None, raw_pad=0):
        self.token, self.redirect_to, self.raw_pad = token, redirect_to, raw_pad
        self.queue, self.inflight, self.seen = [], {}, []
        self._n = 0
        relay = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _auth(self):
                relay.seen.append((self.command, self.path, self.headers.get("Authorization")))
                if self.headers.get("Authorization") != f"Bearer {relay.token}":
                    self.send_response(401); self.end_headers(); return False
                return True

            def _send(self, code, body=b"", ctype="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if not self._auth():
                    return
                u = urlparse(self.path)
                if relay.redirect_to:
                    self.send_response(302); self.send_header("Location", relay.redirect_to); self.end_headers(); return
                if u.path == "/v1/messages":
                    limit = int(parse_qs(u.query).get("limit", ["10"])[0])
                    out = []
                    while relay.queue and len(out) < limit:
                        m = relay.queue.pop(0)
                        relay.inflight[m["receipt"]] = m
                        out.append({k: m[k] for k in ("id", "receipt", "sender", "recipient", "verdict", "size")})
                    return self._send(200, json.dumps({"messages": out}).encode())
                if u.path.startswith("/v1/messages/") and u.path.endswith("/raw"):
                    receipt = unquote(u.path[len("/v1/messages/"):-len("/raw")])
                    m = relay.inflight.get(receipt)
                    if not m:
                        return self._send(404)
                    return self._send(200, m["raw"] + b"\0" * relay.raw_pad, "message/rfc822")
                self._send(404)

            def do_POST(self):
                if not self._auth():
                    return
                parts = urlparse(self.path).path.split("/")  # '', v1, messages, <receipt>, ack|nack
                if len(parts) == 5 and parts[1] == "v1" and parts[2] == "messages":
                    receipt = unquote(parts[3])
                    m = relay.inflight.pop(receipt, None)
                    if m is None:
                        return self._send(404)
                    if parts[4] == "nack":
                        relay.queue.insert(0, m)
                    return self._send(204)
                self._send(404)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def deliver(self, raw, sender, recipient, verdict):
        self._n += 1
        self.queue.append({"id": f"m{self._n}", "receipt": f"r{self._n}/x y", "sender": sender,
                           "recipient": recipient, "verdict": verdict, "size": len(raw), "raw": raw})

    def close(self):
        self.server.shutdown()
        self.server.server_close()
