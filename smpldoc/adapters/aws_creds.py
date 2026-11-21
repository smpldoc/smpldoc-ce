"""Where the container gets AWS credentials. Prefer a platform role over long-lived keys:
1. AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY (+ AWS_SESSION_TOKEN): for local trials and S3-compatible servers.
2. An ECS task role (AWS_CONTAINER_CREDENTIALS_RELATIVE_URI), read from the fixed ECS address.
3. An EC2 instance role through IMDSv2 (a token first, never the older unauthenticated call).
The two metadata addresses are fixed link-local constants, never taken from settings, redirects are
not followed, and nothing here is ever logged."""
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

REFRESH_BEFORE = timedelta(minutes=5)
ECS_PATH = re.compile(r"^/[A-Za-z0-9._~/-]*$")


class CredentialError(Exception):
    pass


@dataclass(frozen=True)
class Credentials:
    access_key: str
    secret_key: str = field(repr=False)
    token: Optional[str] = field(default=None, repr=False)
    expires: Optional[datetime] = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class CredentialProvider:
    def __init__(self, env, *, ecs_base="http://169.254.170.2", imds_base="http://169.254.169.254", now=None, timeout=2):
        self.env, self.ecs_base, self.imds_base, self.timeout = env, ecs_base, imds_base, timeout
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._opener = urllib.request.build_opener(_NoRedirect)
        self._cached = None

    def get(self) -> Credentials:
        c = self._cached
        if c is None or (c.expires is not None and c.expires - self._now() < REFRESH_BEFORE):
            c = self._cached = self._load()
        return c

    # -- sources ---------------------------------------------------------------------
    def _load(self) -> Credentials:
        key, secret = self.env.get("AWS_ACCESS_KEY_ID"), self.env.get("AWS_SECRET_ACCESS_KEY")
        if key or secret:
            if not (key and secret):
                raise CredentialError("set both AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, or neither")
            return Credentials(key, secret, self.env.get("AWS_SESSION_TOKEN") or None, None)
        uri = self.env.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
        if uri:
            if not ECS_PATH.match(uri) or uri.startswith("//") or ".." in uri.split("/"):
                raise CredentialError("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI is not a plain path")
            return self._parse(self._call("GET", self.ecs_base + uri))
        try:
            token = self._call("PUT", self.imds_base + "/latest/api/token", {"X-aws-ec2-metadata-token-ttl-seconds": "21600"}).decode()
            hdr = {"X-aws-ec2-metadata-token": token}
            role = self._call("GET", self.imds_base + "/latest/meta-data/iam/security-credentials/", hdr).decode().split()[0]
            return self._parse(self._call("GET", self.imds_base + "/latest/meta-data/iam/security-credentials/" + role, hdr))
        except (CredentialError, IndexError):
            raise CredentialError("no AWS credentials: set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, or run with an ECS task role or an EC2 instance role") from None

    def _call(self, method, url, headers=None) -> bytes:
        req = urllib.request.Request(url, method=method, headers=headers or {}, data=b"" if method == "PUT" else None)
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return resp.read(100_000)
        except (urllib.error.URLError, OSError, TimeoutError):
            raise CredentialError("the credentials service did not answer") from None

    @staticmethod
    def _parse(body: bytes) -> Credentials:
        try:
            d = json.loads(body)
            exp = datetime.strptime(d["Expiration"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if d.get("Expiration") else None
            return Credentials(d["AccessKeyId"], d["SecretAccessKey"], d.get("Token") or None, exp)
        except (ValueError, KeyError, TypeError):
            raise CredentialError("the credentials service sent something unreadable") from None
