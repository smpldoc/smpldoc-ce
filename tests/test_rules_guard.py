import time
import unittest

from smpldoc.adapters.rules_guard import GuardedEvaluator
from smpldoc.domain.errors import RuleTimeout
from smpldoc.domain.models import Condition, Rule
from smpldoc.domain.rules import Facts, evaluate

FACTS = Facts("a@b.test", "c@d.test", "March Invoice", "pay", (("x.pdf", "application/pdf"),))


def rule(rid, action, *conds):
    return Rule(rid, "c", rid, action, "ap" if action == "forward" else "", True, tuple(Condition(f, p) for f, p in conds), "t")


class GuardTest(unittest.TestCase):
    def test_it_gives_the_same_answer_as_evaluating_in_process(self):
        rules = [rule("a", "hold", ("subject", "invoice")), rule("b", "forward", ("format", "pdf")), rule("c", "close", ("from", "nobody"))]
        self.assertEqual(GuardedEvaluator(timeout=10)(rules, FACTS), evaluate(rules, FACTS))
        self.assertEqual(GuardedEvaluator(timeout=10)([], FACTS), evaluate([], FACTS))

    def test_a_catastrophic_pattern_is_cut_off_and_cannot_freeze_the_service(self):
        evil = rule("evil", "hold", ("subject", "(a*)*b"))  # saved rules are screened, this one bypasses that on purpose
        facts = Facts("", "", "a" * 40, "", ())
        t = time.monotonic()
        with self.assertRaises(RuleTimeout):
            GuardedEvaluator(timeout=1)([evil], facts)
        self.assertLess(time.monotonic() - t, 5)

    def test_it_recovers_after_a_timeout(self):
        g = GuardedEvaluator(timeout=1)
        with self.assertRaises(RuleTimeout):
            g([rule("evil", "hold", ("subject", "(a*)*b"))], Facts("", "", "a" * 40, "", ()))
        self.assertEqual(g([rule("a", "hold", ("subject", "invoice"))], FACTS).kind, "move")


if __name__ == "__main__":
    unittest.main()
