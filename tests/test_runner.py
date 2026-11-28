import hashlib
import json
import unittest
from email.message import EmailMessage

from smpldoc.adapters.memory import MemoryBlob, MemoryBundleStore, MemoryMailIn, MemoryMailOut
from smpldoc.adapters.plain_text import PlainTextExtractor
from smpldoc.adapters.sqlite_store import SqliteStore
from smpldoc.domain import bundle
from smpldoc.domain.errors import ExtractError, SendError
from smpldoc.domain.models import Condition
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

    def rule(self, name, action, *conds, target="", company=None):
        return self.store.add_rule((company or self.acme).id, name, action, target, [Condition(f, p) for f, p in conds])

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
        self.assertEqual(job.status, "ready")
        self.assertEqual((summary.completed, summary.failed), (1, 0))
        self.assertEqual(self.steps(job), [("ingest", "ok"), ("extract", "ok"), ("rules", "ok"), ("finish", "ok")])
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
        self.assertIn(self.only_job().status, {"ready", "failed"})


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
        self.assertEqual(job.status, "ready")
        self.assertEqual(self.steps(job), [("ingest", "ok"), ("extract", "retry"), ("extract", "retry"),
                                           ("extract", "ok"), ("rules", "ok"), ("finish", "ok")])
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
        self.assertEqual(self.only_job().status, "ready")


class CrashRecovery(RunnerCase):
    def test_a_job_resumes_after_a_crash_mid_extract(self):
        self.deliver()
        with self.assertRaises(Crash):
            self.runner(Flaky(1, exc=Crash)).run_once()
        self.assertEqual(self.only_job().status, "extracting")
        self.runner().run_once()
        job = self.only_job()
        self.assertEqual(job.status, "ready")
        self.assertEqual(self.steps(job), [("ingest", "ok"), ("extract", "ok"), ("rules", "ok"), ("finish", "ok")])
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
        self.assertEqual(job.status, "ready")
        self.assertEqual(len(self.store.list_field_values(self.acme.id, job.id)), 2)
        self.assertEqual(self.mail.poll(10), [])


class Rules(RunnerCase):
    def run_one(self, **kw):
        self.deliver(mail(subject=kw.pop("subject", "March Invoice"), attachments=kw.pop("attachments", ())))
        self.runner(**kw).run_once()
        return self.only_job()

    def test_with_no_matching_rule_the_job_waits_for_a_person(self):
        self.rule("Refunds", "close", ("subject", "refund"))
        job = self.run_one()
        self.assertEqual(job.status, "ready")
        self.assertIn(("rules", "ok"), self.steps(job))
        self.assertEqual([e.detail for e in self.store.list_events(job.company_id, job.id) if e.step == "rules"], ["none"])

    def test_a_matching_rule_moves_the_job(self):
        for action, status in (("hold", "held"), ("close", "closed"), ("review", "ready")):
            self.store.close()
            self.setUp()
            self.rule("R", action, ("subject", "invoice"))
            job = self.run_one()
            self.assertEqual(job.status, status, action)
            self.assertEqual([e.detail for e in self.store.list_events(job.company_id, job.id) if e.step == "rules"], [action])

    def test_rules_can_read_the_body_attachment_names_and_formats(self):
        self.rule("Pdf from vendor", "hold", ("filename", r"^inv-\d+\.pdf$"), ("format", "pdf"), ("body", "total: 9"), ("to", "^acme@"))
        job = self.run_one(attachments=[("inv-42.pdf", "x")])
        self.assertEqual(job.status, "held")

    def test_rules_that_disagree_flag_the_job_and_move_nothing(self):
        a = self.rule("A", "hold", ("subject", "invoice"))
        b = self.rule("B", "close", ("body", "total"))
        job = self.run_one()
        self.assertEqual((job.status, set(job.rule_conflict)), ("ready", {a.id, b.id}))
        self.assertEqual([e.detail for e in self.store.list_events(job.company_id, job.id) if e.step == "rules"], ["conflict"])

    def test_a_rule_that_cannot_be_evaluated_does_not_lose_the_job(self):
        self.rule("A", "hold", ("subject", "invoice"))

        def boom(rules, facts):
            raise TimeoutError("slow pattern")

        job = self.run_one(evaluate=boom)
        self.assertEqual(job.status, "ready")
        steps = self.steps(job)
        self.assertEqual([s for s in steps if s[0] == "rules"], [("rules", "retry"), ("rules", "retry"), ("rules", "failed")])
        self.assertEqual(steps[-1], ("finish", "ok"))

    def test_a_reprocess_runs_extract_and_rules_again(self):
        job = self.run_one()
        self.rule("Late rule", "hold", ("subject", "invoice"))
        self.assertTrue(self.store.move_job(self.acme.id, job.id, ["ready"], "extracting"))
        self.runner().run_once()
        got = self.store.get_job(self.acme.id, job.id)
        self.assertEqual(got.status, "held")
        self.assertEqual(len(self.store.list_field_values(self.acme.id, job.id)), 2)


