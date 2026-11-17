from dataclasses import dataclass

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


@dataclass(frozen=True)
class Document:
    id: str
    company_id: str
    job_id: str
    filename: str
    content_type: str
    blob_key: str
    size: int


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
