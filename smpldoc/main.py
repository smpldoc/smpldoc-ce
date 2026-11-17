"""Entry point: `python -m smpldoc [run | check-config | add-company SLUG NAME]`.
Exit codes: 0 ok, 1 command failed, 2 bad usage or settings, 3 refused to start (exposure)."""
import json
import os
import re
import signal
import sys
import threading
from datetime import datetime, timezone

from smpldoc.adapters.fs_blob import FileBlob
from smpldoc.adapters.plain_text import PlainTextExtractor
from smpldoc.adapters.relay_pull import RelayError, RelayPull
from smpldoc.adapters.sqlite_store import SqliteStore
from smpldoc.config import ConfigError, load
from smpldoc.domain.runner import Runner
from smpldoc.exposure import ExposureError, check_exposure, probe_host, self_check
from smpldoc.http_server import Heartbeat, build_server, default_routes

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
COUNTS = ("completed", "failed", "held", "skipped", "rejected", "deferred")


def run_loop(runner, beat, poll_seconds, wait, log):
    """Run cycles until `wait(seconds)` says stop. A crash (BaseException) is never swallowed."""
    errors = 0
    while True:
        try:
            summary = runner.run_once()
        except RelayError as exc:
            errors += 1
            log({"event": "relay_error", "error": type(exc).__name__})
        except Exception as exc:  # the message may hold document text: log the class only
            errors += 1
            log({"event": "cycle_error", "error": type(exc).__name__})
        else:
            errors = 0
            beat.beat()
            log({"event": "cycle", **{k: getattr(summary, k) for k in COUNTS}})
        if wait(poll_seconds * min(2 ** errors, 8) if errors else poll_seconds):
            return


def _open(config):
    os.makedirs(config.data_dir, mode=0o700, exist_ok=True)
    return SqliteStore(os.path.join(config.data_dir, "smpldoc.db"))


def main(argv, env=None, *, out=None, err=None, stop=None, extra_routes=()):
    env = os.environ if env is None else env
    out, err = out or sys.stdout, err or sys.stderr
    stop = stop or threading.Event()
    command, args = (argv[0], argv[1:]) if argv else ("run", [])

    def log(fields):
        err.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **fields}) + "\n")
        err.flush()

    try:
        if command == "add-company":
            if len(args) != 2 or not SLUG.match(args[0]):
                print("usage: add-company SLUG NAME   (slug: lowercase letters, digits, dashes)", file=err)
                return 1
            store = _open(load(env, need_relay=False))
            try:
                store.add_company(args[0], args[1])
            except ValueError as e:
                print(str(e), file=err)
                return 1
            finally:
                store.close()
            print(f"added {args[0]}", file=out)
            return 0
        if command == "check-config":
            c = load(env)
            print(f"config ok: relay={c.relay_url} bind={c.bind}:{c.port} data={c.data_dir}", file=out)
            return 0
        if command != "run":
            print("usage: python -m smpldoc [run | check-config | add-company SLUG NAME]", file=err)
            return 2
        config = load(env)
    except ConfigError as e:
        print(f"config error: {e}", file=err)
        return 2

    beat = Heartbeat()
    routes = default_routes(beat, max_age=max(120, config.poll_seconds * 10)) + list(extra_routes)
    try:
        check_exposure(config.bind, routes, auth_configured=False)  # sign-in does not exist yet
    except ExposureError as e:
        print(f"Refusing to start: {e}", file=err)
        return 3

    store = _open(config)
    runner = Runner(RelayPull(config.relay_url, config.relay_token), store, FileBlob(os.path.join(config.data_dir, "blobs")),
                    PlainTextExtractor(), batch=config.batch)
    server = build_server(config.bind, config.port, routes)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        try:
            self_check(f"http://{probe_host(config.bind)}:{server.server_address[1]}", routes)
        except ExposureError as e:
            print(f"Refusing to start: {e}", file=err)
            return 3
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, lambda *_: stop.set())
        log({"event": "started", "bind": config.bind, "port": config.port})
        run_loop(runner, beat, config.poll_seconds, stop.wait, log)
        log({"event": "stopped"})
        return 0
    finally:
        server.shutdown()
        server.server_close()
        store.close()
