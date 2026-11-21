"""Routing rules. A rule is a name, 1 to 10 conditions (a field plus a case-insensitive regex) and one
move. Every condition must match. Moves: review, hold, close, forward (to a named target). Rules that
match and agree make one move; rules that match and disagree move nothing and flag the job for a person.

Pure: no I/O. User patterns are screened when saved (length, nested repeats, alternation inside a
repeat, back-references) and inputs are truncated before matching. Python's regex engine cannot be
interrupted, so the service evaluates in a time-limited subprocess (adapters/rules_guard.py)."""
import json
import re
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from .errors import RuleError
from .models import Condition, Rule

FIELDS = ("from", "to", "subject", "body", "filename", "format")
ACTIONS = ("review", "hold", "close", "forward")
MAX_PATTERN, MAX_CONDITIONS = 200, 10
MAX_BODY, MAX_FIELD = 20_000, 1_000
TARGET_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


@dataclass(frozen=True)
class Facts:
    sender: str
    recipient: str
    subject: str
    body: str
    attachments: tuple  # ((filename, mime), ...)


@dataclass(frozen=True)
class Decision:
    kind: str  # none | move | conflict
    action: str = ""
    target: str = ""
    matched: tuple = ()


def _unsafe(pattern: str) -> Optional[str]:
    """Reject the shapes that make backtracking explode: a repeated group that itself repeats, branches
    or holds another group, a repeated look-around, and back-references."""
    groups, i, n = [], 0, len(pattern)  # each entry: [is_lookaround, is_risky]
    while i < n:
        c = pattern[i]
        if c == "\\":
            if i + 1 < n and pattern[i + 1] in "123456789":
                return "back-references are not allowed"
            i += 2
            continue
        if c == "[":  # skip a character class
            i += 1
            if i < n and pattern[i] == "^":
                i += 1
            if i < n and pattern[i] == "]":
                i += 1
            while i < n and pattern[i] != "]":
                i += 2 if pattern[i] == "\\" else 1
            i += 1
            continue
        if c == "(":
            if groups:
                groups[-1][1] = True  # a group inside a group
            if pattern.startswith("(?P=", i):
                return "back-references are not allowed"
            look = pattern.startswith(("(?=", "(?!", "(?<=", "(?<!"), i)
            groups.append([look, False])
            i += 3 if pattern.startswith("(?", i) and not look else 1
            continue
        if c == ")" and groups:
            look, risky = groups.pop()
            nxt = pattern[i + 1] if i + 1 < n else ""
            if look and nxt in ("+", "*", "{", "?"):
                return "a repeated look-around is not allowed"
            if risky and nxt in ("+", "*", "{"):
                return "nested repeats like (a+)+ are not allowed"
            if groups and risky:
                groups[-1][1] = True
        elif groups and c in "+*{|?":
            groups[-1][1] = True
        i += 1
    return None


def validate_rule(name, action, conditions, target=""):
    """Return (name, action, target, conditions) cleaned, or raise RuleError with a reason."""
    name = (name or "").strip()[:100]
    if not name:
        raise RuleError("a rule needs a name")
    if action not in ACTIONS:
        raise RuleError(f"action must be one of {', '.join(ACTIONS)}")
    if action == "forward":
        if not TARGET_NAME.match(target or ""):
            raise RuleError("a forward rule needs the name of a forward target")
    elif target:
        raise RuleError("only a forward rule has a target")
    if not conditions:
        raise RuleError("at least one condition is required")
    if len(conditions) > MAX_CONDITIONS:
        raise RuleError(f"at most {MAX_CONDITIONS} conditions")
    out = []
    for i, c in enumerate(conditions, 1):
        field, pattern = (c.field, c.pattern) if isinstance(c, Condition) else c
        if field not in FIELDS:
            raise RuleError(f"condition {i}: field must be one of {', '.join(FIELDS)}")
        if not pattern:
            raise RuleError(f"condition {i}: a pattern is required")
        if len(pattern) > MAX_PATTERN:
            raise RuleError(f"condition {i}: pattern longer than {MAX_PATTERN} characters")
        problem = _unsafe(pattern)
        if problem:
            raise RuleError(f"condition {i}: {problem}")
        try:
            re.compile(pattern, re.IGNORECASE)
        except (re.error, RecursionError, OverflowError):
            raise RuleError(f"condition {i}: not a valid regular expression") from None
        out.append(Condition(field, pattern))
    return name, action, target if action == "forward" else "", tuple(out)


def _values(field: str, f: Facts) -> list:
    cap = lambda s, n: (s or "")[:n]
    if field == "from":
        return [cap(f.sender, MAX_FIELD)]
    if field == "to":
        return [cap(f.recipient, MAX_FIELD)]
    if field == "subject":
        return [cap(f.subject, MAX_FIELD)]
    if field == "body":
        return [cap(f.body, MAX_BODY)]
    if field == "filename":
        return [cap(name, MAX_FIELD) for name, _ in f.attachments if name]
    out = []  # format: each attachment offers its mime type and its extension, so "pdf" and "application/pdf" both work
    for name, mime in f.attachments:
        ext = re.search(r"\.([a-z0-9]{1,10})$", name or "", re.IGNORECASE)
        out += [v for v in (cap(mime, MAX_FIELD), ext.group(1).lower() if ext else "") if v]
    return out


def _matches(rule: Rule, facts: Facts) -> bool:
    if not rule.enabled or not rule.conditions:
        return False
    for c in rule.conditions:
        try:
            rx = re.compile(c.pattern, re.IGNORECASE)
        except re.error:
            return False
        if not any(rx.search(v) for v in _values(c.field, facts)):
            return False
    return True


def evaluate(rules: Iterable[Rule], facts: Facts) -> Decision:
    hits = [r for r in rules if _matches(r, facts)]
    if not hits:
        return Decision("none")
    moves = {(r.action, r.target) for r in hits}
    ids = tuple(r.id for r in hits)
    if len(moves) > 1:
        return Decision("conflict", matched=ids)
    action, target = next(iter(moves))
    return Decision("move", action, target, ids)


# ---- JSON wire format, used to run evaluate in a separate process --------------------------
def to_json(rules: Sequence[Rule], facts: Facts) -> str:
    return json.dumps({
        "rules": [{"id": r.id, "action": r.action, "target": r.target, "enabled": r.enabled,
                   "conditions": [[c.field, c.pattern] for c in r.conditions]} for r in rules],
        "facts": {"sender": facts.sender, "recipient": facts.recipient, "subject": facts.subject, "body": facts.body,
                  "attachments": [list(a) for a in facts.attachments]}})


def evaluate_json(text: str) -> str:
    raw = json.loads(text)
    rules = [Rule(r["id"], "", "", r["action"], r["target"], r["enabled"], tuple(Condition(f, p) for f, p in r["conditions"]), "")
             for r in raw["rules"]]
    f = raw["facts"]
    d = evaluate(rules, Facts(f["sender"], f["recipient"], f["subject"], f["body"], tuple(tuple(a) for a in f["attachments"])))
    return json.dumps({"kind": d.kind, "action": d.action, "target": d.target, "matched": list(d.matched)})


def decision_from_json(text: str) -> Decision:
    d = json.loads(text)
    return Decision(d["kind"], d["action"], d["target"], tuple(d["matched"]))
