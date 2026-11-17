import io
import json
import os
import socket
import stat
import tempfile
import threading
import time
import unittest

from smpldoc.adapters.relay_pull import RelayError
from smpldoc.adapters.sqlite_store import SqliteStore
from smpldoc.http_server import Heartbeat
from smpldoc.main import main, run_loop
from tests.fake_relay import FakeRelay
from tests.test_runner import mail


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Summary:
    completed = failed = held = skipped = rejected = deferred = 0


class LoopTest(unittest.TestCase):
    def loop(self, runner, waits_before_stop=3):
        beat, logs, waited = Heartbeat(), [], []

        def wait(seconds):
            waited.append(seconds)
            return len(waited) >= waits_before_stop

        run_loop(runner, beat, 30, wait, logs.append)
        return beat, logs, waited

    def test_runs_repeatedly_beats_and_stops_when_told(self):
        class R:
            calls = 0
            def run_once(self):
                R.calls += 1
                s = Summary()
                s.completed = 1
                return s
        beat, logs, waited = self.loop(R())
        self.assertEqual(R.calls, 3)
        self.assertEqual(waited, [30, 30, 30])
        self.assertTrue(beat.fresh(60))
        self.assertEqual([l["event"] for l in logs], ["cycle"] * 3)
        self.assertEqual(logs[0]["completed"], 1)

    def test_relay_errors_back_off_and_never_leak_the_message(self):
        class R:
            def run_once(self):
                raise RelayError("secret relay detail")
        beat, logs, waited = self.loop(R(), waits_before_stop=5)
        self.assertEqual(waited, [60, 120, 240, 240, 240])
        self.assertTrue(all(l["event"] == "relay_error" for l in logs))
        self.assertNotIn("secret", json.dumps(logs))

    def test_unexpected_errors_are_logged_by_class_only_and_do_not_stop_the_loop(self):
        class R:
            def run_once(self):
                raise ValueError("document text")
        _, logs, waited = self.loop(R())
        self.assertEqual(len(waited), 3)
        self.assertEqual(logs[0], {"event": "cycle_error", "error": "ValueError"})

    def test_a_crash_is_not_swallowed(self):
        class Crash(BaseException):
            pass
        class R:
            def run_once(self):
                raise Crash()
        with self.assertRaises(Crash):
            self.loop(R())


class CliTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.addCleanup(self._d.cleanup)
        self.data = os.path.join(self._d.name, "data")
        self.env = {"SMPLDOC_DATA_DIR": self.data}

    def run_cli(self, *argv, env=None):
        out, err = io.StringIO(), io.StringIO()
        code = main(list(argv), env if env is not None else self.env, out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def test_add_company_creates_a_private_data_dir(self):
        code, out, _ = self.run_cli("add-company", "acme", "Acme Inc")
        self.assertEqual(code, 0)
        self.assertEqual(stat.S_IMODE(os.stat(self.data).st_mode), 0o700)
        store = SqliteStore(os.path.join(self.data, "smpldoc.db"))
        self.addCleanup(store.close)
        self.assertIsNotNone(store.find_company_by_slug("acme"))

    def test_add_company_rejects_bad_and_duplicate_slugs(self):
        for bad in ("Acme", "a b", "../x", "", "a" * 64, "-x"):
            self.assertEqual(self.run_cli("add-company", bad, "N")[0], 1, bad)
        self.assertEqual(self.run_cli("add-company", "acme", "A")[0], 0)
        self.assertEqual(self.run_cli("add-company", "acme", "A")[0], 1)

    def test_check_config_reports_without_printing_the_token(self):
        env = {**self.env, "SMPLDOC_RELAY_URL": "https://relay.example.com", "SMPLDOC_RELAY_TOKEN": "s3cret-token"}
        code, out, err = self.run_cli("check-config", env=env)
        self.assertEqual(code, 0)
        self.assertNotIn("s3cret-token", out + err)

    def test_bad_config_exits_2(self):
        self.assertEqual(self.run_cli("run")[0], 2)  # no relay configured
        self.assertEqual(self.run_cli("nonsense")[0], 2)

    def test_public_bind_with_a_protected_route_refuses_to_start(self):
        env = {**self.env, "SMPLDOC_RELAY_URL": "http://127.0.0.1:9", "SMPLDOC_RELAY_TOKEN": "t", "SMPLDOC_BIND": "0.0.0.0"}
        from smpldoc.exposure import ExposureError
        from smpldoc.http_server import Route
        out, err = io.StringIO(), io.StringIO()
        code = main(["run"], env, out=out, err=err, extra_routes=[Route("/jobs", lambda r: (200, {}), public=False)])
        self.assertEqual(code, 3)
        self.assertIn("refusing", err.getvalue().lower())


class EndToEndTest(unittest.TestCase):
    def test_run_pulls_mail_processes_it_and_serves_health(self):
        relay = FakeRelay()
        self.addCleanup(relay.close)
        with tempfile.TemporaryDirectory() as d:
            data, port = os.path.join(d, "data"), free_port()
            env = {"SMPLDOC_DATA_DIR": data, "SMPLDOC_RELAY_URL": relay.url, "SMPLDOC_RELAY_TOKEN": "tok",
                   "SMPLDOC_POLL_SECONDS": "1", "SMPLDOC_PORT": str(port)}
            self.assertEqual(main(["add-company", "acme", "Acme"], env, out=io.StringIO(), err=io.StringIO()), 0)
            relay.deliver(mail(), "s@x.test", "acme@in.test", "pass")
            stop, result, err = threading.Event(), [], io.StringIO()
            t = threading.Thread(target=lambda: result.append(main(["run"], env, out=io.StringIO(), err=err, stop=stop)))
            t.start()
            try:
                store = SqliteStore(os.path.join(data, "smpldoc.db"))
                company = store.find_company_by_slug("acme")
                deadline = time.time() + 20
                while time.time() < deadline and not [j for j in store.list_jobs(company.id) if j.status == "done"]:
                    time.sleep(0.1)
                self.assertEqual([j.status for j in store.list_jobs(company.id)], ["done"])
                import urllib.request
                self.assertEqual(urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5).status, 200)
                self.assertEqual(urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz", timeout=5).status, 200)
                store.close()
            finally:
                stop.set()
                t.join(15)
            self.assertEqual(result, [0])
            self.assertNotIn("tok", err.getvalue())
            self.assertNotIn("Invoice", err.getvalue())  # no document text in logs


if __name__ == "__main__":
    unittest.main()
