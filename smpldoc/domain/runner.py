"""The job pipeline: ingest -> extract -> bundle -> rules -> finish, then deliver when a forward is queued.
Each step is retried with backoff and writes a step event. Unfinished jobs and queued forwards resume
after a crash. Nothing here imports a cloud library."""
import time
from collections import Counter
from dataclasses import dataclass

from . import bundle_writer
from .deliver import build_outgoing
from .errors import ForwardError, SmpldocError
from .intake import parse_mail, slug_from_recipient
from .models import Attachment, Inbound, NewDocument, NewValue
from . import rules as rules_mod

STATUS_FOR = {"review": "ready", "hold": "held", "close": "closed", "forward": "ready"}


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
    delivered: int = 0
    delivery_failed: int = 0


class Runner:
    def __init__(self, mail_in, store, blob, extractor, *, bundles=None, mail_out=None, evaluate=None, sleep=time.sleep,
                 max_attempts=3, base_delay=1.0, batch=10, max_forward_bytes=10_000_000, max_forward_files=32):
        self.mail, self.store, self.blob, self.extractor = mail_in, store, blob, extractor
        self.bundles = bundles  # optional: with a BundleStore every readable document also becomes a bundle
        self.mail_out, self.evaluate = mail_out, evaluate or rules_mod.evaluate
        self.sleep, self.max_attempts, self.base_delay, self.batch = sleep, max_attempts, base_delay, batch
        self.max_forward_bytes, self.max_forward_files = max_forward_bytes, max_forward_files

    def run_once(self) -> RunSummary:
        summary = RunSummary()
        for job in self.store.list_pending():  # finish work a crash left behind
            self._finish(job, summary)
        for job in self.store.list_to_deliver():  # forwards a person or a crash left queued
            self._deliver(job, summary)
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
        docs = [NewDocument(p.filename, p.content_type, self.blob.put(company.id, p.data), len(p.data), p.kind) for p in parsed.parts]
        held = message.verdict != "pass"
        source = f"mid:{parsed.message_id}" if parsed.message_id else f"in:{message.id}"
        job, created = self.store.create_job(company.id, source, message.sender, parsed.subject, raw_key,
                                             "held" if held else "received", docs, recipient=message.recipient)
        outcome = "skipped" if not created else "held" if held else "ok"
        self.store.add_event(company.id, job.id, "ingest", outcome)
        self.mail.ack(message)
        if not created:
            summary.skipped += 1
        elif held:
            summary.held += 1
        else:
            self._finish(job, summary)

    # ---- extract, rules, finish ------------------------------------------------------------
    def _finish(self, job, summary: RunSummary) -> None:
        try:
            if job.status == "received":
                self.store.set_status(job.company_id, job.id, "extracting")
            values = self._retry(job, "extract", lambda: self._extract(job))
            if self.bundles is not None:
                self._retry(job, "bundle", lambda: self._bundle(job, values), detail=lambda note: note)
            decision = self._decide(job)
            status = "ready" if decision.kind == "conflict" else STATUS_FOR.get(decision.action, "ready")
            forward = decision.target if decision.kind == "move" and decision.action == "forward" else ""
            conflict = decision.matched if decision.kind == "conflict" else ()
            self._retry(job, "finish", lambda: self.store.complete_job(job.company_id, job.id, values, status=status,
                                                                       conflict=conflict, forward_target=forward))
            summary.completed += 1
        except StepFailed as failure:
            self.store.set_status(job.company_id, job.id, "failed", str(failure))
            summary.failed += 1
            return
        if forward:
            self._deliver(self.store.get_job(job.company_id, job.id), summary)

    def _extract(self, job) -> list:
        values = []
        for doc in self.store.list_documents(job.company_id, job.id):
            data = self.blob.get(job.company_id, doc.blob_key)
            values += [NewValue(doc.id, name, value) for name, value in self.extractor.extract(doc.filename, doc.content_type, data)]
        return values

    def _bundle(self, job, values) -> str:
        """One bundle per document (docs/BUNDLE_FORMAT.md). Attachments are the documents; the message text
        is one only when nothing is attached. The id is the document's id, so writing again after a crash
        or a reprocess replaces the same bundle. Returns a note for the step event: counts and codes only."""
        company = self.store.get_company(job.company_id)
        if company is None:
            raise StepFailed("UnknownCompany")
        docs = self.store.list_documents(job.company_id, job.id)
        chosen = [d for d in docs if d.kind != "body"] or docs
        pairs = {}
        for v in values:
            pairs.setdefault(v.document_id, []).append((v.name, v.value))
        written, skipped = 0, Counter()
        for doc in chosen:
            data = self.blob.get(job.company_id, doc.blob_key)
            files = bundle_writer.build(company=company.slug, bundle_id=doc.id, job_id=job.id, created_at=job.created_at,
                                        sender=job.sender, subject=job.subject, filename=doc.filename,
                                        content_type=doc.content_type, data=data, pairs=pairs.get(doc.id, []))
            if files is None:
                skipped[bundle_writer.skip_reason(doc.content_type, data)] += 1
                continue
            self.bundles.put(company.slug, doc.id, files)
            written += 1
        note = f"{written} written"
        if skipped:
            note += f", {sum(skipped.values())} skipped ({', '.join(sorted(skipped))})"
        return note

    def _decide(self, job):
        """Evaluate the company's rules. A rule problem never loses the job: it waits for a person."""
        rules = self.store.list_rules(job.company_id, enabled_only=True)
        if not rules:
            self.store.add_event(job.company_id, job.id, "rules", "ok", 1, "none")
            return rules_mod.Decision("none")
        docs = self.store.list_documents(job.company_id, job.id)
        body = next((self.blob.get(job.company_id, d.blob_key).decode("utf-8", "replace") for d in docs if d.kind == "body"), "")
        facts = rules_mod.Facts(job.sender, job.recipient, job.subject, body[:rules_mod.MAX_BODY],
                                tuple((d.filename, d.content_type) for d in docs if d.kind != "body"))
        try:
            return self._retry(job, "rules", lambda: self.evaluate(rules, facts),
                               detail=lambda d: d.action if d.kind == "move" else d.kind)
        except StepFailed:
            return rules_mod.Decision("none")

    # ---- deliver --------------------------------------------------------------------------
    def _deliver(self, job, summary: RunSummary) -> None:
        def fail(name):
            self.store.add_event(job.company_id, job.id, "deliver", "failed", 1, name)
            self.store.settle_delivery(job.company_id, job.id, False, name)
            summary.delivery_failed += 1

        if self.mail_out is None:
            return fail("NotConfigured")
        target = self.store.get_target(job.company_id, job.forward_target)
        try:
            if target is None:
                raise ForwardError("the forward target no longer exists")
            outgoing = self._compose(job, target)
        except ForwardError:
            return fail("ForwardError")
        try:
            self._retry(job, "deliver", lambda: self.mail_out.send(outgoing))
        except StepFailed as failure:
            self.store.settle_delivery(job.company_id, job.id, False, str(failure))
            summary.delivery_failed += 1
            return
        self.store.settle_delivery(job.company_id, job.id, True)
        summary.delivered += 1

    def _compose(self, job, target):
        docs = self.store.list_documents(job.company_id, job.id)
        files = [d for d in docs if d.kind != "body"]
        if len(files) > self.max_forward_files or sum(d.size for d in files) > self.max_forward_bytes:
            raise ForwardError("too much to email")  # checked before any file is read into memory
        attachments = [Attachment(d.filename, d.content_type, self.blob.get(job.company_id, d.blob_key)) for d in files]
        body = next((self.blob.get(job.company_id, d.blob_key).decode("utf-8", "replace") for d in docs if d.kind == "body"), "")
        values = [(v.name, v.value) for v in self.store.list_field_values(job.company_id, job.id)]
        return build_outgoing(job_id=job.id, sender=job.sender, subject=job.subject, recipient=job.recipient, received=job.created_at,
                              label=f"Forwarded to {target.name}", to=target.address, attachments=attachments, values=values,
                              body=body, max_bytes=self.max_forward_bytes, max_files=self.max_forward_files)

    # ---- retries --------------------------------------------------------------------------
    def _retry(self, job, step, action, detail=lambda result: ""):
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = action()
            except Exception as exc:  # a crash (BaseException) is deliberately not caught
                name = type(exc).__name__  # the message may hold document text: never store it
                if attempt == self.max_attempts or getattr(exc, "permanent", False):
                    self.store.add_event(job.company_id, job.id, step, "failed", attempt, name)
                    raise StepFailed(name) from None
                self.store.add_event(job.company_id, job.id, step, "retry", attempt, name)
                self.sleep(self.base_delay * 2 ** (attempt - 1))
            else:
                self.store.add_event(job.company_id, job.id, step, "ok", attempt, detail(result))
                return result
