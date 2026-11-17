"""MailIn adapter that pulls from a relay (docs/RELAY_PROTOCOL.md). Outbound only: the container
opens no inbound port for mail. The one network service it talks to is the relay the operator
configured, and the token is sent only there, never to a redirect target."""
import json
import urllib.error
import urllib.request
from urllib.parse import quote, urlparse

from smpldoc.domain.models import Inbound, VERDICTS

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class RelayError(Exception):
    pass


class RelayAuthError(RelayError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class RelayPull:
    def __init__(self, base_url, token, *, timeout=30, max_bytes=25_000_000, lease_seconds=300):
        u = urlparse(base_url)
        if not token:
            raise ValueError("a relay token is required")
        if u.scheme != "https" and not (u.scheme == "http" and u.hostname in LOOPBACK):
            raise ValueError("the relay URL must be https (plain http only on loopback)")
        self.base, self.token = base_url.rstrip("/"), token
        self.timeout, self.max_bytes, self.lease = timeout, max_bytes, lease_seconds
        self._opener = urllib.request.build_opener(_NoRedirect)

    def _call(self, method, path, limit=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     headers={"Authorization": f"Bearer {self.token}"})
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                body = resp.read((limit or 1_000_000) + 1)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise RelayAuthError("the relay refused the token") from None
            raise RelayError(f"relay answered {e.code}") from None
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise RelayError(f"relay unreachable: {type(e).__name__}") from None
        if len(body) > (limit or 1_000_000):
            raise RelayError("relay response is larger than the allowed size")
        return body

    def poll(self, limit):
        limit = max(1, min(int(limit), 100))
        body = self._call("GET", f"/v1/messages?limit={limit}&lease={self.lease}")
        try:
            items = json.loads(body)["messages"]
            return [Inbound(str(i["id"]), str(i["receipt"]), str(i["sender"]), str(i["recipient"]),
                            i["verdict"] if i["verdict"] in VERDICTS else "unknown", int(i["size"]))
                    for i in items]
        except (ValueError, KeyError, TypeError):
            raise RelayError("the relay sent a malformed message list") from None

    def fetch(self, message):
        return self._call("GET", f"/v1/messages/{quote(message.receipt, safe='')}/raw", self.max_bytes)

    def ack(self, message):
        self._call("POST", f"/v1/messages/{quote(message.receipt, safe='')}/ack")

    def nack(self, message):
        self._call("POST", f"/v1/messages/{quote(message.receipt, safe='')}/nack")
