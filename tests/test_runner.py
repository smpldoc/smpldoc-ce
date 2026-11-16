import unittest
from email.message import EmailMessage

from smpldoc.adapters.memory import MemoryBlob, MemoryMailIn
from smpldoc.adapters.plain_text import PlainTextExtractor
from smpldoc.adapters.sqlite_store import SqliteStore
from smpldoc.domain.errors import ExtractError
from smpldoc.domain.intake import safe_filename, slug_from_recipient
from smpldoc.domain.runner import Runner


class Crash(BaseException):
    """Stands in for a process dying: not an Exception, so the runner must not swallow it."""


def mail(body="Invoice: 42\nTotal: 9.50\n", attachments=(), message_id="<m1@x.test>", subject="Docs"):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = "s@x.test", "acme@in.test", subject
    if message_id:
        m["Message-ID"] = message_id
    m.set_content(body)
    for name, text in attachments:
        m.add_attachment(text.encode(), maintype="text", subtype="plain", filename=name)
    return m.as_bytes()


class Flaky:
    def __init__(self, fail_times, exc=ExtractError):
        self.left, self.exc, self.inner = fail_times, exc, PlainTextExtractor()

    def extract(self, filename, content_type, data):
        if self.left:
            self.left -= 1
            raise self.exc("secret document text")
        return self.inner.extract(filename, content_type, data)


class RunnerCase(unittest.TestCase):
    def setUp(self):
        self.store, self.blob, self.mail = SqliteStore(":memory:"), MemoryBlob(), MemoryMailIn()
        self.addCleanup(self.store.close)
        self.acme = self.store.add_company("acme", "Acme")
        self.sleeps = []

    def runner(self, extractor=None, **kw):
        return Runner(self.mail, self.store, self.blob, extractor or PlainTextExtractor(),
                      sleep=self.sleeps.append, **kw)

    def deliver(self, raw=None, recipient="acme@in.test", verdict="pass"):
        self.mail.deliver(raw or mail(), "s@x.test", recipient, verdict)

    def only_job(self, company=None):
        jobs = self.store.list_jobs((company or self.acme).id)
        self.assertEqual(len(jobs), 1)
        return jobs[0]

    def steps(self, job):
        return [(e.step, e.outcome) for e in self.store.list_events(job.company_id, job.id)]


class HappyPath(RunnerCase):
    def test_email_becomes_a_done_job_with_values_and_exact_step_events(self):
        self.deliver(mail(attachments=[("notes.txt", "Ref: A1\n")]))
        summary = self.runner().run_once()
        job = self.only_job()
        self.assertEqual(job.status, "done")
        self.assertEqual((summary.completed, summary.failed), (1, 0))
        self.assertEqual(self.steps(job), [("ingest", "ok"), ("extract", "ok"), ("close", "ok")])
        values = {(v.name, v.value) for v in self.store.list_field_values(self.acme.id, job.id)}
        self.assertEqual(values, {("invoice", "42"), ("total", "9.50"), ("ref", "A1")})
        self.assertEqual(self.mail.poll(10), [])

    def test_body_and_attachments_become_documents_and_the_raw_mail_is_kept(self):
        raw = mail(attachments=[("notes.txt", "Ref: A1\n")])
        self.deliver(raw)
        self.runner().run_once()
        job = self.only_job()
        self.assertEqual(sorted(d.filename for d in self.store.list_documents(self.acme.id, job.id)),
                         ["body.txt", "notes.txt"])
        self.assertEqual(self.blob.get(self.acme.id, job.raw_key), raw)

    def test_malformed_mail_does_not_crash(self):
        self.deliver(b"\xff\xfe not an email at all")
        self.runner().run_once()
        self.assertIn(self.only_job().status, {"done", "failed"})


