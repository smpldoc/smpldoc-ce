// SQLite Store on Node's built-in node:sqlite. One file on the operator's disk. Every query
// carries the company, history rows cannot be changed once written, and each change to a job and
// its history happens in one transaction. The move rules come from the domain.
import { DatabaseSync } from "node:sqlite";
import { allowedActions, canAdvance, isJobAction, statusAfterAction } from "../../domain/workflow.ts";
import type { JobAction, JobStatus } from "../../domain/workflow.ts";
import { checkActor, checkCompany, checkFieldValue, checkNewJob, checkNote, resolveFieldValues } from "../../domain/rules.ts";
import type { Clock, FieldValue, HistoryEntry, Job, Store } from "../../ports/store.ts";
import { CompanyRequiredError, InvalidInputError, InvalidTransitionError, JobNotFoundError } from "../../ports/store.ts";

const SCHEMA = `
CREATE TABLE IF NOT EXISTS job (
  n INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  company_id TEXT NOT NULL,
  message_id TEXT NOT NULL,
  subject TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (company_id, message_id)
);
CREATE INDEX IF NOT EXISTS job_company_created ON job (company_id, created_at);
CREATE TABLE IF NOT EXISTS history (
  job_id TEXT NOT NULL REFERENCES job (id),
  seq INTEGER NOT NULL,
  at TEXT NOT NULL,
  actor TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  action TEXT NOT NULL,
  note TEXT NOT NULL,
  PRIMARY KEY (job_id, seq)
);
CREATE TRIGGER IF NOT EXISTS history_no_update BEFORE UPDATE ON history BEGIN SELECT RAISE(ABORT, 'history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS history_no_delete BEFORE DELETE ON history BEGIN SELECT RAISE(ABORT, 'history is append-only'); END;
CREATE TABLE IF NOT EXISTS field_value (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES job (id),
  name TEXT NOT NULL,
  value TEXT NOT NULL,
  source TEXT NOT NULL,
  at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS field_value_job ON field_value (job_id, id);
`;

interface JobRow {
  id: string;
  company_id: string;
  message_id: string;
  subject: string;
  status: JobStatus;
  created_at: string;
  updated_at: string;
}

const toJob = (r: JobRow): Job => ({
  id: r.id,
  companyId: r.company_id,
  messageId: r.message_id,
  subject: r.subject,
  status: r.status,
  createdAt: r.created_at,
  updatedAt: r.updated_at,
});

export interface SqliteHandle {
  store: Store;
  /** The open database, for tests and backups. */
  db: DatabaseSync;
  close(): void;
}

