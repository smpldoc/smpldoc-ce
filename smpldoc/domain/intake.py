"""Turn raw mail bytes into documents. Mail and attachments are data: nothing here runs them."""
import email
import re
from dataclasses import dataclass
from email import policy
from typing import Optional

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class Part:
    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True)
class ParsedMail:
    message_id: str
    subject: str
    parts: list


def slug_from_recipient(recipient: str) -> Optional[str]:
    """acme@in.test and Acme+tag@in.test both mean the company `acme`."""
    local, at, _ = recipient.partition("@")
    slug = local.split("+")[0].strip().lower()
    return slug if at and slug else None


def safe_filename(name: str) -> str:
    base = _CONTROL.sub("", (name or "")).replace("\\", "/").split("/")[-1].strip()
    return base[:255] if base and base not in {".", ".."} else "unnamed"


def parse_mail(raw: bytes) -> ParsedMail:
    msg = email.message_from_bytes(raw, policy=policy.default)
    parts, body = [], []
    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        try:
            data = part.get_payload(decode=True) or b""
        except Exception:
            continue
        if filename:
            parts.append(Part(safe_filename(filename), part.get_content_type(), data))
        elif part.get_content_type() == "text/plain":
            body.append(data.decode(part.get_content_charset() or "utf-8", errors="replace"))
    text = "\n".join(b for b in body if b.strip())
    if text:
        parts.insert(0, Part("body.txt", "text/plain", text.encode()))
    mid = _CONTROL.sub("", str(msg.get("Message-ID", "") or "")).strip()[:500]
    return ParsedMail(mid, _CONTROL.sub(" ", str(msg.get("Subject", "") or ""))[:500], parts)
