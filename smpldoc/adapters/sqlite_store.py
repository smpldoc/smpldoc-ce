"""Store adapter on a single SQLite file. Every query carries the company id."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from smpldoc.domain.ids import new_id
from smpldoc.domain.models import Company, Document, Event, FieldValue, Job, PENDING

SCHEMA = """
CREATE TABLE IF NOT EXISTS company (id TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS job (
  id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES company(id), source_id TEXT NOT NULL,
  status TEXT NOT NULL, sender TEXT NOT NULL, subject TEXT NOT NULL, raw_key TEXT NOT NULL,
  error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, UNIQUE (company_id, source_id));
CREATE TABLE IF NOT EXISTS document (
  id TEXT PRIMARY KEY, company_id TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES job(id),
  filename TEXT NOT NULL, content_type TEXT NOT NULL, blob_key TEXT NOT NULL, size INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS field_value (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL, job_id TEXT NOT NULL,
  document_id TEXT NOT NULL, name TEXT NOT NULL, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS event (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL, job_id TEXT NOT NULL,
  step TEXT NOT NULL, outcome TEXT NOT NULL, attempt INTEGER NOT NULL, detail TEXT NOT NULL, at TEXT NOT NULL);
"""
JOB = "id, company_id, source_id, status, sender, subject, raw_key, error, created_at"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class SqliteStore:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    @contextmanager
    def _tx(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    def add_company(self, slug, name):
        try:
            c = Company(new_id(), slug, name)
            self.db.execute("INSERT INTO company VALUES (?,?,?)", (c.id, c.slug, c.name))
            return c
        except sqlite3.IntegrityError:
            raise ValueError(f"company slug {slug!r} already exists") from None

    def find_company_by_slug(self, slug):
        row = self.db.execute("SELECT id, slug, name FROM company WHERE slug = ?", (slug,)).fetchone()
        return Company(*row) if row else None

    def create_job(self, company_id, source_id, sender, subject, raw_key, status, documents):
        with self._tx():
            row = self.db.execute(f"SELECT {JOB} FROM job WHERE company_id = ? AND source_id = ?",
                                  (company_id, source_id)).fetchone()
            if row:
                return Job(*row), False
            job = Job(new_id(), company_id, source_id, status, sender, subject, raw_key, "", _now())
            self.db.execute(f"INSERT INTO job ({JOB}) VALUES (?,?,?,?,?,?,?,?,?)", tuple(job.__dict__.values()))
            for d in documents:
                self.db.execute("INSERT INTO document VALUES (?,?,?,?,?,?,?)",
                                (new_id(), company_id, job.id, d.filename, d.content_type, d.blob_key, d.size))
            return job, True

    def get_job(self, company_id, job_id):
        row = self.db.execute(f"SELECT {JOB} FROM job WHERE company_id = ? AND id = ?",
                              (company_id, job_id)).fetchone()
        return Job(*row) if row else None

    def list_jobs(self, company_id, status=None):
        sql, args = f"SELECT {JOB} FROM job WHERE company_id = ?", [company_id]
        if status:
            sql, args = sql + " AND status = ?", args + [status]
        return [Job(*r) for r in self.db.execute(sql + " ORDER BY id", args)]

    def list_pending(self):
        marks = ",".join("?" * len(PENDING))
        return [Job(*r) for r in self.db.execute(f"SELECT {JOB} FROM job WHERE status IN ({marks}) ORDER BY id", PENDING)]

    def set_status(self, company_id, job_id, status, error=""):
        self.db.execute("UPDATE job SET status = ?, error = ? WHERE company_id = ? AND id = ?",
                        (status, error, company_id, job_id))

    def list_documents(self, company_id, job_id):
        return [Document(*r) for r in self.db.execute(
            "SELECT id, company_id, job_id, filename, content_type, blob_key, size FROM document "
            "WHERE company_id = ? AND job_id = ? ORDER BY rowid", (company_id, job_id))]

    def complete_job(self, company_id, job_id, values):
        marks = ",".join("?" * len(PENDING))
        with self._tx():
            row = self.db.execute(f"SELECT 1 FROM job WHERE company_id = ? AND id = ? AND status IN ({marks})",
                                  (company_id, job_id, *PENDING)).fetchone()
            if not row:
                return False
            for v in values:
                self.db.execute("INSERT INTO field_value (company_id, job_id, document_id, name, value) VALUES (?,?,?,?,?)",
                                (company_id, job_id, v.document_id, v.name, v.value))
            self.db.execute("UPDATE job SET status = 'done', error = '' WHERE company_id = ? AND id = ?",
                            (company_id, job_id))
            return True

    def list_field_values(self, company_id, job_id):
        return [FieldValue(*r) for r in self.db.execute(
            "SELECT company_id, job_id, document_id, name, value FROM field_value "
            "WHERE company_id = ? AND job_id = ? ORDER BY seq", (company_id, job_id))]

    def add_event(self, company_id, job_id, step, outcome, attempt=1, detail=""):
        self.db.execute("INSERT INTO event (company_id, job_id, step, outcome, attempt, detail, at) VALUES (?,?,?,?,?,?,?)",
                        (company_id, job_id, step, outcome, attempt, detail, _now()))

    def list_events(self, company_id, job_id):
        return [Event(*r) for r in self.db.execute(
            "SELECT company_id, job_id, step, outcome, attempt, detail, at FROM event "
            "WHERE company_id = ? AND job_id = ? ORDER BY seq", (company_id, job_id))]
