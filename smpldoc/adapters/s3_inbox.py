"""MailIn adapter for mail that Amazon SES writes into an S3 bucket. The container reads the bucket;
no inbound port is needed. Object keys are `<prefix><mailbox>/<id>` (one SES receipt rule per mailbox,
or one rule plus `default_slug`). Acknowledged mail moves to `processed/` (a lifecycle rule expires it),
anything unroutable or too large moves to `quarantine/`, nothing is ever deleted outright.

Trust: the verdict comes only from the TOPMOST Authentication-Results header, and only if its
authserv-id is SES's (`amazonses.com`). SES prepends its own, so a header the sender wrote lower down,
or one naming another server, is ignored."""
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from email.parser import BytesParser
from email.utils import parseaddr
from urllib.parse import quote, urlparse

from smpldoc.adapters.sigv4 import EMPTY_SHA256, sign
from smpldoc.domain.models import Inbound

LOOPBACK = {"127.0.0.1", "localhost", "[::1]", "::1"}
HEADER_BYTES = 32 * 1024
PREFIX = re.compile(r"^(?:[A-Za-z0-9._-]+/)+$")


class S3Error(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def endpoint_for(bucket: str, region: str) -> str:
    """Virtual-hosted style, except for dotted bucket names (their TLS name would not match)."""
    return f"https://s3.{region}.amazonaws.com/{bucket}" if "." in bucket else f"https://{bucket}.s3.{region}.amazonaws.com"


def _check_prefix(p: str) -> str:
    if not PREFIX.match(p) or any(s in (".", "..") for s in p.split("/")):
        raise ValueError(f"{p!r} must look like 'folder/' or 'a/b/'")
    return p


def _verdict(auth_header, authserv_id: str) -> str:
    if not auth_header or not re.match(rf"^\s*{re.escape(authserv_id)}\s*;", auth_header, re.IGNORECASE):
        return "unknown"
    if re.search(r"(?:^|[\s;])(?:dkim|spf)=pass\b", auth_header, re.IGNORECASE):
        return "pass"
    if re.search(r"(?:^|[\s;])(?:dkim|spf)=(?:fail|softfail)\b", auth_header, re.IGNORECASE):
        return "fail"
    return "unknown"


class S3Inbox:
    def __init__(self, bucket, region, credentials, *, endpoint=None, prefix="inbox/", processed_prefix="processed/",
                 quarantine_prefix="quarantine/", domain="mail.invalid", default_slug=None, authserv_id="amazonses.com",
                 max_bytes=25_000_000, timeout=30, lease_seconds=300, now=None):
        if endpoint:
            u = urlparse(endpoint)
            if u.scheme != "https" and not (u.scheme == "http" and u.hostname in LOOPBACK):
                raise ValueError("the S3 endpoint must be https (plain http only on loopback)")
            self.base = endpoint.rstrip("/") + "/" + bucket  # S3-compatible servers: path style
        else:
            self.base = endpoint_for(bucket, region)
        self.bucket, self.region, self.credentials = bucket, region, credentials
        self.prefix, self.processed, self.quarantine = _check_prefix(prefix), _check_prefix(processed_prefix), _check_prefix(quarantine_prefix)
        self.domain, self.default_slug, self.authserv_id = domain, default_slug, authserv_id
        self.max_bytes, self.timeout, self.lease = max_bytes, timeout, lease_seconds
        self._now = now or time.monotonic
        self._inflight: dict[str, float] = {}
        self._opener = urllib.request.build_opener(_NoRedirect)

    # -- HTTP --------------------------------------------------------------------------
    def _url(self, key="", query=""):
        return f"{self.base}/{quote(key, safe='/-_.~')}" + (f"?{query}" if query else "")

    def _request(self, method, url, headers=None, limit=None):
        c = self.credentials.get()
        signed = sign(method, url, headers or {}, EMPTY_SHA256, access_key=c.access_key, secret_key=c.secret_key, region=self.region, token=c.token)
        req = urllib.request.Request(url, method=method, headers=signed, data=b"" if method == "PUT" else None)
        cap = limit if limit is not None else self.max_bytes
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                body = resp.read(cap + 1)
        except urllib.error.HTTPError as e:
            e.close()
            if e.code == 403:
                raise S3Error("S3 refused the credentials (403)") from None
            raise S3Error(f"S3 answered {e.code}") from None
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise S3Error(f"S3 unreachable: {type(e).__name__}") from None
        if len(body) > cap:
            raise S3Error("S3 answer is larger than the allowed size")
        return body

    # -- listing and headers -------------------------------------------------------------
    def _list(self):
        body = self._request("GET", self._url("", f"list-type=2&max-keys=1000&prefix={quote(self.prefix, safe='')}"), limit=5_000_000)
        if re.search(rb"<!DOCTYPE|<!ENTITY", body, re.IGNORECASE):
            raise S3Error("S3 sent a listing with entity declarations; refusing it")
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            raise S3Error("S3 sent an unreadable listing") from None
        out = []
        for el in root.iter():
            if el.tag.endswith("Contents"):
                key = next((c.text for c in el if c.tag.endswith("Key")), None)
                size = next((c.text for c in el if c.tag.endswith("Size")), "0")
                if key and size.isdigit():
                    out.append((key, int(size)))
        return out

    def _headers_of(self, key):
        head = self._request("GET", self._url(key), {"Range": f"bytes=0-{HEADER_BYTES - 1}"}, limit=HEADER_BYTES)
        msg = BytesParser().parsebytes(head, headersonly=True)
        auth = msg.get_all("Authentication-Results") or []
        sender = " ".join(str(msg.get("Return-Path") or "").split()).strip("<> ") or parseaddr(str(msg.get("From") or ""))[1]
        return _verdict(" ".join(str(auth[0]).split()) if auth else None, self.authserv_id), sender

    def _move(self, key, to_prefix):
        dest = to_prefix + key[len(self.prefix):]
        self._request("PUT", self._url(dest), {"x-amz-copy-source": quote(f"/{self.bucket}/{key}", safe="/-_.~")}, limit=100_000)
        self._request("DELETE", self._url(key), limit=100_000)

    # -- MailIn --------------------------------------------------------------------------
    def poll(self, limit):
        now = self._now()
        self._inflight = {k: t for k, t in self._inflight.items() if t > now}
        out = []
        for key, size in self._list():
            if key == self.prefix or key.endswith("/") or key in self._inflight:
                continue
            parts = key[len(self.prefix):].split("/")
            slug = parts[0] if len(parts) > 1 else self.default_slug
            if not slug or size > self.max_bytes:
                self._move(key, self.quarantine)  # never handed out, never deleted
                continue
            if len(out) >= limit:
                continue
            verdict, sender = self._headers_of(key)
            self._inflight[key] = now + self.lease
            out.append(Inbound(key, key, sender, f"{slug}@{self.domain}", verdict, size))
        return out

    def fetch(self, message):
        return self._request("GET", self._url(message.id))

    def ack(self, message):
        self._inflight.pop(message.receipt, None)
        self._move(message.id, self.processed)

    def nack(self, message):
        self._inflight.pop(message.receipt, None)
