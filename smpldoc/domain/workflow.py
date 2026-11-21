"""Job moves. Same rules the old product used, on smpldoc-ce's statuses:
received -> extracting -> ready (a person decides) | held | closed | done (forwarded) | failed."""
from .errors import SmpldocError

TABLE = {
    "review": {"received": "ready", "held": "ready", "failed": "ready"},
    "hold": {"received": "held", "ready": "held", "failed": "held"},
    "close": {"received": "closed", "extracting": "closed", "ready": "closed", "held": "closed", "failed": "closed"},
    "reopen": {"closed": "ready"},
    "reprocess": {"extracting": "extracting", "ready": "extracting", "held": "extracting", "failed": "extracting",
                  "closed": "extracting", "done": "extracting"},
    "forward": {"ready": "ready"},  # stays ready until the mail is actually sent
}


class TransitionError(SmpldocError):
    pass


def next_status(status: str, action: str) -> str:
    try:
        return TABLE[action][status]
    except KeyError:
        raise TransitionError(f"cannot {action} a job that is {status}") from None


def allowed_actions(status: str) -> list:
    return sorted(a for a, moves in TABLE.items() if status in moves)