class Gates(RunnerCase):
    def test_unknown_company_is_rejected_and_acked(self):
        self.deliver(recipient="nobody@in.test")
        summary = self.runner().run_once()
        self.assertEqual(summary.rejected, 1)
        self.assertEqual(self.mail.poll(10), [])
        self.assertEqual(self.store.list_jobs(self.acme.id), [])

    def test_anything_but_a_pass_verdict_is_held_and_never_extracted(self):
        for verdict, mid in (("fail", "<a>"), ("unknown", "<b>")):
            self.deliver(mail(message_id=mid), verdict=verdict)
        summary = self.runner().run_once()
        self.assertEqual(summary.held, 2)
        for job in self.store.list_jobs(self.acme.id):
            self.assertEqual(job.status, "held")
            self.assertEqual(self.steps(job), [("ingest", "held")])
            self.assertEqual(self.store.list_field_values(self.acme.id, job.id), [])

    def test_duplicate_message_id_is_skipped(self):
        self.deliver()
        self.deliver()
        summary = self.runner().run_once()
        job = self.only_job()
        self.assertEqual(summary.skipped, 1)
        self.assertEqual(self.steps(job)[-1], ("ingest", "skipped"))
        self.assertEqual(self.mail.poll(10), [])

    def test_each_company_only_gets_its_own_jobs(self):
        globex = self.store.add_company("globex", "Globex")
        self.deliver()
        self.deliver(mail(message_id="<g>"), recipient="Globex+tag@in.test")
        self.runner().run_once()
        a, g = self.only_job(), self.only_job(globex)
        self.assertNotEqual(a.id, g.id)
        with self.assertRaises(KeyError):
            self.blob.get(globex.id, a.raw_key)

    def test_helpers(self):
        self.assertEqual(slug_from_recipient("Acme+x@in.test"), "acme")
        self.assertIsNone(slug_from_recipient("nope"))
        self.assertEqual(safe_filename("../../etc/passwd"), "passwd")
        self.assertEqual(safe_filename("a\x00b\r\n.txt"), "ab.txt")
        self.assertEqual(safe_filename(""), "unnamed")
        self.assertLessEqual(len(safe_filename("x" * 999)), 255)

    def test_hostile_attachment_name_is_stored_safely(self):
        self.deliver(mail(attachments=[("../../evil.txt", "Ref: 1\n")]))
        self.runner().run_once()
        names = [d.filename for d in self.store.list_documents(self.acme.id, self.only_job().id)]
        self.assertIn("evil.txt", names)


class Retries(RunnerCase):
    def test_transient_failures_are_retried_with_backoff(self):
        self.deliver()
        self.runner(Flaky(2)).run_once()
        job = self.only_job()
        self.assertEqual(job.status, "done")
        self.assertEqual(self.steps(job), [("ingest", "ok"), ("extract", "retry"), ("extract", "retry"),
                                           ("extract", "ok"), ("close", "ok")])
        self.assertEqual(self.sleeps, [1.0, 2.0])

    def test_permanent_failure_marks_the_job_failed_and_leaks_no_content(self):
        self.deliver()
        summary = self.runner(Flaky(99)).run_once()
        job = self.only_job()
        self.assertEqual((job.status, job.error), ("failed", "ExtractError"))
        self.assertEqual(summary.failed, 1)
        self.assertEqual(self.steps(job), [("ingest", "ok"), ("extract", "retry"), ("extract", "retry"), ("extract", "failed")])
        self.assertEqual(self.sleeps, [1.0, 2.0], "no sleep after the last attempt")
        self.assertEqual(self.store.list_field_values(self.acme.id, job.id), [])
        self.assertEqual(self.mail.poll(10), [])
        for e in self.store.list_events(self.acme.id, job.id):
            self.assertNotIn("secret", e.detail)

    def test_a_failing_fetch_is_nacked_for_redelivery(self):
        self.deliver()
        real, calls = self.mail.fetch, []

        def flaky_fetch(m):
            calls.append(1)
            if len(calls) == 1:
                raise OSError("network")
            return real(m)

        self.mail.fetch = flaky_fetch
        first = self.runner().run_once()
        self.assertEqual((first.deferred, self.store.list_jobs(self.acme.id)), (1, []))
        self.runner().run_once()
        self.assertEqual(self.only_job().status, "done")


class CrashRecovery(RunnerCase):
    def test_a_job_resumes_after_a_crash_mid_extract(self):
        self.deliver()
        with self.assertRaises(Crash):
            self.runner(Flaky(1, exc=Crash)).run_once()
        self.assertEqual(self.only_job().status, "extracting")
        self.runner().run_once()
        job = self.only_job()
        self.assertEqual(job.status, "done")
        self.assertEqual(self.steps(job), [("ingest", "ok"), ("extract", "ok"), ("close", "ok")])
        self.assertEqual(len(self.store.list_field_values(self.acme.id, job.id)), 2)

    def test_a_crash_between_saving_the_job_and_acking_does_not_duplicate(self):
        self.deliver()
        real_ack = self.mail.ack

        def dying_ack(m):
            raise Crash()

        self.mail.ack = dying_ack
        with self.assertRaises(Crash):
            self.runner().run_once()
        self.mail.ack = real_ack
        for m in list(self.mail.inflight.values()):
            self.mail.nack(m)  # the relay hands the mail out again after its lease
        self.runner().run_once()
        self.runner().run_once()
        job = self.only_job()
        self.assertEqual(job.status, "done")
        self.assertEqual(len(self.store.list_field_values(self.acme.id, job.id)), 2)
        self.assertEqual(self.mail.poll(10), [])


if __name__ == "__main__":
    unittest.main()
