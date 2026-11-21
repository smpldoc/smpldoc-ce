from dataclasses import dataclass, field

VERDICTS = ("pass", "fail", "unknown")
# Job statuses. received/extracting are unfinished; held, done and failed are resting states.
PENDING = ("received", "extracting")


@dataclass(frozen=True)
class Inbound:
    """One message waiting at a MailIn adapter. `verdict` is the one normalised sender check."""
    id: str
    receipt: str
    sender: str
    recipient: str
    verdict: str
    size: int


@dataclass(frozen=True)
class Company:
    id: str
    slug: str
    name: str


@dataclass(frozen=True)
class NewDocument:
    filename: str
    content_type: str
    blob_key: str
    size: int
    kind: str = "attachment"  # "body" for the message text, otherwise "attachment"


@dataclass(frozen=True)
class Document:
    id: str
    company_id: str
    job_id: str
    filename: str
    content_type: str
    blob_key: str
    size: int
    kind: str = "attachment"


@dataclass(frozen=True)
class Job:
    id: str
    company_id: str
    source_id: str
    status: str
    sender: str
    subject: str
    raw_key: str
    error: str
    created_at: str
    recipient: str = ""
    rule_conflict: tuple = ()  # ids of rules that matched but disagreed: a person must choose
    forward_target: str = ""  # a queued forward, until it is sent or fails


@dataclass(frozen=True)
class NewValue:
    document_id: str
    name: str
    value: str


@dataclass(frozen=True)
class FieldValue:
    company_id: str
    job_id: str
    document_id: str
    name: str
    value: str


@dataclass(frozen=True)
class Event:
    company_id: str
    job_id: str
    step: str
    outcome: str
    attempt: int
    detail: str
    at: str


@dataclass(frozen=True)
class Condition:
    field: str
    pattern: str


@dataclass(frozen=True)
class Rule:
    id: str
    company_id: str
    name: str
    action: str  # review | hold | close | forward
    target: str  # forward target name, only for forward
    enabled: bool
    conditions: tuple
    created_at: str


@dataclass(frozen=True)
class Target:
    company_id: str
    name: str
    address: str


@dataclass(frozen=True)
class Attachment:
    filename: str
    content_type: str
    data: bytes = field(repr=False)


@dataclass(frozen=True)
class OutgoingMail:
    to: str
    subject: str
    text: str
    attachments: tuple = ()
