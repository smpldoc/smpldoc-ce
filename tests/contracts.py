"""Shared contract tests. Every adapter for a port must pass the same class.

Each concrete test case mixes one of these into unittest.TestCase and supplies the factory
methods named at the top of the mixin.
"""
import hashlib

from smpldoc.domain.models import Condition, NewDocument, NewValue

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

    def test_get_company_by_id(self):
        self.assertEqual(self.store.get_company(self.a.id), self.a)
        self.assertIsNone(self.store.get_company("nope"))

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
        self.assertEqual(self.store.get_job(self.a.id, job.id).status, "ready")
        got = self.store.list_field_values(self.a.id, job.id)
        self.assertEqual([(v.name, v.value) for v in got], [("invoice", "42"), ("total", "9.50")])

    def test_completing_again_after_a_reprocess_replaces_the_values(self):
        job, _ = self.job(self.a, docs=[NewDocument("a.txt", "text/plain", "k1", 3)])
        doc = self.store.list_documents(self.a.id, job.id)[0]
        self.assertTrue(self.store.complete_job(self.a.id, job.id, [NewValue(doc.id, "total", "1")]))
        self.assertTrue(self.store.move_job(self.a.id, job.id, ["ready"], "extracting"))
        self.assertTrue(self.store.complete_job(self.a.id, job.id, [NewValue(doc.id, "total", "2"), NewValue(doc.id, "ref", "x")]))
        self.assertEqual([(v.name, v.value) for v in self.store.list_field_values(self.a.id, job.id)], [("total", "2"), ("ref", "x")])

    def test_complete_job_can_hold_close_flag_a_conflict_or_queue_a_forward(self):
        for i, (status, kw, check) in enumerate([
            ("held", {}, lambda j: j.status == "held"),
            ("closed", {}, lambda j: j.status == "closed"),
            ("ready", {"conflict": ("r1", "r2")}, lambda j: j.rule_conflict == ("r1", "r2")),
            ("ready", {"forward_target": "ap"}, lambda j: j.forward_target == "ap"),
        ]):
            job, _ = self.job(self.a, f"c{i}")
            self.assertTrue(self.store.complete_job(self.a.id, job.id, [], status=status, **kw))
            self.assertTrue(check(self.store.get_job(self.a.id, job.id)), status)
        job, _ = self.job(self.a, "bad")
        with self.assertRaises(ValueError):
            self.store.complete_job(self.a.id, job.id, [], status="done")

    def test_move_job_is_compare_and_set_and_clears_the_conflict(self):
        job, _ = self.job(self.a)
        self.store.complete_job(self.a.id, job.id, [], conflict=("r1",))
        self.assertFalse(self.store.move_job(self.a.id, job.id, ["held"], "closed"))
        self.assertFalse(self.store.move_job(self.b.id, job.id, ["ready"], "closed"))
        self.assertTrue(self.store.move_job(self.a.id, job.id, ["ready", "held"], "held"))
        got = self.store.get_job(self.a.id, job.id)
        self.assertEqual((got.status, got.rule_conflict), ("held", ()))

    def test_move_job_can_queue_a_forward_without_changing_status(self):
        job, _ = self.job(self.a)
        self.store.complete_job(self.a.id, job.id, [])
        self.assertTrue(self.store.move_job(self.a.id, job.id, ["ready"], "ready", forward_target="ap"))
        self.assertEqual(self.store.get_job(self.a.id, job.id).forward_target, "ap")
        self.assertEqual([j.id for j in self.store.list_to_deliver()], [job.id])

    def test_delivery_settles_to_done_or_records_the_failure(self):
        j1, _ = self.job(self.a, "d1")
        j2, _ = self.job(self.a, "d2")
        for j in (j1, j2):
            self.store.complete_job(self.a.id, j.id, [], forward_target="ap")
        self.assertTrue(self.store.settle_delivery(self.a.id, j1.id, True))
        self.assertTrue(self.store.settle_delivery(self.a.id, j2.id, False, "SendError"))
        d1, d2 = self.store.get_job(self.a.id, j1.id), self.store.get_job(self.a.id, j2.id)
        self.assertEqual((d1.status, d1.forward_target, d1.error), ("done", "", ""))
        self.assertEqual((d2.status, d2.forward_target, d2.error), ("ready", "", "SendError"))
        self.assertFalse(self.store.settle_delivery(self.a.id, j1.id, True), "nothing queued any more")
        self.assertEqual(self.store.list_to_deliver(), [])

    def test_a_job_remembers_who_it_was_sent_to(self):
        job, _ = self.store.create_job(self.a.id, "r", "x@y.test", "S", "rk", "received", [], recipient="acme@in.test")
        self.assertEqual(self.store.get_job(self.a.id, job.id).recipient, "acme@in.test")

    def test_documents_know_if_they_are_the_body(self):
        job, _ = self.job(self.a, docs=[NewDocument("body.txt", "text/plain", "k1", 3, "body"), NewDocument("a.pdf", "application/pdf", "k2", 9)])
        self.assertEqual([d.kind for d in self.store.list_documents(self.a.id, job.id)], ["body", "attachment"])

    def test_rules_are_stored_per_company_and_limited(self):
        r = self.store.add_rule(self.a.id, "Big", "forward", "ap", [Condition("subject", "x"), Condition("format", "pdf")])
        self.store.add_rule(self.a.id, "Off", "hold", "", [Condition("from", "y")], enabled=False)
        self.assertEqual([x.name for x in self.store.list_rules(self.a.id)], ["Big", "Off"])
        self.assertEqual([x.name for x in self.store.list_rules(self.a.id, enabled_only=True)], ["Big"])
        got = self.store.get_rule(self.a.id, r.id)
        self.assertEqual((got.action, got.target, got.conditions), ("forward", "ap", (Condition("subject", "x"), Condition("format", "pdf"))))
        self.assertEqual(self.store.list_rules(self.b.id), [])
        self.assertIsNone(self.store.get_rule(self.b.id, r.id))
        self.assertFalse(self.store.set_rule_enabled(self.b.id, r.id, False))
        self.assertFalse(self.store.delete_rule(self.b.id, r.id))
        self.assertTrue(self.store.set_rule_enabled(self.a.id, r.id, False))
        self.assertFalse(self.store.get_rule(self.a.id, r.id).enabled)
        self.assertTrue(self.store.delete_rule(self.a.id, r.id))
        self.assertIsNone(self.store.get_rule(self.a.id, r.id))

    def test_a_company_can_have_at_most_fifty_rules(self):
        for i in range(50):
            self.store.add_rule(self.a.id, f"r{i}", "hold", "", [Condition("subject", "x")])
        with self.assertRaises(ValueError):
            self.store.add_rule(self.a.id, "one too many", "hold", "", [Condition("subject", "x")])
        self.store.add_rule(self.b.id, "other company is unaffected", "hold", "", [Condition("subject", "x")])

    def test_forward_targets_are_named_and_scoped(self):
        t = self.store.add_target(self.a.id, "accounts", "ap@example.com")
        self.assertEqual((t.name, t.address), ("accounts", "ap@example.com"))
        self.assertEqual(self.store.get_target(self.a.id, "accounts").address, "ap@example.com")
        self.assertIsNone(self.store.get_target(self.b.id, "accounts"))
        self.assertEqual([x.name for x in self.store.list_targets(self.a.id)], ["accounts"])
        self.assertEqual(self.store.list_targets(self.b.id), [])
        with self.assertRaises(ValueError):
            self.store.add_target(self.a.id, "accounts", "other@example.com")
        for name, addr in (("Bad Name", "a@b.test"), ("ok", "not-an-address"), ("ok", "a@b.test\r\nBcc: x@y.test")):
            with self.assertRaises(ValueError, msg=f"{name} {addr!r}"):
                self.store.add_target(self.a.id, name, addr)
        self.assertFalse(self.store.delete_target(self.b.id, "accounts"))
        self.assertTrue(self.store.delete_target(self.a.id, "accounts"))

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


