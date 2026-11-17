"""Settings come from environment variables only. Unknown SMPLDOC_* names are an error, so a typo
cannot silently leave a safe default in place. Secrets can be read from a file (the *_FILE form),
and are never printed."""
from dataclasses import dataclass, field
from typing import Mapping, Optional

from smpldoc.adapters.relay_pull import validate_url

KNOWN = {"SMPLDOC_DATA_DIR", "SMPLDOC_RELAY_URL", "SMPLDOC_RELAY_TOKEN", "SMPLDOC_RELAY_TOKEN_FILE",
         "SMPLDOC_POLL_SECONDS", "SMPLDOC_BATCH", "SMPLDOC_BIND", "SMPLDOC_PORT"}


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


def _token(env):
    direct, path = env.get("SMPLDOC_RELAY_TOKEN"), env.get("SMPLDOC_RELAY_TOKEN_FILE")
    if direct and path:
        raise ConfigError("set SMPLDOC_RELAY_TOKEN or SMPLDOC_RELAY_TOKEN_FILE, not both")
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                direct = f.read().strip()
        except OSError:
            raise ConfigError("SMPLDOC_RELAY_TOKEN_FILE could not be read") from None
        if not direct:
            raise ConfigError("SMPLDOC_RELAY_TOKEN_FILE is empty")
    return direct or None


def load(env: Mapping[str, str], need_relay: bool = True) -> Config:
    unknown = sorted(k for k in env if k.startswith("SMPLDOC_") and k not in KNOWN)
    if unknown:
        raise ConfigError(f"unknown setting(s): {', '.join(unknown)}")
    bind = env.get("SMPLDOC_BIND", "127.0.0.1")
    if not bind.strip():
        raise ConfigError("SMPLDOC_BIND must not be empty")
    url, token = env.get("SMPLDOC_RELAY_URL") or None, _token(env)
    if need_relay and not (url and token):
        raise ConfigError("SMPLDOC_RELAY_URL and a relay token are required")
    if url:
        try:
            validate_url(url)
        except ValueError as e:
            raise ConfigError(str(e)) from None
    return Config(
        data_dir=env.get("SMPLDOC_DATA_DIR", "/data"), relay_url=url, relay_token=token,
        poll_seconds=_number(env, "SMPLDOC_POLL_SECONDS", 30.0, 1, 3600, float),
        batch=_number(env, "SMPLDOC_BATCH", 10, 1, 100, int),
        bind=bind, port=_number(env, "SMPLDOC_PORT", 8080, 1, 65535, int))
