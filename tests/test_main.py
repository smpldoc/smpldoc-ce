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
from smpldoc.domain.models import NewDocument, NewValue
from smpldoc.http_server import Heartbeat
from smpldoc.main import main, run_loop
from tests.fake_relay import FakeRelay
from tests.fake_smtp import FakeSmtp
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


class JobsCliTest(unittest.TestCase):
    """`jobs` and `job` are how an operator sees results until the portal exists."""

    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.addCleanup(self._d.cleanup)
        self.env = {"SMPLDOC_DATA_DIR": os.path.join(self._d.name, "data")}
        store = SqliteStore(os.path.join(self.env["SMPLDOC_DATA_DIR"], "smpldoc.db")) if os.makedirs(self.env["SMPLDOC_DATA_DIR"]) is None else None
        self.addCleanup(store.close)
        company = store.add_company("acme", "Acme")
        job, _ = store.create_job(company.id, "s1", "s@x.test", "Invoice March", "rk", "received",
                                  [NewDocument("body.txt", "text/plain", "k", 9)])
        doc = store.list_documents(company.id, job.id)[0]
        store.add_event(company.id, job.id, "ingest", "ok")
        store.complete_job(company.id, job.id, [NewValue(doc.id, "total", "9.50")])
        self.job = job

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        return main(list(argv), self.env, out=out, err=err), out.getvalue(), err.getvalue()

    def test_jobs_lists_each_job_with_its_status(self):
        code, out, _ = self.run_cli("jobs", "acme")
        self.assertEqual(code, 0)
        self.assertIn(self.job.id, out)
        self.assertIn("ready", out)
        self.assertIn("Invoice March", out)

    def test_job_shows_values_and_step_history(self):
        code, out, _ = self.run_cli("job", "acme", self.job.id)
        self.assertEqual(code, 0)
        self.assertIn("total", out)
        self.assertIn("9.50", out)
        self.assertIn("ingest", out)

    def test_unknown_company_or_job_is_a_clear_failure(self):
        self.assertEqual(self.run_cli("jobs", "nobody")[0], 1)
        self.assertEqual(self.run_cli("job", "acme", "nope")[0], 1)
        self.assertEqual(self.run_cli("jobs")[0], 1)

    def test_subject_text_cannot_inject_terminal_control_characters(self):
        store = SqliteStore(os.path.join(self.env["SMPLDOC_DATA_DIR"], "smpldoc.db"))
        self.addCleanup(store.close)
        c = store.find_company_by_slug("acme")
        store.create_job(c.id, "s2", "s@x.test", "bad\x1b[31m\x07subject", "rk", "received", [])
        _, out, _ = self.run_cli("jobs", "acme")
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\x07", out)


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
                while time.time() < deadline and not [j for j in store.list_jobs(company.id) if j.status == "ready"]:
                    time.sleep(0.1)
                self.assertEqual([j.status for j in store.list_jobs(company.id)], ["ready"])
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


class ForwardEndToEndTest(unittest.TestCase):
    def test_a_rule_forwards_real_mail_through_the_real_service(self):
        relay, smtp = FakeRelay(), FakeSmtp()
        self.addCleanup(relay.close)
        self.addCleanup(smtp.close)
        with tempfile.TemporaryDirectory() as d:
            data, port = os.path.join(d, "data"), free_port()
            env = {"SMPLDOC_DATA_DIR": data, "SMPLDOC_RELAY_URL": relay.url, "SMPLDOC_RELAY_TOKEN": "tok", "SMPLDOC_POLL_SECONDS": "1",
                   "SMPLDOC_PORT": str(port), "SMPLDOC_SMTP_HOST": "127.0.0.1", "SMPLDOC_SMTP_PORT": str(smtp.port),
                   "SMPLDOC_SMTP_SECURITY": "none", "SMPLDOC_MAIL_FROM": "smpldoc@example.com"}
            cli = lambda *a: main(list(a), env, out=io.StringIO(), err=io.StringIO())
            self.assertEqual(cli("add-company", "acme", "Acme"), 0)
            self.assertEqual(cli("target-add", "acme", "accounts", "ap@example.com"), 0)
            self.assertEqual(cli("rule-add", "acme", "Invoices", "forward:accounts", "subject=invoice", "body=total: 9"), 0)
            relay.deliver(mail(subject="March Invoice", attachments=[("inv.txt", "Ref: A1\n")]), "s@x.test", "acme@in.test", "pass")
            stop, result = threading.Event(), []
            t = threading.Thread(target=lambda: result.append(main(["run"], env, out=io.StringIO(), err=io.StringIO(), stop=stop)))
            t.start()
            try:
                store = SqliteStore(os.path.join(data, "smpldoc.db"))
                company = store.find_company_by_slug("acme")
                deadline = time.time() + 30
                while time.time() < deadline and not [j for j in store.list_jobs(company.id) if j.status == "done"]:
                    time.sleep(0.2)
                job = store.list_jobs(company.id)[0]
                self.assertEqual(job.status, "done")
                self.assertEqual([(e.step, e.outcome) for e in store.list_events(company.id, job.id)],
                                 [("ingest", "ok"), ("extract", "ok"), ("rules", "ok"), ("finish", "ok"), ("deliver", "ok")])
                store.close()
            finally:
                stop.set()
                t.join(15)
            self.assertEqual(result, [0])
            self.assertEqual(len(smtp.messages), 1)
            _, rcpts, msg = smtp.messages[0]
            self.assertIn("ap@example.com", rcpts[0])
            self.assertEqual(msg["Subject"], "March Invoice")
            names = [p.get_filename() for p in msg.walk() if p.get_filename()]
            self.assertEqual(names, ["inv.txt"])


if __name__ == "__main__":
    unittest.main()
