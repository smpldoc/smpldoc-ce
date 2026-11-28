"""Store adapter on a single SQLite file. Every query carries the company id."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from smpldoc.domain.deliver import valid_address, valid_name
from smpldoc.domain.ids import new_id
from smpldoc.domain.models import Company, Condition, Document, Event, FieldValue, Job, PENDING, Rule, Target

MAX_RULES = 50
SCHEMA = """
CREATE TABLE IF NOT EXISTS company (id TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS job (
  id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES company(id), source_id TEXT NOT NULL,
  status TEXT NOT NULL, sender TEXT NOT NULL, subject TEXT NOT NULL, raw_key TEXT NOT NULL,
  error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
  recipient TEXT NOT NULL DEFAULT '', rule_conflict TEXT NOT NULL DEFAULT '', forward_target TEXT NOT NULL DEFAULT '',
  UNIQUE (company_id, source_id));
CREATE TABLE IF NOT EXISTS document (
  id TEXT PRIMARY KEY, company_id TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES job(id),
  filename TEXT NOT NULL, content_type TEXT NOT NULL, blob_key TEXT NOT NULL, size INTEGER NOT NULL,
  kind TEXT NOT NULL DEFAULT 'attachment');
CREATE TABLE IF NOT EXISTS field_value (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL, job_id TEXT NOT NULL,
  document_id TEXT NOT NULL, name TEXT NOT NULL, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS event (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL, job_id TEXT NOT NULL,
  step TEXT NOT NULL, outcome TEXT NOT NULL, attempt INTEGER NOT NULL, detail TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rule (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, company_id TEXT NOT NULL, name TEXT NOT NULL,
  action TEXT NOT NULL, target TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1,
  conditions TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS forward_target (
  company_id TEXT NOT NULL, name TEXT NOT NULL, address TEXT NOT NULL, PRIMARY KEY (company_id, name));
"""
# Columns added after the first release of the schema: an older database file gains them on open.
ADDED = {"job": [("recipient", "TEXT NOT NULL DEFAULT ''"), ("rule_conflict", "TEXT NOT NULL DEFAULT ''"),
                 ("forward_target", "TEXT NOT NULL DEFAULT ''")],
         "document": [("kind", "TEXT NOT NULL DEFAULT 'attachment'")]}
JOB = "id, company_id, source_id, status, sender, subject, raw_key, error, created_at, recipient, rule_conflict, forward_target"
RULE = "id, company_id, name, action, target, enabled, conditions, created_at"
FINAL = ("ready", "held", "closed")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _job(r):
    return Job(*r[:9], recipient=r[9], rule_conflict=tuple(x for x in r[10].split(",") if x), forward_target=r[11])


def _rule(r):
    return Rule(r[0], r[1], r[2], r[3], r[4], bool(r[5]), tuple(Condition(f, p) for f, p in json.loads(r[6])), r[7])


class SqliteStore:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=10)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        for table, cols in ADDED.items():
            have = {r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}
            for name, decl in cols:
                if name not in have:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

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

    # ---- companies and jobs -------------------------------------------------------------
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

    def get_company(self, company_id):
        row = self.db.execute("SELECT id, slug, name FROM company WHERE id = ?", (company_id,)).fetchone()
        return Company(*row) if row else None

    def create_job(self, company_id, source_id, sender, subject, raw_key, status, documents, recipient=""):
        with self._tx():
            row = self.db.execute(f"SELECT {JOB} FROM job WHERE company_id = ? AND source_id = ?", (company_id, source_id)).fetchone()
            if row:
                return _job(row), False
            job = Job(new_id(), company_id, source_id, status, sender, subject, raw_key, "", _now(), recipient)
            self.db.execute("INSERT INTO job (id, company_id, source_id, status, sender, subject, raw_key, error, created_at, recipient) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (job.id, company_id, source_id, status, sender, subject, raw_key, "", job.created_at, recipient))
            for d in documents:
                self.db.execute("INSERT INTO document (id, company_id, job_id, filename, content_type, blob_key, size, kind) VALUES (?,?,?,?,?,?,?,?)",
                                (new_id(), company_id, job.id, d.filename, d.content_type, d.blob_key, d.size, d.kind))
            return job, True

    def get_job(self, company_id, job_id):
        row = self.db.execute(f"SELECT {JOB} FROM job WHERE company_id = ? AND id = ?", (company_id, job_id)).fetchone()
        return _job(row) if row else None

    def list_jobs(self, company_id, status=None):
        sql, args = f"SELECT {JOB} FROM job WHERE company_id = ?", [company_id]
        if status:
            sql, args = sql + " AND status = ?", args + [status]
        return [_job(r) for r in self.db.execute(sql + " ORDER BY id", args)]

    def list_pending(self):
        marks = ",".join("?" * len(PENDING))
        return [_job(r) for r in self.db.execute(f"SELECT {JOB} FROM job WHERE status IN ({marks}) ORDER BY id", PENDING)]

    def list_to_deliver(self):
        return [_job(r) for r in self.db.execute(f"SELECT {JOB} FROM job WHERE status = 'ready' AND forward_target != '' ORDER BY id")]

    def set_status(self, company_id, job_id, status, error=""):
        self.db.execute("UPDATE job SET status = ?, error = ? WHERE company_id = ? AND id = ?", (status, error, company_id, job_id))

    def list_documents(self, company_id, job_id):
        return [Document(*r) for r in self.db.execute(
            "SELECT id, company_id, job_id, filename, content_type, blob_key, size, kind FROM document "
            "WHERE company_id = ? AND job_id = ? ORDER BY rowid", (company_id, job_id))]

    def complete_job(self, company_id, job_id, values, status="ready", conflict=(), forward_target=""):
        if status not in FINAL:
            raise ValueError(f"a finished job is {', '.join(FINAL)}, not {status!r}")
        marks = ",".join("?" * len(PENDING))
        with self._tx():
            row = self.db.execute(f"SELECT 1 FROM job WHERE company_id = ? AND id = ? AND status IN ({marks})", (company_id, job_id, *PENDING)).fetchone()
            if not row:
                return False
            self.db.execute("DELETE FROM field_value WHERE company_id = ? AND job_id = ?", (company_id, job_id))  # a reprocess replaces
            for v in values:
                self.db.execute("INSERT INTO field_value (company_id, job_id, document_id, name, value) VALUES (?,?,?,?,?)",
                                (company_id, job_id, v.document_id, v.name, v.value))
            self.db.execute("UPDATE job SET status = ?, error = '', rule_conflict = ?, forward_target = ? WHERE company_id = ? AND id = ?",
                            (status, ",".join(conflict), forward_target, company_id, job_id))
            return True

    def move_job(self, company_id, job_id, from_statuses, to_status, forward_target=None, clear_conflict=True):
        marks = ",".join("?" * len(from_statuses))
        cur = self.db.execute(
            "UPDATE job SET status = ?, error = '', rule_conflict = CASE WHEN ? THEN '' ELSE rule_conflict END, "
            "forward_target = COALESCE(?, forward_target) "
            f"WHERE company_id = ? AND id = ? AND status IN ({marks})",
            (to_status, 1 if clear_conflict else 0, forward_target, company_id, job_id, *from_statuses))
        return cur.rowcount > 0

    def settle_delivery(self, company_id, job_id, ok, error=""):
        if ok:
            cur = self.db.execute("UPDATE job SET status = 'done', forward_target = '', error = '' WHERE company_id = ? AND id = ? AND status = 'ready' AND forward_target != ''", (company_id, job_id))
        else:
            cur = self.db.execute("UPDATE job SET forward_target = '', error = ? WHERE company_id = ? AND id = ? AND status = 'ready' AND forward_target != ''", (error, company_id, job_id))
        return cur.rowcount > 0

    def list_field_values(self, company_id, job_id):
        return [FieldValue(*r) for r in self.db.execute(
            "SELECT company_id, job_id, document_id, name, value FROM field_value WHERE company_id = ? AND job_id = ? ORDER BY seq", (company_id, job_id))]

    def add_event(self, company_id, job_id, step, outcome, attempt=1, detail=""):
        self.db.execute("INSERT INTO event (company_id, job_id, step, outcome, attempt, detail, at) VALUES (?,?,?,?,?,?,?)",
                        (company_id, job_id, step, outcome, attempt, detail, _now()))

    def list_events(self, company_id, job_id):
        return [Event(*r) for r in self.db.execute(
            "SELECT company_id, job_id, step, outcome, attempt, detail, at FROM event WHERE company_id = ? AND job_id = ? ORDER BY seq", (company_id, job_id))]

    # ---- rules ---------------------------------------------------------------------------
    def add_rule(self, company_id, name, action, target, conditions, enabled=True):
        with self._tx():
            if self.db.execute("SELECT COUNT(*) FROM rule WHERE company_id = ?", (company_id,)).fetchone()[0] >= MAX_RULES:
                raise ValueError(f"a company can have at most {MAX_RULES} rules")
            r = Rule(new_id(), company_id, name, action, target, enabled, tuple(Condition(c.field, c.pattern) for c in conditions), _now())
            self.db.execute(f"INSERT INTO rule (id, company_id, name, action, target, enabled, conditions, created_at) VALUES (?,?,?,?,?,?,?,?)",
                            (r.id, company_id, name, action, target, int(enabled), json.dumps([[c.field, c.pattern] for c in r.conditions]), r.created_at))
            return r

    def list_rules(self, company_id, enabled_only=False):
        sql = f"SELECT {RULE} FROM rule WHERE company_id = ?" + (" AND enabled = 1" if enabled_only else "") + " ORDER BY seq"
        return [_rule(r) for r in self.db.execute(sql, (company_id,))]

    def get_rule(self, company_id, rule_id):
        row = self.db.execute(f"SELECT {RULE} FROM rule WHERE company_id = ? AND id = ?", (company_id, rule_id)).fetchone()
        return _rule(row) if row else None

    def set_rule_enabled(self, company_id, rule_id, enabled):
        return self.db.execute("UPDATE rule SET enabled = ? WHERE company_id = ? AND id = ?", (int(enabled), company_id, rule_id)).rowcount > 0

    def delete_rule(self, company_id, rule_id):
        return self.db.execute("DELETE FROM rule WHERE company_id = ? AND id = ?", (company_id, rule_id)).rowcount > 0

    # ---- forward targets -------------------------------------------------------------------
    def add_target(self, company_id, name, address):
        if not valid_name(name):
            raise ValueError("a target name is lowercase letters, digits and dashes")
        if not valid_address(address):
            raise ValueError("that is not a valid email address")
        try:
            self.db.execute("INSERT INTO forward_target VALUES (?,?,?)", (company_id, name, address))
        except sqlite3.IntegrityError:
            raise ValueError(f"a target named {name!r} already exists") from None
        return Target(company_id, name, address)

    def get_target(self, company_id, name):
        row = self.db.execute("SELECT company_id, name, address FROM forward_target WHERE company_id = ? AND name = ?", (company_id, name)).fetchone()
        return Target(*row) if row else None

    def list_targets(self, company_id):
        return [Target(*r) for r in self.db.execute("SELECT company_id, name, address FROM forward_target WHERE company_id = ? ORDER BY name", (company_id,))]

    def delete_target(self, company_id, name):
        return self.db.execute("DELETE FROM forward_target WHERE company_id = ? AND name = ?", (company_id, name)).rowcount > 0
