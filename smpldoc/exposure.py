"""Keep an accidental exposure harmless. Two checks:
1. Before binding: refuse a non-loopback bind if any protected route has no authentication.
2. After starting: call every protected route with no credentials and fail if any answers."""
import ipaddress
import urllib.error
import urllib.request


class ExposureError(Exception):
    pass


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def probe_host(bind: str) -> str:
    return "127.0.0.1" if bind in ("0.0.0.0", "::", "") else bind


def check_exposure(bind, routes, auth_configured):
    protected = [r.path for r in routes if not r.public]
    if protected and not auth_configured and not is_loopback(bind):
        raise ExposureError(
            f"refusing to bind {bind}: {', '.join(protected)} need authentication and none is configured. "
            "Bind to 127.0.0.1 or configure sign-in first.")


def self_check(base_url, routes):
    for route in routes:
        if route.public:
            continue
        try:
            with urllib.request.urlopen(base_url + route.path, timeout=5) as resp:
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        except OSError as e:
            raise ExposureError(f"self-check could not reach {route.path}: {type(e).__name__}") from None
        if status not in (401, 403):
            raise ExposureError(f"{route.path} answered {status} to an anonymous request")
