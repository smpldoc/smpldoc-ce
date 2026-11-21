"""Shared contract tests. Every adapter for a port must pass the same class.

Each concrete test case mixes one of these into unittest.TestCase and supplies the factory
methods named at the top of the mixin.
"""
import hashlib

from smpldoc.domain.models import NewDocument, NewValue

RAW = b"From: a@b.test\r\n\r\nbody \x00\xff\xfe binary-safe\r\n"


class StoreContract:
    def make_store(self):
        raise NotImplementedError

    def setUp(self):
        self.store = self.make_store()
        self.addCleanup(self.store.close)
        self.a = self.store.add_company("acme", "Acme")
        self.b = self.store.add_company("globex", "Globex")

    def job(self, company, source="s1", status="received", docs=()):
        return self.store.create_job(company.id, source, "x@y.test", "Subject", "rawkey", status, list(docs))

    def test_company_lookup_and_unique_slug(self):
        self.assertEqual(self.store.find_company_by_slug("acme"), self.a)
        self.assertIsNone(self.store.find_company_by_slug("nope"))
        with self.assertRaises(ValueError):
            self.store.add_company("acme", "Again")

    def test_create_job_is_idempotent_per_company(self):
        job, created = self.job(self.a)
        again, created2 = self.job(self.a)
        self.assertTrue(created)
        self.assertFalse(created2)
        self.assertEqual(job.id, again.id)
        other, created3 = self.job(self.b)
        self.assertTrue(created3)
        self.assertNotEqual(job.id, other.id)

    def test_documents_are_saved_with_the_job(self):
        docs = [NewDocument("a.txt", "text/plain", "k1", 3), NewDocument("b.pdf", "application/pdf", "k2", 9)]
        job, _ = self.job(self.a, docs=docs)
        got = self.store.list_documents(self.a.id, job.id)
        self.assertEqual([d.filename for d in got], ["a.txt", "b.pdf"])
        self.assertEqual({d.company_id for d in got}, {self.a.id})

    def test_nothing_crosses_companies(self):
        job, _ = self.job(self.a, docs=[NewDocument("a.txt", "text/plain", "k1", 3)])
        self.store.add_event(self.a.id, job.id, "ingest", "ok")
        self.assertIsNone(self.store.get_job(self.b.id, job.id))
        self.assertEqual(self.store.list_jobs(self.b.id), [])
        self.assertEqual(self.store.list_documents(self.b.id, job.id), [])
        self.assertEqual(self.store.list_events(self.b.id, job.id), [])
        self.assertFalse(self.store.complete_job(self.b.id, job.id, []))
        self.assertEqual(self.store.get_job(self.a.id, job.id).status, "received")

    def test_list_jobs_filters_by_status(self):
        j1, _ = self.job(self.a, "s1")
        self.job(self.a, "s2", status="held")
        self.assertEqual([j.id for j in self.store.list_jobs(self.a.id, "received")], [j1.id])
        self.assertEqual(len(self.store.list_jobs(self.a.id)), 2)

    def test_complete_job_is_atomic_and_only_once(self):
        job, _ = self.job(self.a, docs=[NewDocument("a.txt", "text/plain", "k1", 3)])
        doc = self.store.list_documents(self.a.id, job.id)[0]
        values = [NewValue(doc.id, "invoice", "42"), NewValue(doc.id, "total", "9.50")]
        self.assertTrue(self.store.complete_job(self.a.id, job.id, values))
        self.assertFalse(self.store.complete_job(self.a.id, job.id, values))
        self.assertEqual(self.store.get_job(self.a.id, job.id).status, "done")
        got = self.store.list_field_values(self.a.id, job.id)
        self.assertEqual([(v.name, v.value) for v in got], [("invoice", "42"), ("total", "9.50")])

    def test_held_jobs_cannot_be_completed(self):
        job, _ = self.job(self.a, status="held")
        self.assertFalse(self.store.complete_job(self.a.id, job.id, []))
        self.assertEqual(self.store.get_job(self.a.id, job.id).status, "held")

    def test_events_keep_order_and_are_append_only(self):
        job, _ = self.job(self.a)
        for step, outcome, attempt in [("ingest", "ok", 1), ("extract", "retry", 1), ("extract", "ok", 2)]:
            self.store.add_event(self.a.id, job.id, step, outcome, attempt)
        got = self.store.list_events(self.a.id, job.id)
        self.assertEqual([(e.step, e.outcome, e.attempt) for e in got],
                         [("ingest", "ok", 1), ("extract", "retry", 1), ("extract", "ok", 2)])

    def test_pending_lists_unfinished_jobs_across_companies(self):
        j1, _ = self.job(self.a, "s1")
        j2, _ = self.job(self.b, "s2")
        self.job(self.a, "s3", status="held")
        done, _ = self.job(self.a, "s4")
        self.store.complete_job(self.a.id, done.id, [])
        self.assertEqual({j.id for j in self.store.list_pending()}, {j1.id, j2.id})

    def test_set_status_records_error(self):
        job, _ = self.job(self.a)
        self.store.set_status(self.a.id, job.id, "failed", "ExtractError")
        got = self.store.get_job(self.a.id, job.id)
        self.assertEqual((got.status, got.error), ("failed", "ExtractError"))