class Forwarding(RunnerCase):
    def setUp(self):
        super().setUp()
        self.out = MemoryMailOut()
        self.store.add_target(self.acme.id, "accounts", "ap@example.com")

    def run_one(self, subject="March Invoice", attachments=(), **kw):
        self.deliver(mail(subject=subject, attachments=attachments))
        self.runner(mail_out=self.out, **kw).run_once()
        return self.only_job()

    def test_a_forward_rule_sends_the_mail_and_finishes_the_job(self):
        self.rule("To accounts", "forward", ("subject", "invoice"), target="accounts")
        job = self.run_one(attachments=[("inv.txt", "Ref: A1\n")])
        self.assertEqual((job.status, job.forward_target, job.error), ("done", "", ""))
        self.assertEqual(self.steps(job)[-2:], [("finish", "ok"), ("deliver", "ok")])
        mail_out = self.out.sent[0]
        self.assertEqual((mail_out.to, mail_out.subject), ("ap@example.com", "March Invoice"))
        self.assertEqual([a.filename for a in mail_out.attachments], ["inv.txt"])
        self.assertIn("total: 9.50", mail_out.text)
        self.assertIn("Job ID: " + job.id, mail_out.text)

    def test_the_body_is_not_attached_only_real_attachments(self):
        self.rule("To accounts", "forward", ("subject", "invoice"), target="accounts")
        self.run_one()
        self.assertEqual(self.out.sent[0].attachments, ())

    def test_transient_send_failures_are_retried_with_backoff(self):
        self.rule("To accounts", "forward", ("subject", "invoice"), target="accounts")
        self.out.fail_times = 2
        job = self.run_one()
        self.assertEqual(job.status, "done")
        self.assertEqual([s for s in self.steps(job) if s[0] == "deliver"], [("deliver", "retry"), ("deliver", "retry"), ("deliver", "ok")])
        self.assertEqual(self.sleeps, [1.0, 2.0])

    def test_a_permanent_failure_is_not_retried_and_leaves_the_job_for_a_person(self):
        self.rule("To accounts", "forward", ("subject", "invoice"), target="accounts")
        self.out.fail_times, self.out.permanent = 5, True
        job = self.run_one()
        self.assertEqual((job.status, job.forward_target, job.error), ("ready", "", "SendError"))
        self.assertEqual([s for s in self.steps(job) if s[0] == "deliver"], [("deliver", "failed")])
        self.assertEqual(self.sleeps, [])
        self.assertEqual(self.out.sent, [])

    def test_a_failed_delivery_does_not_loop_forever(self):
        self.rule("To accounts", "forward", ("subject", "invoice"), target="accounts")
        self.out.fail_times = 99
        self.run_one()
        before = len(self.store.list_events(self.acme.id, self.only_job().id))
        self.runner(mail_out=self.out).run_once()
        self.assertEqual(len(self.store.list_events(self.acme.id, self.only_job().id)), before)

    def test_a_deleted_target_or_no_mail_out_is_a_clear_failure(self):
        self.rule("To accounts", "forward", ("subject", "invoice"), target="accounts")
        self.store.delete_target(self.acme.id, "accounts")
        job = self.run_one()
        self.assertEqual((job.status, job.error), ("ready", "ForwardError"))
        self.store.close()
        self.setUp()
        self.rule("To accounts", "forward", ("subject", "invoice"), target="accounts")
        self.deliver(mail(subject="March Invoice"))
        self.runner().run_once()  # no mail_out configured
        job = self.only_job()
        self.assertEqual((job.status, job.error), ("ready", "NotConfigured"))

    def test_too_much_to_email_is_a_permanent_failure(self):
        self.rule("To accounts", "forward", ("subject", "invoice"), target="accounts")
        job = self.run_one(attachments=[("big.txt", "x" * 5000)], max_forward_bytes=1000)
        self.assertEqual((job.status, job.error), ("ready", "ForwardError"))

    def test_a_crash_while_sending_is_picked_up_and_sent_once(self):
        self.rule("To accounts", "forward", ("subject", "invoice"), target="accounts")

        class Dies(MemoryMailOut):
            def send(self, mail):
                raise Crash()

        self.deliver(mail(subject="March Invoice"))
        with self.assertRaises(Crash):
            Runner(self.mail, self.store, self.blob, PlainTextExtractor(), mail_out=Dies(), sleep=self.sleeps.append).run_once()
        self.assertEqual(self.only_job().forward_target, "accounts")
        self.runner(mail_out=self.out).run_once()
        self.runner(mail_out=self.out).run_once()
        self.assertEqual((len(self.out.sent), self.only_job().status), (1, "done"))

    def test_a_forward_a_person_queued_is_sent_on_the_next_cycle(self):
        job = self.run_one()
        self.assertEqual(job.status, "ready")
        self.assertTrue(self.store.move_job(self.acme.id, job.id, ["ready"], "ready", forward_target="accounts"))
        self.runner(mail_out=self.out).run_once()
        self.assertEqual((self.only_job().status, len(self.out.sent)), ("done", 1))