export function createSqliteStore(path: string, clock: Clock): SqliteHandle {
  const db = new DatabaseSync(path);
  db.exec("PRAGMA foreign_keys = ON");
  if (path !== ":memory:") db.exec("PRAGMA journal_mode = WAL");
  db.exec(SCHEMA);

  const q = {
    jobByMessage: db.prepare("SELECT * FROM job WHERE company_id = ? AND message_id = ?"),
    jobById: db.prepare("SELECT * FROM job WHERE company_id = ? AND id = ?"),
    listAll: db.prepare("SELECT * FROM job WHERE company_id = ? ORDER BY created_at DESC, n DESC"),
    listStatus: db.prepare("SELECT * FROM job WHERE company_id = ? AND status = ? ORDER BY created_at DESC, n DESC"),
    insertJob: db.prepare("INSERT INTO job (id, company_id, message_id, subject, status, created_at, updated_at) VALUES (?, ?, ?, ?, 'received', ?, ?)"),
    lastN: db.prepare("SELECT seq FROM sqlite_sequence WHERE name = 'job'"),
    setStatus: db.prepare("UPDATE job SET status = ?, updated_at = ? WHERE id = ?"),
    insertHistory: db.prepare("INSERT INTO history (job_id, seq, at, actor, from_status, to_status, action, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"),
    nextSeq: db.prepare("SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM history WHERE job_id = ?"),
    history: db.prepare("SELECT * FROM history WHERE job_id = ? ORDER BY seq"),
    insertValue: db.prepare("INSERT INTO field_value (job_id, name, value, source, at) VALUES (?, ?, ?, ?, ?)"),
    values: db.prepare("SELECT name, value, source, at FROM field_value WHERE job_id = ? ORDER BY id"),
  };

  function requireCompany(companyId: string): void {
    if (checkCompany(companyId)) throw new CompanyRequiredError("a company is required");
  }

  function findRow(companyId: string, jobId: string): JobRow {
    requireCompany(companyId);
    const row = q.jobById.get(companyId, jobId) as JobRow | undefined;
    if (!row) throw new JobNotFoundError("job not found");
    return row;
  }

  function inTransaction<T>(work: () => T): T {
    db.exec("BEGIN IMMEDIATE");
    try {
      const result = work();
      db.exec("COMMIT");
      return result;
    } catch (error) {
      db.exec("ROLLBACK");
      throw error;
    }
  }

  function move(row: JobRow, to: JobStatus, actor: string, action: string, note: string): Job {
    const at = clock();
    const seq = (q.nextSeq.get(row.id) as { next: number }).next;
    q.insertHistory.run(row.id, seq, at, actor, row.status, to, action, note);
    q.setStatus.run(to, at, row.id);
    return toJob({ ...row, status: to, updated_at: at });
  }

  const store: Store = {
    async createJob(companyId, input) {
      requireCompany(companyId);
      const subject = input.subject ?? "";
      const problem = checkNewJob(input.messageId, subject);
      if (problem) throw new InvalidInputError(problem);
      return inTransaction(() => {
        const existing = q.jobByMessage.get(companyId, input.messageId) as JobRow | undefined;
        if (existing) return { job: toJob(existing), created: false };
        const at = clock();
        const last = (q.lastN.get() as { seq: number } | undefined)?.seq ?? 0;
        const id = `job_${last + 1}`;
        q.insertJob.run(id, companyId, input.messageId, subject, at, at);
        q.insertHistory.run(id, 1, at, "system", null, "received", "create", "");
        return { job: toJob(q.jobById.get(companyId, id) as JobRow), created: true };
      });
    },
    async getJob(companyId, jobId) {
      requireCompany(companyId);
      const row = q.jobById.get(companyId, jobId) as JobRow | undefined;
      return row ? toJob(row) : null;
    },
    async listJobs(companyId, filter) {
      requireCompany(companyId);
      const rows = (filter?.status ? q.listStatus.all(companyId, filter.status) : q.listAll.all(companyId)) as unknown as JobRow[];
      return rows.map(toJob);
    },
    async advance(companyId, jobId, to) {
      return inTransaction(() => {
        const row = findRow(companyId, jobId);
        if (!canAdvance(row.status, to)) {
          throw new InvalidTransitionError(`the pipeline cannot move ${row.status} to ${to}`, row.status, allowedActions(row.status));
        }
        return move(row, to, "pipeline", "advance", "");
      });
    },
    async applyAction(companyId, jobId, action: JobAction, actor, note = "") {
      return inTransaction(() => {
        const row = findRow(companyId, jobId);
        const problem = checkActor(actor) ?? checkNote(note);
        if (problem) throw new InvalidInputError(problem);
        const to = isJobAction(action) ? statusAfterAction(row.status, action) : null;
        if (to === null) {
          throw new InvalidTransitionError(`${String(action)} is not allowed from ${row.status}`, row.status, allowedActions(row.status));
        }
        return move(row, to, actor, action, note);
      });
    },
    async history(companyId, jobId) {
      const row = findRow(companyId, jobId);
      return (q.history.all(row.id) as Array<Record<string, string | number | null>>).map(
        (h): HistoryEntry => ({
          seq: h.seq as number,
          at: h.at as string,
          actor: h.actor as string,
          from: h.from_status as JobStatus | null,
          to: h.to_status as JobStatus,
          action: h.action as string,
          note: h.note as string,
        }),
      );
    },
    async addFieldValue(companyId, jobId, value) {
      const row = findRow(companyId, jobId);
      const problem = checkFieldValue(value);
      if (problem) throw new InvalidInputError(problem);
      q.insertValue.run(row.id, value.name, value.value, value.source, clock());
    },
    async fieldValues(companyId, jobId) {
      return resolveFieldValues(await this.allFieldValues(companyId, jobId));
    },
    async allFieldValues(companyId, jobId) {
      const row = findRow(companyId, jobId);
      return (q.values.all(row.id) as unknown as FieldValue[]).map((v) => ({ name: v.name, value: v.value, source: v.source, at: v.at }));
    },
  };

  return { store, db, close: () => db.close() };
}
