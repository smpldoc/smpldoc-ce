"""The job pipeline: ingest -> extract -> close. Each step is retried with backoff and writes a
step event. Unfinished jobs resume after a crash. Nothing here imports a cloud library."""
import time
from dataclasses import dataclass

from .errors import SmpldocError
from .intake import parse_mail, slug_from_recipient
from .models import Inbound, NewDocument, NewValue


class StepFailed(SmpldocError):
    pass


@dataclass
class RunSummary:
    completed: int = 0
    failed: int = 0
    held: int = 0
    skipped: int = 0
    rejected: int = 0
    deferred: int = 0


class Runner:
    def __init__(self, mail_in, store, blob, extractor, *, sleep=time.sleep,
                 max_attempts=3, base_delay=1.0, batch=10):
        self.mail, self.store, self.blob, self.extractor = mail_in, store, blob, extractor
        self.sleep, self.max_attempts, self.base_delay, self.batch = sleep, max_attempts, base_delay, batch

    def run_once(self) -> RunSummary:
        summary = RunSummary()
        for job in self.store.list_pending():  # finish work a crash left behind
            self._finish(job, summary)
        for message in self.mail.poll(self.batch):
            self._ingest(message, summary)
        return summary

    # ---- ingest -------------------------------------------------------------------------
    def _ingest(self, message: Inbound, summary: RunSummary) -> None:
        slug = slug_from_recipient(message.recipient)
        company = self.store.find_company_by_slug(slug) if slug else None
        if company is None:
            self.mail.ack(message)  # nothing to attach a job to; do not loop on it
            summary.rejected += 1
            return
        try:
            raw = self.mail.fetch(message)
        except Exception:
            self.mail.nack(message)  # transient: let the adapter hand it out again
            summary.deferred += 1
            return
        parsed = parse_mail(raw)
        raw_key = self.blob.put(company.id, raw)
        docs = [NewDocument(p.filename, p.content_type, self.blob.put(company.id, p.data), len(p.data))
                for p in parsed.parts]
        held = message.verdict != "pass"
        source = f"mid:{parsed.message_id}" if parsed.message_id else f"in:{message.id}"
        job, created = self.store.create_job(company.id, source, message.sender, parsed.subject, raw_key,
                                             "held" if held else "received", docs)
        outcome = "skipped" if not created else "held" if held else "ok"
        self.store.add_event(company.id, job.id, "ingest", outcome)
        self.mail.ack(message)
        if not created:
            summary.skipped += 1
        elif held:
            summary.held += 1
        else:
            self._finish(job, summary)

    # ---- extract and close --------------------------------------------------------------
    def _finish(self, job, summary: RunSummary) -> None:
        try:
            if job.status == "received":
                self.store.set_status(job.company_id, job.id, "extracting")
            values = self._retry(job, "extract", lambda: self._extract(job))
            self._retry(job, "close", lambda: self.store.complete_job(job.company_id, job.id, values))
            summary.completed += 1
        except StepFailed as failure:
            self.store.set_status(job.company_id, job.id, "failed", str(failure))
            summary.failed += 1

    def _extract(self, job) -> list[NewValue]:
        values = []
        for doc in self.store.list_documents(job.company_id, job.id):
            data = self.blob.get(job.company_id, doc.blob_key)
            values += [NewValue(doc.id, name, value)
                       for name, value in self.extractor.extract(doc.filename, doc.content_type, data)]
        return values

    def _retry(self, job, step, action):
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = action()
            except Exception as exc:  # a crash (BaseException) is deliberately not caught
                name = type(exc).__name__  # the message may hold document text: never store it
                if attempt == self.max_attempts:
                    self.store.add_event(job.company_id, job.id, step, "failed", attempt, name)
                    raise StepFailed(name) from None
                self.store.add_event(job.company_id, job.id, step, "retry", attempt, name)
                self.sleep(self.base_delay * 2 ** (attempt - 1))
            else:
                self.store.add_event(job.company_id, job.id, step, "ok", attempt)
                return result
