import unittest

from smpldoc.domain.rules import (ACTIONS, FIELDS, MAX_CONDITIONS, MAX_PATTERN, Facts, RuleError, evaluate, validate_rule)
from smpldoc.domain.models import Condition, Rule


def rule(name="r", action="hold", conds=(("subject", "invoice"),), target="", enabled=True, rid="r1"):
    return Rule(rid, "c1", name, action, target, enabled, tuple(Condition(f, p) for f, p in conds), "t")


FACTS = Facts(sender="Billing <billing@vendor.test>", recipient="acme@in.test", subject="March Invoice 42",
              body="Please pay by Friday.", attachments=(("inv-42.PDF", "application/pdf"), ("notes.txt", "text/plain")))


class ValidateTest(unittest.TestCase):
    def ok(self, **kw):
        args = dict(name="R", action="hold", conditions=[("subject", "x")], target="")
        args.update(kw)
        return validate_rule(**args)

    def test_a_good_rule(self):
        name, action, target, conds = self.ok(name="  Invoices  ")
        self.assertEqual((name, action, target, conds), ("Invoices", "hold", "", (Condition("subject", "x"),)))

    def test_the_constants(self):
        self.assertEqual(set(FIELDS), {"from", "to", "subject", "body", "filename", "format"})
        self.assertEqual(set(ACTIONS), {"review", "hold", "close", "forward"})

    def test_bad_rules_are_refused_with_a_reason(self):
        bad = [dict(name=""), dict(name="   "), dict(action="delete"), dict(conditions=[]),
               dict(conditions=[("subject", "x")] * (MAX_CONDITIONS + 1)), dict(conditions=[("nope", "x")]),
               dict(conditions=[("subject", "")]), dict(conditions=[("subject", "x" * (MAX_PATTERN + 1))]),
               dict(conditions=[("subject", "(unclosed")]), dict(conditions=[("subject", "(a+)+$")]),
               dict(conditions=[("subject", "(a|aa)+$")]), dict(conditions=[("subject", "(\\w*)*")]),
               dict(conditions=[("subject", "(x+){2,}")]), dict(conditions=[("subject", "(?=a)+")]),
               dict(conditions=[("subject", "(a)\\1")]),
               dict(action="forward", target=""), dict(action="hold", target="accounts"),
               dict(action="forward", target="Bad Name")]
        for kw in bad:
            with self.assertRaises(RuleError, msg=str(kw)):
                self.ok(**kw)

    def test_a_forward_rule_needs_a_target_name(self):
        self.assertEqual(self.ok(action="forward", target="accounts")[2], "accounts")

    def test_ordinary_patterns_are_fine(self):
        for p in (r"\.(pdf|docx)$", r"^invoice \d+", r"@vendor\.test", r"(foo|bar)", r"a{2,3}", r"[a-z]+@[a-z]+\.com"):
            self.ok(conditions=[("filename", p)])


class EvaluateTest(unittest.TestCase):
    def test_no_rules_or_no_match_leaves_the_job_alone(self):
        self.assertEqual(evaluate([], FACTS).kind, "none")
        self.assertEqual(evaluate([rule(conds=[("subject", "refund")])], FACTS).kind, "none")

    def test_every_condition_must_match_and_case_is_ignored(self):
        r = rule(conds=[("subject", "INVOICE"), ("from", r"billing@vendor\.test")])
        self.assertEqual(evaluate([r], FACTS).kind, "move")
        r2 = rule(conds=[("subject", "invoice"), ("from", "nobody")])
        self.assertEqual(evaluate([r2], FACTS).kind, "none")

    def test_every_field(self):
        for field, pattern in (("from", "vendor"), ("to", "^acme@"), ("subject", "march"), ("body", "friday"),
                               ("filename", r"inv-\d+\.pdf"), ("format", "application/pdf"), ("format", r"^pdf$"), ("format", "^txt$")):
            self.assertEqual(evaluate([rule(conds=[(field, pattern)])], FACTS).kind, "move", f"{field}:{pattern}")

    def test_attachment_fields_need_at_least_one_attachment_to_match(self):
        none = Facts("a@b.test", "c@d.test", "s", "b", ())
        self.assertEqual(evaluate([rule(conds=[("filename", ".")])], none).kind, "none")
        self.assertEqual(evaluate([rule(conds=[("format", "pdf")])], none).kind, "none")

    def test_a_missing_single_value_is_an_empty_string(self):
        empty = Facts("", "", "", "", ())
        self.assertEqual(evaluate([rule(conds=[("subject", "^$")])], empty).kind, "move")
        self.assertEqual(evaluate([rule(conds=[("subject", ".")])], empty).kind, "none")

    def test_disabled_rules_never_match(self):
        self.assertEqual(evaluate([rule(enabled=False)], FACTS).kind, "none")

    def test_matches_that_agree_make_one_move(self):
        d = evaluate([rule(rid="a", action="hold"), rule(rid="b", action="hold", conds=[("from", "vendor")])], FACTS)
        self.assertEqual((d.kind, d.action, d.matched), ("move", "hold", ("a", "b")))

    def test_matches_that_disagree_are_a_conflict_nothing_moves(self):
        d = evaluate([rule(rid="a", action="hold"), rule(rid="b", action="close", conds=[("from", "vendor")])], FACTS)
        self.assertEqual((d.kind, d.matched), ("conflict", ("a", "b")))

    def test_forwards_to_different_targets_disagree(self):
        a = rule(rid="a", action="forward", target="ap")
        b = rule(rid="b", action="forward", target="legal")
        self.assertEqual(evaluate([a, b], FACTS).kind, "conflict")
        self.assertEqual(evaluate([a, rule(rid="c", action="forward", target="ap")], FACTS).kind, "move")
        d = evaluate([a], FACTS)
        self.assertEqual((d.action, d.target), ("forward", "ap"))

    def test_inputs_are_truncated_before_matching(self):
        far = Facts("a@b.test", "c@d.test", "x" * 1500 + "NEEDLE", "y" * 20_500 + "NEEDLE", ())
        self.assertEqual(evaluate([rule(conds=[("subject", "NEEDLE")])], far).kind, "none")
        self.assertEqual(evaluate([rule(conds=[("body", "NEEDLE")])], far).kind, "none")
        near = Facts("a@b.test", "c@d.test", "x" * 900 + "NEEDLE", "y" * 19_000 + "NEEDLE", ())
        self.assertEqual(evaluate([rule(conds=[("subject", "NEEDLE")])], near).kind, "move")
        self.assertEqual(evaluate([rule(conds=[("body", "NEEDLE")])], near).kind, "move")


if __name__ == "__main__":
    unittest.main()
