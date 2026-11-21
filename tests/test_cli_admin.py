import io
import os
import tempfile
import unittest

from smpldoc.adapters.sqlite_store import SqliteStore
from smpldoc.domain.models import NewValue
from smpldoc.main import main


class AdminCliTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.addCleanup(self._d.cleanup)
        self.data = os.path.join(self._d.name, "data")
        self.env = {"SMPLDOC_DATA_DIR": self.data}
        self.assertEqual(self.run_cli("add-company", "acme", "Acme")[0], 0)
        self.store = SqliteStore(os.path.join(self.data, "smpldoc.db"))
        self.addCleanup(self.store.close)
        self.company = self.store.find_company_by_slug("acme")

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        return main(list(argv), self.env, out=out, err=err), out.getvalue(), err.getvalue()

    def ready_job(self, source="s1", subject="March Invoice", **kw):
        job, _ = self.store.create_job(self.company.id, source, "s@x.test", subject, "rk", "received", [])
        self.store.complete_job(self.company.id, job.id, [], **kw)
        return job

    # ---- targets
    def test_targets_can_be_added_listed_and_deleted(self):
        self.assertEqual(self.run_cli("target-add", "acme", "accounts", "ap@example.com")[0], 0)
        code, out, _ = self.run_cli("targets", "acme")
        self.assertEqual(code, 0)
        self.assertIn("accounts", out)
        self.assertIn("ap@example.com", out)
        self.assertEqual(self.run_cli("target-add", "acme", "accounts", "x@example.com")[0], 1)
        self.assertEqual(self.run_cli("target-add", "acme", "Bad Name", "x@example.com")[0], 1)
        self.assertEqual(self.run_cli("target-delete", "acme", "accounts")[0], 0)
        self.assertEqual(self.run_cli("target-delete", "acme", "accounts")[0], 1)

    # ---- rules
    def test_rules_can_be_added_listed_switched_and_deleted(self):
        self.run_cli("target-add", "acme", "accounts", "ap@example.com")
        code, out, _ = self.run_cli("rule-add", "acme", "Invoices", "forward:accounts", "subject=invoice", "format=pdf")
        self.assertEqual(code, 0)
        rule = self.store.list_rules(self.company.id)[0]
        self.assertEqual((rule.name, rule.action, rule.target, [(c.field, c.pattern) for c in rule.conditions]),
                         ("Invoices", "forward", "accounts", [("subject", "invoice"), ("format", "pdf")]))
        self.assertIn(rule.id, out)
        code, out, _ = self.run_cli("rules", "acme")
        self.assertIn("Invoices", out)
        self.assertIn("forward:accounts", out)
        self.assertEqual(self.run_cli("rule-disable", "acme", rule.id)[0], 0)
        self.assertFalse(self.store.get_rule(self.company.id, rule.id).enabled)
        self.assertEqual(self.run_cli("rule-enable", "acme", rule.id)[0], 0)
        self.assertEqual(self.run_cli("rule-delete", "acme", rule.id)[0], 0)
        self.assertEqual(self.run_cli("rule-delete", "acme", rule.id)[0], 1)

    def test_bad_rules_are_refused_with_a_reason(self):
        for argv in (("rule-add", "acme", "R", "hold"), ("rule-add", "acme", "R", "explode", "subject=x"),
                     ("rule-add", "acme", "R", "hold", "subject"), ("rule-add", "acme", "R", "hold", "nofield=x"),
                     ("rule-add", "acme", "R", "hold", "subject=(a+)+$"), ("rule-add", "acme", "R", "forward:ghost", "subject=x"),
                     ("rule-add", "acme", "R", "hold:accounts", "subject=x")):
            code, _, err = self.run_cli(*argv)
            self.assertEqual(code, 1, argv)
            self.assertTrue(err.strip(), argv)
        self.assertEqual(self.store.list_rules(self.company.id), [])

    def test_a_pattern_may_contain_an_equals_sign(self):
        self.assertEqual(self.run_cli("rule-add", "acme", "R", "hold", "subject=a=b")[0], 0)
        self.assertEqual(self.store.list_rules(self.company.id)[0].conditions[0].pattern, "a=b")

    # ---- job actions
    def test_a_person_can_hold_close_and_reopen_a_job(self):
        job = self.ready_job()
        for action, status in (("hold", "held"), ("close", "closed"), ("reopen", "ready")):
            code, out, _ = self.run_cli("job-action", "acme", job.id, action)
            self.assertEqual(code, 0, action)
            self.assertEqual(self.store.get_job(self.company.id, job.id).status, status)

    def test_an_invalid_move_changes_nothing_and_says_what_is_allowed(self):
        job = self.ready_job()
        code, _, err = self.run_cli("job-action", "acme", job.id, "reopen")
        self.assertEqual(code, 1)
        self.assertIn("close", err)
        self.assertEqual(self.store.get_job(self.company.id, job.id).status, "ready")
        self.assertEqual(self.run_cli("job-action", "acme", job.id, "explode")[0], 1)
        self.assertEqual(self.run_cli("job-action", "acme", "nope", "close")[0], 1)

    def test_forward_queues_the_job_for_the_service_to_send(self):
        self.run_cli("target-add", "acme", "accounts", "ap@example.com")
        job = self.ready_job()
        code, out, _ = self.run_cli("job-action", "acme", job.id, "forward", "accounts")
        self.assertEqual(code, 0)
        self.assertIn("queued", out)
        self.assertEqual(self.store.get_job(self.company.id, job.id).forward_target, "accounts")
        self.assertEqual(self.run_cli("job-action", "acme", job.id, "forward", "ghost")[0], 1)
        self.assertEqual(self.run_cli("job-action", "acme", job.id, "forward")[0], 1)

    def test_reprocess_sends_the_job_back_to_extract(self):
        job = self.ready_job()
        self.assertEqual(self.run_cli("job-action", "acme", job.id, "reprocess")[0], 0)
        self.assertEqual(self.store.get_job(self.company.id, job.id).status, "extracting")

    # ---- conflicts
    def test_a_conflicted_job_is_marked_and_can_be_resolved_either_way(self):
        a = self.store.add_rule(self.company.id, "A", "hold", "", [])
        b = self.store.add_rule(self.company.id, "B", "close", "", [])
        job = self.ready_job(conflict=(a.id, b.id))
        _, out, _ = self.run_cli("jobs", "acme")
        self.assertIn("needs review", out)
        self.assertEqual(self.run_cli("resolve", "acme", job.id, a.id)[0], 0)
        got = self.store.get_job(self.company.id, job.id)
        self.assertEqual((got.status, got.rule_conflict), ("held", ()))
        job2 = self.ready_job("s2", conflict=(a.id, b.id))
        self.assertEqual(self.run_cli("resolve", "acme", job2.id, "none")[0], 0)
        got = self.store.get_job(self.company.id, job2.id)
        self.assertEqual((got.status, got.rule_conflict), ("ready", ()))
        job3 = self.ready_job("s3", conflict=(a.id, b.id))
        self.assertEqual(self.run_cli("resolve", "acme", job3.id, "not-one-of-them")[0], 1)
        self.assertEqual(self.store.get_job(self.company.id, job3.id).rule_conflict, (a.id, b.id))

    def test_names_from_mail_cannot_inject_terminal_codes(self):
        self.ready_job(subject="x\x1b[31m\x07")
        _, out, _ = self.run_cli("jobs", "acme")
        self.assertNotIn("\x1b", out)


if __name__ == "__main__":
    unittest.main()
