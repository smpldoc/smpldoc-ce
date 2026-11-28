"""Entry point: `python -m smpldoc [run | check-config | bundle-validate FOLDER | add-company SLUG NAME | jobs COMPANY | job COMPANY JOB_ID]`.
Exit codes: 0 ok, 1 command failed, 2 bad usage or settings, 3 refused to start (exposure)."""
import json
import os
import re
import signal
import sys
import threading
from datetime import datetime, timezone

from smpldoc.adapters.fs_blob import FileBlob
from smpldoc.adapters.fs_bundle_store import FileBundleStore
from smpldoc.adapters.fs_bundle import BundleReadError, read_bundle_dir
from smpldoc.adapters.plain_text import PlainTextExtractor
from smpldoc.adapters.rules_guard import GuardedEvaluator
from smpldoc.cli_admin import COMMANDS as ADMIN_COMMANDS, clean, run_admin
from smpldoc.adapters.relay_pull import RelayError
from smpldoc.adapters.sqlite_store import SqliteStore
from smpldoc.config import ConfigError, load
from smpldoc.domain import bundle
from smpldoc.domain.runner import Runner
from smpldoc.exposure import ExposureError, check_exposure, probe_host, self_check
from smpldoc.http_server import Heartbeat, build_server, default_routes
from smpldoc.mail_source import build_mail_in, build_mail_out

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_clean = clean
COUNTS = ("completed", "failed", "held", "skipped", "rejected", "deferred", "delivered", "delivery_failed")


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
            log({"event": "cycle", **{k: getattr(summary, k, 0) for k in COUNTS}})
        if wait(poll_seconds * min(2 ** errors, 8) if errors else poll_seconds):
            return


def _open(config):
    os.makedirs(config.data_dir, mode=0o700, exist_ok=True)
    return SqliteStore(os.path.join(config.data_dir, "smpldoc.db"))


def _bundle_validate(args, out, err) -> int:
    if len(args) != 1:
        print("usage: bundle-validate FOLDER", file=err)
        return 2
    try:
        files = read_bundle_dir(args[0])
    except BundleReadError as e:
        print(_clean(str(e)), file=err)
        return 1
    problems = bundle.validate(files)
    for problem in problems:
        print(_clean(problem), file=err)
    if problems:
        return 1
    kind = json.loads(files["fields.json"])["kind"]
    print(f"bundle ok: {bundle.FORMAT} {json.loads(files['manifest.json'])['version']}, {kind}", file=out)
    return 0


def main(argv, env=None, *, out=None, err=None, stop=None, extra_routes=()):
    env = os.environ if env is None else env
    out, err = out or sys.stdout, err or sys.stderr
    stop = stop or threading.Event()
    command, args = (argv[0], argv[1:]) if argv else ("run", [])

    def log(fields):
        err.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **fields}) + "\n")
        err.flush()

    if command == "bundle-validate":
        return _bundle_validate(args, out, err)

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
        if command in ADMIN_COMMANDS:
            store = _open(load(env, need_relay=False))
            try:
                return run_admin(command, args, store, out, err)
            finally:
                store.close()
        if command in ("jobs", "job"):
            need = 1 if command == "jobs" else 2
            if len(args) != need:
                print("usage: jobs COMPANY   |   job COMPANY JOB_ID", file=err)
                return 1
            store = _open(load(env, need_relay=False))
            try:
                company = store.find_company_by_slug(args[0])
                if company is None:
                    print(f"no company {_clean(args[0], 63)!r}", file=err)
                    return 1
                if command == "jobs":
                    for j in store.list_jobs(company.id):
                        print(f"{j.id}  {j.status:<10}  {j.created_at[:19]}  {_clean(j.subject, 60)}" + (f"  [{_clean(j.error, 40)}]" if j.error else "")
                              + ("  [needs review]" if j.rule_conflict else "") + (f"  [forward queued: {_clean(j.forward_target, 41)}]" if j.forward_target else ""), file=out)
                    return 0
                job = store.get_job(company.id, args[1])
                if job is None:
                    print("no such job", file=err)
                    return 1
                print(f"job {job.id}  status {job.status}  from {_clean(job.sender, 80)}  subject {_clean(job.subject, 80)}", file=out)
                for d in store.list_documents(company.id, job.id):
                    print(f"  document {_clean(d.filename, 80)} ({d.content_type}, {d.size} bytes)", file=out)
                for v in store.list_field_values(company.id, job.id):
                    print(f"  value {_clean(v.name, 60)}: {_clean(v.value)}", file=out)
                for e in store.list_events(company.id, job.id):
                    print(f"  step {e.at[:19]} {e.step} {e.outcome} attempt {e.attempt}" + (f" ({_clean(e.detail, 60)})" if e.detail else ""), file=out)
                return 0
            finally:
                store.close()
        if command == "check-config":
            c = load(env)
            print(f"config ok: mail={c.mail_source} bind={c.bind}:{c.port} data={c.data_dir}", file=out)
            return 0
        if command != "run":
            print("usage: python -m smpldoc [run | check-config | bundle-validate FOLDER | add-company SLUG NAME | jobs COMPANY | job COMPANY JOB_ID | rules | targets | job-action ...]  (see docs/ROUTING.md)", file=err)
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
    runner = Runner(build_mail_in(config, env), store, FileBlob(os.path.join(config.data_dir, "blobs")),
                    PlainTextExtractor(), batch=config.batch,
                    bundles=FileBundleStore(os.path.join(config.data_dir, "bundles")),
                    mail_out=build_mail_out(config), evaluate=GuardedEvaluator(), max_forward_bytes=config.max_forward_bytes)
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