class BlobContract:
    def make_blob(self):
        raise NotImplementedError

    def setUp(self):
        self.blob = self.make_blob()

    def test_round_trip_and_content_addressed_key(self):
        key = self.blob.put("acme", RAW)
        self.assertEqual(key, hashlib.sha256(RAW).hexdigest())
        self.assertEqual(self.blob.get("acme", key), RAW)
        self.assertEqual(self.blob.put("acme", RAW), key)

    def test_other_company_cannot_read(self):
        key = self.blob.put("acme", RAW)
        with self.assertRaises(KeyError):
            self.blob.get("globex", key)

    def test_unknown_and_hostile_keys_are_not_found(self):
        for key in ("0" * 64, "../x", "..\\x", "/etc/passwd", "", "a" * 65):
            with self.assertRaises(KeyError, msg=key):
                self.blob.get("acme", key)


class ExtractorContract:
    def make_extractor(self):
        raise NotImplementedError

    def setUp(self):
        self.extractor = self.make_extractor()

    def test_returns_pairs_of_text_and_is_deterministic(self):
        data = b"Invoice: 42\nTotal: 9.50\n"
        first = self.extractor.extract("a.txt", "text/plain", data)
        self.assertEqual(first, self.extractor.extract("a.txt", "text/plain", data))
        for pair in first:
            self.assertEqual(len(pair), 2)
            self.assertTrue(all(isinstance(p, str) for p in pair))

    def test_empty_and_binary_input_do_not_crash(self):
        self.assertEqual(self.extractor.extract("a.txt", "text/plain", b""), [])
        self.assertIsInstance(self.extractor.extract("a.bin", "application/octet-stream", RAW), list)


class MailInContract:
    """Needs self.mail and self.deliver(raw, sender, recipient, verdict), which returns the exact
    bytes the source will hand out (a source may add its own headers, as SES does)."""

    def deliver(self, raw=RAW, sender="s@x.test", recipient="acme@in.test", verdict="pass"):
        raise NotImplementedError

    def test_empty_queue(self):
        self.assertEqual(self.mail.poll(10), [])

    def test_poll_fetch_returns_exact_bytes_and_fields(self):
        stored = self.deliver(RAW, "s@x.test", "acme@in.test", "pass")
        got = self.mail.poll(10)
        self.assertEqual(len(got), 1)
        m = got[0]
        self.assertEqual((m.sender, m.recipient, m.verdict), ("s@x.test", "acme@in.test", "pass"))
        self.assertEqual(self.mail.fetch(m), stored)
        self.assertEqual(m.size, len(stored))

    def test_in_flight_messages_are_not_delivered_twice(self):
        self.deliver()
        self.assertEqual(len(self.mail.poll(10)), 1)
        self.assertEqual(self.mail.poll(10), [])

    def test_nack_makes_a_message_available_again(self):
        self.deliver()
        m = self.mail.poll(10)[0]
        self.mail.nack(m)
        self.assertEqual(len(self.mail.poll(10)), 1)

    def test_ack_removes_for_good(self):
        self.deliver()
        m = self.mail.poll(10)[0]
        self.mail.ack(m)
        self.assertEqual(self.mail.poll(10), [])

    def test_limit_is_respected(self):
        for _ in range(3):
            self.deliver()
        self.assertEqual(len(self.mail.poll(2)), 2)
        self.assertEqual(len(self.mail.poll(2)), 1)

    def test_verdict_is_always_normalised(self):
        for v in ("pass", "fail", "unknown"):
            self.deliver(verdict=v)
        self.assertEqual(sorted(m.verdict for m in self.mail.poll(10)), ["fail", "pass", "unknown"])
