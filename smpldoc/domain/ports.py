"""The ports. The core talks to the outside world only through these; adapters implement them.
Every adapter must pass the shared contract tests in tests/contracts.py."""
from typing import Optional, Protocol, Sequence

from .models import (Company, Document, Event, FieldValue, Inbound, Job, NewDocument, NewValue)


class MailIn(Protocol):
    def poll(self, limit: int) -> list[Inbound]:
        """Hand out up to `limit` messages. A handed-out message is in flight: not given again
        until it is nacked (or the adapter's lease runs out)."""

    def fetch(self, message: Inbound) -> bytes:
        """The exact raw RFC 822 bytes."""

    def ack(self, message: Inbound) -> None:
        """Done with it for good."""

    def nack(self, message: Inbound) -> None:
        """Give it back so it is delivered again."""


class Blob(Protocol):
    def put(self, company_id: str, data: bytes) -> str:
        """Store bytes. The key is the sha256 hex of the content, so storing twice is harmless."""

    def get(self, company_id: str, key: str) -> bytes:
        """Raises KeyError for an unknown key, another company's key or a malformed key."""


class Extractor(Protocol):
    def extract(self, filename: str, content_type: str, data: bytes) -> list[tuple[str, str]]:
        """Return (field name, value) pairs. Raise ExtractError if the document cannot be read."""


class Store(Protocol):
    """Every method takes the company id and reads or writes only that company's rows.
    The one exception is list_pending, which the runner uses to resume unfinished work."""

    def add_company(self, slug: str, name: str) -> Company: ...
    def find_company_by_slug(self, slug: str) -> Optional[Company]: ...
    def create_job(self, company_id: str, source_id: str, sender: str, subject: str, raw_key: str,
                   status: str, documents: Sequence[NewDocument]) -> tuple[Job, bool]:
        """Idempotent on (company, source_id): returns (job, created). Job and documents are one
        atomic write."""
    def get_job(self, company_id: str, job_id: str) -> Optional[Job]: ...
    def list_jobs(self, company_id: str, status: Optional[str] = None) -> list[Job]: ...
    def list_pending(self) -> list[Job]: ...
    def set_status(self, company_id: str, job_id: str, status: str, error: str = "") -> None: ...
    def list_documents(self, company_id: str, job_id: str) -> list[Document]: ...
    def complete_job(self, company_id: str, job_id: str, values: Sequence[NewValue]) -> bool:
        """Atomically save the values and mark the job done. False if it was not unfinished."""
    def list_field_values(self, company_id: str, job_id: str) -> list[FieldValue]: ...
    def add_event(self, company_id: str, job_id: str, step: str, outcome: str,
                  attempt: int = 1, detail: str = "") -> None: ...
    def list_events(self, company_id: str, job_id: str) -> list[Event]: ...
