"""Operator commands for rules, forward targets and job moves (a portal comes later). Everything printed
that came from mail or from a rule is cleaned of terminal control characters."""
import re

from smpldoc.domain.deliver import valid_address, valid_name
from smpldoc.domain.errors import RuleError
from smpldoc.domain.models import Condition
from smpldoc.domain.rules import ACTIONS, validate_rule
from smpldoc.domain.workflow import TransitionError, allowed_actions, next_status

CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
COMMANDS = {"rules", "rule-add", "rule-enable", "rule-disable", "rule-delete", "targets", "target-add", "target-delete", "job-action", "resolve"}


def clean(text, limit=200):
    """Mail text is untrusted: no terminal control characters reach an operator's screen."""
    return CONTROL.sub("?", str(text))[:limit]


def run_admin(command, args, store, out, err) -> int:
    def say(msg):
        print(msg, file=out)

    def fail(msg):
        print(msg, file=err)
        return 1

    if not args:
        return fail(f"usage: {command} COMPANY ...")
    company = store.find_company_by_slug(args[0])
    if company is None:
        return fail(f"no company {clean(args[0], 63)!r}")
    rest, cid = args[1:], company.id

    # ---- targets
    if command == "targets":
        for t in store.list_targets(cid):
            say(f"{clean(t.name, 41)}  {clean(t.address, 254)}")
        return 0
    if command == "target-add":
        if len(rest) != 2:
            return fail("usage: target-add COMPANY NAME EMAIL")
        try:
            store.add_target(cid, rest[0], rest[1])
        except ValueError as e:
            return fail(str(e))
        say(f"target {rest[0]} added")
        return 0
    if command == "target-delete":
        if len(rest) != 1:
            return fail("usage: target-delete COMPANY NAME")
        if not store.delete_target(cid, rest[0]):
            return fail("no such target")
        say(f"target {clean(rest[0], 41)} deleted (rules that forward to it will fail until you add it back)")
        return 0

    # ---- rules
    if command == "rules":
        for r in store.list_rules(cid):
            move = f"{r.action}:{r.target}" if r.target else r.action
            conds = "; ".join(f"{c.field}~{clean(c.pattern, 60)}" for c in r.conditions)
            say(f"{r.id}  {'on ' if r.enabled else 'off'}  {clean(r.name, 60)}  ->  {clean(move, 60)}  if {conds}")
        return 0
    if command == "rule-add":
        if len(rest) < 3:
            return fail(f"usage: rule-add COMPANY NAME ACTION FIELD=REGEX ...   (ACTION: {', '.join(a for a in ACTIONS if a != 'forward')}, or forward:TARGET)")
        name, action_arg, raw = rest[0], rest[1], rest[2:]
        action, _, target = action_arg.partition(":")
        conditions = []
        for item in raw:
            field, eq, pattern = item.partition("=")
            if not eq:
                return fail(f"a condition looks like FIELD=REGEX, not {clean(item, 40)!r}")
            conditions.append((field, pattern))
        try:
            name, action, target, conds = validate_rule(name, action, conditions, target)
            if action == "forward" and store.get_target(cid, target) is None:
                return fail(f"no forward target named {target!r}: add it with target-add first")
            rule = store.add_rule(cid, name, action, target, conds)
        except (RuleError, ValueError) as e:
            return fail(str(e))
        say(f"rule {rule.id} added")
        return 0
    if command in ("rule-enable", "rule-disable", "rule-delete"):
        if len(rest) != 1:
            return fail(f"usage: {command} COMPANY RULE_ID")
        done = store.delete_rule(cid, rest[0]) if command == "rule-delete" else store.set_rule_enabled(cid, rest[0], command == "rule-enable")
        if not done:
            return fail("no such rule")
        say("ok")
        return 0

    # ---- job moves
    if len(rest) < 1:
        return fail(f"usage: {command} COMPANY JOB_ID ...")
    job = store.get_job(cid, rest[0])
    if job is None:
        return fail("no such job")

    def apply(action, target=""):
        try:
            to = next_status(job.status, action)
        except TransitionError as e:
            return fail(f"{e}; allowed now: {', '.join(allowed_actions(job.status)) or 'nothing'}")
        if action == "forward":
            if store.get_target(cid, target) is None:
                return fail(f"no forward target named {clean(target, 41)!r}")
            ok = store.move_job(cid, job.id, [job.status], to, forward_target=target)
            say("queued for delivery: the running service sends it within its poll interval" if ok else "the job changed; look again")
            return 0 if ok else 1
        ok = store.move_job(cid, job.id, [job.status], to)
        say(f"job is now {to}" if ok else "the job changed; look again")
        return 0 if ok else 1

    if command == "job-action":
        if len(rest) < 2:
            return fail("usage: job-action COMPANY JOB_ID ACTION [TARGET]")
        action = rest[1]
        if action == "forward" and len(rest) != 3:
            return fail("usage: job-action COMPANY JOB_ID forward TARGET")
        return apply(action, rest[2] if len(rest) > 2 else "")
    if command == "resolve":
        if len(rest) != 2 or not job.rule_conflict:
            return fail("usage: resolve COMPANY JOB_ID RULE_ID|none   (only for a job that needs review)")
        if rest[1] == "none":
            ok = store.move_job(cid, job.id, [job.status], job.status)
            say("flag cleared; the job stays as it is" if ok else "the job changed; look again")
            return 0 if ok else 1
        if rest[1] not in job.rule_conflict:
            return fail("that rule is not one of the rules that matched this job")
        rule = store.get_rule(cid, rest[1])
        if rule is None:
            return fail("that rule no longer exists")
        if rule.action == "review":  # already ready: just clear the flag
            ok = store.move_job(cid, job.id, [job.status], job.status)
            say("flag cleared" if ok else "the job changed; look again")
            return 0 if ok else 1
        return apply(rule.action, rule.target)
    return fail("unknown command")