class FlakyBundles(MemoryBundleStore):
    def __init__(self, fail_times):
        super().__init__()
        self.left = fail_times

    def put(self, company, bundle_id, files):
        if self.left:
            self.left -= 1
            raise OSError("disk full while writing secret document text")
        super().put(company, bundle_id, files)


def pdf_mail(body="See attached.\n"):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = "s@x.test", "acme@in.test", "Scan", "<pdf@x.test>"
    m.set_content(body)
    m.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="scan.pdf")
    return m.as_bytes()


class Bundles(RunnerCase):
    def setUp(self):
        super().setUp()
        self.bundles = MemoryBundleStore()

    def run_bundled(self, **kw):
        return self.runner(bundles=self.bundles, **kw).run_once()

    def test_each_attachment_gets_a_valid_bundle_and_the_message_text_does_not(self):
        self.deliver(mail(attachments=[("notes.txt", "Ref: A1\n"), ("more.txt", "Ref: B2\n")]))
        self.run_bundled()
        job = self.only_job()
        docs = {d.filename: d for d in self.store.list_documents(self.acme.id, job.id)}
        self.assertEqual(self.bundles.list_ids("acme"), sorted([docs["notes.txt"].id, docs["more.txt"].id]))
        for name in ("notes.txt", "more.txt"):
            files = self.bundles.get("acme", docs[name].id)
            self.assertEqual(bundle.validate(files), [], name)
            manifest = json.loads(files["manifest.json"])
            self.assertEqual((manifest["company"], manifest["job_id"], manifest["bundle_id"]), ("acme", job.id, docs[name].id))
            self.assertEqual(manifest["source"]["sender"], "s@x.test")
            self.assertEqual(manifest["original"]["sha256"], hashlib.sha256(self.blob.get(self.acme.id, docs[name].blob_key)).hexdigest())

    def test_the_fields_in_the_bundle_are_the_values_the_job_has(self):
        self.deliver(mail(attachments=[("notes.txt", "Ref: A1\nTotal: 9.50\n")]))
        self.run_bundled()
        job = self.only_job()
        notes = next(d for d in self.store.list_documents(self.acme.id, job.id) if d.filename == "notes.txt")
        fields = json.loads(self.bundles.get("acme", notes.id)["fields.json"])["fields"]
        self.assertEqual([(f["name"], f["value"]) for f in fields], [("ref", "A1"), ("total", "9.50")])
        stored = {(v.name, v.value) for v in self.store.list_field_values(self.acme.id, job.id) if v.document_id == notes.id}
        self.assertEqual({(f["name"], f["value"]) for f in fields}, stored)

    def test_when_nothing_is_attached_the_message_text_is_the_document(self):
        self.deliver(mail())
        self.run_bundled()
        job = self.only_job()
        (body,) = self.store.list_documents(self.acme.id, job.id)
        self.assertEqual(self.bundles.list_ids("acme"), [body.id])
        self.assertEqual(bundle.validate(self.bundles.get("acme", body.id)), [])

    def test_the_bundle_step_is_recorded_between_extract_and_rules(self):
        self.deliver(mail(attachments=[("notes.txt", "Ref: A1\n")]))
        self.run_bundled()
        self.assertEqual(self.steps(self.only_job()), [("ingest", "ok"), ("extract", "ok"), ("bundle", "ok"), ("rules", "ok"), ("finish", "ok")])
        (event,) = [e for e in self.store.list_events(self.acme.id, self.only_job().id) if e.step == "bundle"]
        self.assertEqual(event.detail, "1 written")

    def test_what_cannot_be_read_yet_is_skipped_and_the_job_still_finishes(self):
        self.deliver(pdf_mail())
        self.run_bundled()
        job = self.only_job()
        self.assertEqual(job.status, "ready")
        self.assertEqual(self.bundles.list_ids("acme"), [])
        (event,) = [e for e in self.store.list_events(self.acme.id, job.id) if e.step == "bundle"]
        self.assertEqual((event.outcome, event.detail), ("ok", "0 written, 1 skipped (not-readable-yet)"))

    def test_without_a_bundle_store_nothing_changes(self):
        self.deliver(mail(attachments=[("notes.txt", "Ref: A1\n")]))
        self.runner().run_once()
        self.assertNotIn("bundle", [step for step, _ in self.steps(self.only_job())])

    def test_a_write_that_fails_is_retried_and_leaves_one_bundle(self):
        self.bundles = FlakyBundles(fail_times=1)
        self.deliver(mail(attachments=[("notes.txt", "Ref: A1\n")]))
        self.run_bundled()
        job = self.only_job()
        self.assertEqual(job.status, "ready")
        self.assertIn(("bundle", "retry"), self.steps(job))
        self.assertEqual(len(self.bundles.list_ids("acme")), 1)
        self.assertEqual(self.sleeps, [1.0])

    def test_a_write_that_keeps_failing_fails_the_job_without_storing_document_text(self):
        self.bundles = FlakyBundles(fail_times=99)
        self.deliver(mail(attachments=[("notes.txt", "Ref: A1\n")]))
        summary = self.run_bundled()
        job = self.only_job()
        self.assertEqual((job.status, job.error, summary.failed), ("failed", "OSError", 1))
        self.assertEqual(self.store.list_field_values(self.acme.id, job.id), [])
        events = self.store.list_events(self.acme.id, job.id)
        self.assertNotIn("secret", " ".join(e.detail for e in events))
        self.assertNotIn("secret", job.error)

    def test_running_again_after_a_crash_rewrites_the_same_bundle(self):
        self.deliver(mail(attachments=[("notes.txt", "Ref: A1\n")]))
        self.run_bundled()
        job = self.only_job()
        notes = next(d for d in self.store.list_documents(self.acme.id, job.id) if d.filename == "notes.txt")
        first = self.bundles.get("acme", notes.id)
        self.store.set_status(self.acme.id, job.id, "extracting")  # as if it died before finishing
        self.run_bundled()
        self.assertEqual(self.bundles.get("acme", notes.id), first)
        self.assertEqual(len(self.bundles.list_ids("acme")), 1)

    def test_a_duplicate_message_writes_no_second_bundle(self):
        self.deliver(mail(attachments=[("notes.txt", "Ref: A1\n")]))
        self.run_bundled()
        self.deliver(mail(attachments=[("notes.txt", "Ref: A1\n")]))
        self.run_bundled()
        self.assertEqual(len(self.bundles.list_ids("acme")), 1)

    def test_companies_keep_their_bundles_apart(self):
        globex = self.store.add_company("globex", "Globex")
        self.deliver(mail(attachments=[("notes.txt", "Ref: A1\n")]))
        self.deliver(mail(message_id="<g@x.test>", attachments=[("notes.txt", "Ref: G1\n")]), recipient="globex@in.test")
        self.run_bundled()
        self.assertEqual(len(self.bundles.list_ids("acme")), 1)
        self.assertEqual(len(self.bundles.list_ids("globex")), 1)
        self.assertEqual(self.store.list_jobs(globex.id)[0].status, "ready")

    def test_held_mail_gets_no_bundle(self):
        self.deliver(mail(attachments=[("notes.txt", "Ref: A1\n")]), verdict="fail")
        self.run_bundled()
        self.assertEqual(self.bundles.list_ids("acme"), [])


if __name__ == "__main__":
    unittest.main()