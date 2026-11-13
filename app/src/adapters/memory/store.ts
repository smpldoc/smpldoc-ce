// In-memory Store. The reference for how every Store must behave. All the rules about moves
// come from the domain, so a database adapter can reuse them.
import { allowedActions, canAdvance, isJobAction, statusAfterAction } from "../../domain/workflow.ts";
import type { JobStatus } from "../../domain/workflow.ts";
import { checkActor, checkCompany, checkFieldValue, checkNewJob, checkNote, resolveFieldValues } from "../../domain/rules.ts";
import type { Clock, FieldValue, HistoryEntry, Job, Store } from "../../ports/store.ts";
import { CompanyRequiredError, InvalidInputError, InvalidTransitionError, JobNotFoundError } from "../../ports/store.ts";

interface Record {
  job: Job;
  history: HistoryEntry[];
  values: FieldValue[];
}

export function createMemoryStore(clock: Clock): Store {
  const records = new Map<string, Record>();
  const byMessage = new Map<string, string>();
  let counter = 0;

  function requireCompany(companyId: string): void {
    if (checkCompany(companyId)) throw new CompanyRequiredError("a company is required");
  }

  function find(companyId: string, jobId: string): Record {
    requireCompany(companyId);
    const record = records.get(jobId);
    if (!record || record.job.companyId !== companyId) throw new JobNotFoundError("job not found");
    return record;
  }

  function move(record: Record, to: JobStatus, actor: string, action: string, note: string): void {
    const at = clock();
    record.history.push({ seq: record.history.length + 1, at, actor, from: record.job.status, to, action, note });
    record.job.status = to;
    record.job.updatedAt = at;
  }

  return {
    async createJob(companyId, input) {
      requireCompany(companyId);
      const subject = input.subject ?? "";
      const problem = checkNewJob(input.messageId, subject);
      if (problem) throw new InvalidInputError(problem);
      const key = `${companyId}\u0000${input.messageId}`;
      const existing = byMessage.get(key);
      if (existing) return { job: structuredClone(records.get(existing)!.job), created: false };
      const at = clock();
      const id = `job_${++counter}`;
      const job: Job = { id, companyId, messageId: input.messageId, subject, status: "received", createdAt: at, updatedAt: at };
      records.set(id, {
        job,
        history: [{ seq: 1, at, actor: "system", from: null, to: "received", action: "create", note: "" }],
        values: [],
      });
      byMessage.set(key, id);
      return { job: structuredClone(job), created: true };
    },
    async getJob(companyId, jobId) {
      requireCompany(companyId);
      const record = records.get(jobId);
      return record && record.job.companyId === companyId ? structuredClone(record.job) : null;
    },
    async listJobs(companyId, filter) {
      requireCompany(companyId);
      return [...records.values()]
        .filter((r) => r.job.companyId === companyId && (!filter?.status || r.job.status === filter.status))
        .sort((a, b) => Date.parse(b.job.createdAt) - Date.parse(a.job.createdAt) || Number(b.job.id.slice(4)) - Number(a.job.id.slice(4)))
        .map((r) => structuredClone(r.job));
    },
    async advance(companyId, jobId, to) {
      const record = find(companyId, jobId);
      if (!canAdvance(record.job.status, to)) {
        throw new InvalidTransitionError(`the pipeline cannot move ${record.job.status} to ${to}`, record.job.status, allowedActions(record.job.status));
      }
      move(record, to, "pipeline", "advance", "");
      return structuredClone(record.job);
    },
    async applyAction(companyId, jobId, action, actor, note = "") {
      const record = find(companyId, jobId);
      const problem = checkActor(actor) ?? checkNote(note);
      if (problem) throw new InvalidInputError(problem);
      const to = isJobAction(action) ? statusAfterAction(record.job.status, action) : null;
      if (to === null) {
        throw new InvalidTransitionError(`${String(action)} is not allowed from ${record.job.status}`, record.job.status, allowedActions(record.job.status));
      }
      move(record, to, actor, action, note);
      return structuredClone(record.job);
    },
    async history(companyId, jobId) {
      return structuredClone(find(companyId, jobId).history);
    },
    async addFieldValue(companyId, jobId, value) {
      const record = find(companyId, jobId);
      const problem = checkFieldValue(value);
      if (problem) throw new InvalidInputError(problem);
      record.values.push({ name: value.name, value: value.value, source: value.source, at: clock() });
    },
    async fieldValues(companyId, jobId) {
      return structuredClone(resolveFieldValues(find(companyId, jobId).values));
    },
    async allFieldValues(companyId, jobId) {
      return structuredClone(find(companyId, jobId).values);
    },
  };
}
