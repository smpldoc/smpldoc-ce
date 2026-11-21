"""Settings come from environment variables only. Unknown SMPLDOC_* names are an error, so a typo
cannot silently leave a safe default in place. Secrets can be read from a file (the *_FILE form),
and are never printed."""
import re
from dataclasses import dataclass, field
from typing import Mapping, Optional

from smpldoc.adapters.relay_pull import validate_url
from smpldoc.domain.deliver import valid_address

KNOWN = {"SMPLDOC_DATA_DIR", "SMPLDOC_RELAY_URL", "SMPLDOC_RELAY_TOKEN", "SMPLDOC_RELAY_TOKEN_FILE",
         "SMPLDOC_POLL_SECONDS", "SMPLDOC_BATCH", "SMPLDOC_BIND", "SMPLDOC_PORT",
         "SMPLDOC_MAIL_SOURCE", "SMPLDOC_S3_BUCKET", "SMPLDOC_S3_REGION", "SMPLDOC_S3_PREFIX", "SMPLDOC_S3_ENDPOINT",
         "SMPLDOC_S3_AUTHSERV_ID", "SMPLDOC_MAIL_DOMAIN", "SMPLDOC_MAX_MESSAGE_BYTES",
         "SMPLDOC_SMTP_HOST", "SMPLDOC_SMTP_PORT", "SMPLDOC_SMTP_SECURITY", "SMPLDOC_SMTP_USER", "SMPLDOC_SMTP_PASSWORD",
         "SMPLDOC_SMTP_PASSWORD_FILE", "SMPLDOC_MAIL_FROM", "SMPLDOC_MAX_FORWARD_BYTES"}
SMTP_HOST = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
REGION = re.compile(r"^[a-z]{2}(?:-[a-z]+)+-\d$")
PREFIX = re.compile(r"^(?:[A-Za-z0-9._-]+/)+$")
DOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
AUTHSERV = re.compile(r"^[A-Za-z0-9.-]+$")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    data_dir: str
    relay_url: Optional[str]
    relay_token: Optional[str] = field(repr=False)
    poll_seconds: float
    batch: int
    bind: str
    port: int
    mail_source: Optional[str] = None
    s3_bucket: Optional[str] = None
    s3_region: Optional[str] = None
    s3_prefix: str = "inbox/"
    s3_endpoint: Optional[str] = None
    s3_authserv_id: str = "amazonses.com"
    mail_domain: str = "mail.invalid"
    max_message_bytes: int = 25_000_000
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_security: str = "starttls"
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = field(default=None, repr=False)
    mail_from: Optional[str] = None
    max_forward_bytes: int = 10_000_000


