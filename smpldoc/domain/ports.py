"""The ports. The core talks to the outside world only through these; adapters implement them.
Every adapter must pass the shared contract tests in tests/contracts.py."""
from typing import Optional, Protocol, Sequence

from .models import (Company, Document, Event, FieldValue, Inbound, Job, NewDocument, NewValue, OutgoingMail, Rule, Target)


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


class MailOut(Protocol):
    def send(self, mail: OutgoingMail) -> str:
        """Send one message and return its Message-ID. Raises SendError(permanent=...)."""


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
                   status: str, documents: Sequence[NewDocument], recipient: str = "") -> tuple[Job, bool]:
        """Idempotent on (company, source_id): returns (job, created). Job and documents are one
        atomic write."""
    def get_job(self, company_id: str, job_id: str) -> Optional[Job]: ...
    def list_jobs(self, company_id: str, status: Optional[str] = None) -> list[Job]: ...
    def list_pending(self) -> list[Job]: ...
    def set_status(self, company_id: str, job_id: str, status: str, error: str = "") -> None: ...
    def list_documents(self, company_id: str, job_id: str) -> list[Document]: ...
    def complete_job(self, company_id: str, job_id: str, values: Sequence[NewValue], status: str = "ready",
                     conflict: Sequence[str] = (), forward_target: str = "") -> bool:
        """Atomically replace the job's values and set its next status (ready, held or closed), a rule
        conflict and a queued forward. False if the job was not unfinished."""
    def move_job(self, company_id: str, job_id: str, from_statuses: Sequence[str], to_status: str,
                 forward_target: Optional[str] = None, clear_conflict: bool = True) -> bool:
        """Compare-and-set a status. False if the job was not in one of `from_statuses`."""
    def list_to_deliver(self) -> list[Job]: ...
    def settle_delivery(self, company_id: str, job_id: str, ok: bool, error: str = "") -> bool: ...
    def add_rule(self, company_id: str, name: str, action: str, target: str, conditions: Sequence, enabled: bool = True) -> Rule: ...
    def list_rules(self, company_id: str, enabled_only: bool = False) -> list[Rule]: ...
    def get_rule(self, company_id: str, rule_id: str) -> Optional[Rule]: ...
    def set_rule_enabled(self, company_id: str, rule_id: str, enabled: bool) -> bool: ...
    def delete_rule(self, company_id: str, rule_id: str) -> bool: ...
    def add_target(self, company_id: str, name: str, address: str) -> Target: ...
    def get_target(self, company_id: str, name: str) -> Optional[Target]: ...
    def list_targets(self, company_id: str) -> list[Target]: ...
    def delete_target(self, company_id: str, name: str) -> bool: ...
    def list_field_values(self, company_id: str, job_id: str) -> list[FieldValue]: ...
    def add_event(self, company_id: str, job_id: str, step: str, outcome: str,
                  attempt: int = 1, detail: str = "") -> None: ...
    def list_events(self, company_id: str, job_id: str) -> list[Event]: ...
