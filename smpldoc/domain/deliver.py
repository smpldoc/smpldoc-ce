"""Build the email that forwards a job. Everything in it that came from the original mail is untrusted:
control characters are stripped so nothing can add a header or escape code, and sizes are capped."""
import re
from typing import Sequence

from .errors import ForwardError
from .models import Attachment, OutgoingMail

ADDRESS = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
MAX_BODY, MAX_VALUE_LINES = 20_000, 50


def valid_address(address: str) -> bool:
    return bool(address) and len(address) <= 254 and ADDRESS.fullmatch(address) is not None


def valid_name(name: str) -> bool:
    return NAME.fullmatch(name or "") is not None


def _line(text, limit=200) -> str:
    return " ".join(CONTROL.sub(" ", str(text or "")).split())[:limit]


def build_outgoing(*, job_id, sender, subject, recipient, received, label, to, attachments: Sequence[Attachment],
                   values, body, max_bytes, max_files) -> OutgoingMail:
    if not valid_address(to):
        raise ForwardError("the forward target is not a valid address")
    total = sum(len(a.data) for a in attachments)
    if total > max_bytes or len(attachments) > max_files:
        raise ForwardError(f"too much to email ({total} bytes in {len(attachments)} files; limit {max_bytes} bytes, {max_files} files)")
    lines = [f"{_line(label, 80)} - forwarded by smpldoc.", "",
             f"Job ID: {_line(job_id, 40)}", f"From: {_line(sender)}", f"Subject: {_line(subject) or '(no subject)'}",
             f"Received at: {_line(recipient, 100)}, {_line(received, 40)}",
             f"Files: {', '.join(_line(a.filename, 80) for a in attachments) or 'none'}"]
    if values:
        lines += ["", "Extracted values:"] + [f"  {_line(k, 60)}: {_line(v, 100)}" for k, v in list(values)[:MAX_VALUE_LINES]]
    text = (body or "")[:MAX_BODY].replace("\x00", "")
    if text.strip():
        lines += ["", "---- Original message ----", text]
    return OutgoingMail(to, _line(subject) or "(no subject)", "\n".join(lines), tuple(attachments))