def _number(env, name, default, low, high, kind):
    raw = env.get(name)
    if raw is None:
        return default
    try:
        value = kind(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number") from None
    if not low <= value <= high:
        raise ConfigError(f"{name} must be between {low} and {high}")
    return value


def _secret(env, name):
    direct, path = env.get(name), env.get(name + "_FILE")
    if direct and path:
        raise ConfigError(f"set {name} or {name}_FILE, not both")
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                direct = f.read().strip()
        except OSError:
            raise ConfigError(f"{name}_FILE could not be read") from None
        if not direct:
            raise ConfigError(f"{name}_FILE is empty")
    return direct or None


def _token(env):
    return _secret(env, "SMPLDOC_RELAY_TOKEN")


def _checked(env, name, default, pattern, what):
    value = env.get(name, default)
    if value is not None and not pattern.match(value):
        raise ConfigError(f"{name} is not a valid {what}")
    return value


def load(env: Mapping[str, str], need_relay: bool = True) -> Config:
    """`need_relay` means "need a mail source" (the name is kept for older callers)."""
    unknown = sorted(k for k in env if k.startswith("SMPLDOC_") and k not in KNOWN)
    if unknown:
        raise ConfigError(f"unknown setting(s): {', '.join(unknown)}")
    bind = env.get("SMPLDOC_BIND", "127.0.0.1")
    if not bind.strip():
        raise ConfigError("SMPLDOC_BIND must not be empty")

    url, token = env.get("SMPLDOC_RELAY_URL") or None, _token(env)
    if url:
        try:
            validate_url(url)
        except ValueError as e:
            raise ConfigError(str(e)) from None
    bucket = _checked(env, "SMPLDOC_S3_BUCKET", None, BUCKET, "S3 bucket name")
    region = _checked(env, "SMPLDOC_S3_REGION", None, REGION, "AWS region")
    prefix = _checked(env, "SMPLDOC_S3_PREFIX", "inbox/", PREFIX, "folder like inbox/")
    if ".." in prefix.split("/"):
        raise ConfigError("SMPLDOC_S3_PREFIX must not contain '..'")
    endpoint = env.get("SMPLDOC_S3_ENDPOINT") or None
    if endpoint:
        try:
            validate_url(endpoint)
        except ValueError:
            raise ConfigError("SMPLDOC_S3_ENDPOINT must be https (plain http only on loopback)") from None

    explicit = env.get("SMPLDOC_MAIL_SOURCE")
    if explicit is not None and explicit not in ("relay", "s3"):
        raise ConfigError("SMPLDOC_MAIL_SOURCE must be relay or s3")
    has_relay, has_s3 = bool(url or token), bool(bucket)
    if explicit:
        source = explicit
    elif has_relay and has_s3:
        raise ConfigError("both relay and S3 settings are present: set SMPLDOC_MAIL_SOURCE to relay or s3")
    else:
        source = "relay" if has_relay else "s3" if has_s3 else None
    if need_relay:
        if source == "relay" and not (url and token):
            raise ConfigError("SMPLDOC_RELAY_URL and a relay token are required")
        if source == "s3" and not (bucket and region):
            raise ConfigError("SMPLDOC_S3_BUCKET and SMPLDOC_S3_REGION are required")
        if source is None:
            raise ConfigError("no mail source: set SMPLDOC_RELAY_URL and a token, or SMPLDOC_S3_BUCKET and SMPLDOC_S3_REGION")
    smtp_host = env.get("SMPLDOC_SMTP_HOST") or None
    smtp_user, smtp_password = env.get("SMPLDOC_SMTP_USER") or None, _secret(env, "SMPLDOC_SMTP_PASSWORD")
    security = env.get("SMPLDOC_SMTP_SECURITY", "starttls")
    mail_from = env.get("SMPLDOC_MAIL_FROM") or None
    if security not in ("starttls", "ssl", "none"):
        raise ConfigError("SMPLDOC_SMTP_SECURITY must be starttls, ssl or none")
    if smtp_host:
        if not SMTP_HOST.match(smtp_host):
            raise ConfigError("SMPLDOC_SMTP_HOST is not a valid host name")
        if not mail_from or not valid_address(mail_from):
            raise ConfigError("SMPLDOC_MAIL_FROM must be a valid sender address when SMPLDOC_SMTP_HOST is set")
        if security == "none" and smtp_host not in LOOPBACK:
            raise ConfigError("SMPLDOC_SMTP_SECURITY=none is only allowed for a server on this machine")
        if smtp_user and not smtp_password:
            raise ConfigError("SMPLDOC_SMTP_USER needs SMPLDOC_SMTP_PASSWORD or SMPLDOC_SMTP_PASSWORD_FILE")
    elif mail_from and not valid_address(mail_from):
        raise ConfigError("SMPLDOC_MAIL_FROM must be a valid sender address")
    return Config(
        data_dir=env.get("SMPLDOC_DATA_DIR", "/data"), relay_url=url, relay_token=token,
        poll_seconds=_number(env, "SMPLDOC_POLL_SECONDS", 30.0, 1, 3600, float),
        batch=_number(env, "SMPLDOC_BATCH", 10, 1, 100, int),
        bind=bind, port=_number(env, "SMPLDOC_PORT", 8080, 1, 65535, int),
        mail_source=source, s3_bucket=bucket, s3_region=region, s3_prefix=prefix, s3_endpoint=endpoint,
        s3_authserv_id=_checked(env, "SMPLDOC_S3_AUTHSERV_ID", "amazonses.com", AUTHSERV, "mail server name"),
        mail_domain=_checked(env, "SMPLDOC_MAIL_DOMAIN", "mail.invalid", DOMAIN, "domain name"),
        max_message_bytes=_number(env, "SMPLDOC_MAX_MESSAGE_BYTES", 25_000_000, 1, 100_000_000, int),
        smtp_host=smtp_host, smtp_port=_number(env, "SMPLDOC_SMTP_PORT", 587, 1, 65535, int), smtp_security=security,
        smtp_user=smtp_user, smtp_password=smtp_password, mail_from=mail_from,
        max_forward_bytes=_number(env, "SMPLDOC_MAX_FORWARD_BYTES", 10_000_000, 1, 100_000_000, int))
