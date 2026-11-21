"""Run rule evaluation in a short-lived subprocess with a hard time limit. Python's regex engine cannot
be interrupted, so a pattern that backtracks forever would freeze the whole service; here it only costs
one killed child process and one `RuleTimeout`."""
import subprocess
import sys
from pathlib import Path

from smpldoc.domain.errors import RuleTimeout, SmpldocError
from smpldoc.domain.rules import decision_from_json, to_json

ROOT = str(Path(__file__).resolve().parents[2])  # the folder that holds the `smpldoc` package
CODE = ("import sys; sys.path.insert(0, sys.argv[1]); from smpldoc.domain.rules import evaluate_json; "
        "sys.stdout.write(evaluate_json(sys.stdin.read()))")


class GuardedEvaluator:
    def __init__(self, timeout=2.0):
        self.timeout = timeout

    def __call__(self, rules, facts):
        try:
            done = subprocess.run([sys.executable, "-I", "-B", "-c", CODE, ROOT], input=to_json(rules, facts).encode(),
                                  capture_output=True, timeout=self.timeout, env={"LANG": "C.UTF-8"})
        except subprocess.TimeoutExpired:
            raise RuleTimeout("rule evaluation timed out") from None
        if done.returncode != 0:
            raise SmpldocError("rule evaluation failed")
        try:
            return decision_from_json(done.stdout.decode())
        except (ValueError, KeyError):
            raise SmpldocError("rule evaluation returned something unreadable") from None