class BundleStoreContract:
    """A bundle is a set of files under relative paths, kept per company. put replaces the whole
    bundle at once: a reader sees the old files or the new ones, never a mix."""
    ID = "019ac8f0c4000000000000000000b001"
    FILES = {"manifest.json": b"{}", "original/a.txt": b"hello", "text.json": b"[]"}

    def make_bundles(self):
        raise NotImplementedError

    def setUp(self):
        self.bundles = self.make_bundles()

    def test_round_trip(self):
        self.bundles.put("acme", self.ID, self.FILES)
        self.assertEqual(self.bundles.get("acme", self.ID), self.FILES)
        self.assertEqual(self.bundles.list_ids("acme"), [self.ID])

    def test_put_replaces_the_whole_bundle(self):
        self.bundles.put("acme", self.ID, self.FILES)
        newer = {"manifest.json": b"{\"v\":2}", "card.json": b"{}"}
        self.bundles.put("acme", self.ID, newer)
        self.assertEqual(self.bundles.get("acme", self.ID), newer)

    def test_bytes_are_kept_exactly(self):
        files = {"manifest.json": RAW, "original/a b.bin": bytes(range(256))}
        self.bundles.put("acme", self.ID, files)
        self.assertEqual(self.bundles.get("acme", self.ID), files)

    def test_other_company_cannot_read(self):
        self.bundles.put("acme", self.ID, self.FILES)
        with self.assertRaises(KeyError):
            self.bundles.get("globex", self.ID)
        self.assertEqual(self.bundles.list_ids("globex"), [])

    def test_unknown_and_hostile_names_are_not_found(self):
        for company, bundle_id in (("acme", "0" * 32), ("acme", "../x"), ("acme", ""), ("acme", "A" * 32), ("../x", self.ID), ("", self.ID), ("a/b", self.ID)):
            with self.assertRaises(KeyError, msg=(company, bundle_id)):
                self.bundles.get(company, bundle_id)
        self.assertEqual(self.bundles.list_ids("../x"), [])

    def test_a_refused_put_leaves_nothing_behind(self):
        bad = ({"manifest.json": b"{}", "../x": b"1"}, {"manifest.json": b"{}", "/abs": b"1"}, {"manifest.json": b"{}", "a/../b": b"1"},
               {"manifest.json": b"{}", "a//b": b"1"}, {"manifest.json": b"{}", "": b"1"}, {"original/a.txt": b"1"}, {})
        for files in bad:
            with self.assertRaises(ValueError, msg=list(files)):
                self.bundles.put("acme", self.ID, files)
        for company, bundle_id in (("../x", self.ID), ("", self.ID), ("Acme", self.ID), ("acme", "../x"), ("acme", "short")):
            with self.assertRaises(ValueError, msg=(company, bundle_id)):
                self.bundles.put(company, bundle_id, self.FILES)
        self.assertEqual(self.bundles.list_ids("acme"), [])

    def test_a_refused_replacement_keeps_the_old_bundle(self):
        self.bundles.put("acme", self.ID, self.FILES)
        with self.assertRaises(ValueError):
            self.bundles.put("acme", self.ID, {"manifest.json": b"{}", "../x": b"1"})
        self.assertEqual(self.bundles.get("acme", self.ID), self.FILES)

    def test_list_ids_is_sorted_and_per_company(self):
        ids = ["019ac8f0c4000000000000000000b003", "019ac8f0c4000000000000000000b001", "019ac8f0c4000000000000000000b002"]
        for i in ids:
            self.bundles.put("acme", i, self.FILES)
        self.bundles.put("globex", "019ac8f0c4000000000000000000b009", self.FILES)
        self.assertEqual(self.bundles.list_ids("acme"), sorted(ids))


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
