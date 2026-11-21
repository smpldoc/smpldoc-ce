"""AWS Signature Version 4 for S3 requests, on the standard library only.
Checked against AWS's documented examples (tests/test_sigv4.py) and against botocore."""
import hashlib
import hmac
from datetime import datetime, timezone
from urllib.parse import parse_qsl, quote, unquote, urlparse

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
ALGORITHM = "AWS4-HMAC-SHA256"


def _enc(value: str) -> str:
    return quote(value, safe="-_.~")


def canonical_query(query: str) -> str:
    pairs = sorted((_enc(k), _enc(v)) for k, v in parse_qsl(query, keep_blank_values=True))
    return "&".join(f"{k}={v}" for k, v in pairs)


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def sign(method, url, headers, payload_hash, *, access_key, secret_key, region, token=None, now=None, service="s3"):
    """Return the request headers to send: the ones given, plus x-amz-date, x-amz-content-sha256,
    x-amz-security-token (if any) and Authorization. `host` is signed but left for the HTTP client to send."""
    now = now or datetime.now(timezone.utc)
    amz_date, date = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    u = urlparse(url)
    out = dict(headers)
    out["x-amz-date"], out["x-amz-content-sha256"] = amz_date, payload_hash
    if token:
        out["x-amz-security-token"] = token

    to_sign = {"host": u.netloc.lower(), **{k.lower(): " ".join(str(v).split()) for k, v in out.items()}}
    names = sorted(to_sign)
    canonical_headers = "".join(f"{n}:{to_sign[n]}\n" for n in names)
    signed = ";".join(names)
    path = quote(unquote(u.path or "/"), safe="/-_.~")
    canonical = "\n".join([method, path, canonical_query(u.query), canonical_headers, signed, payload_hash])

    scope = f"{date}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([ALGORITHM, amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    key = _hmac(_hmac(_hmac(_hmac(("AWS4" + secret_key).encode(), date), region), service), "aws4_request")
    signature = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    out["Authorization"] = f"{ALGORITHM} Credential={access_key}/{scope}, SignedHeaders={signed}, Signature={signature}"
    return out
