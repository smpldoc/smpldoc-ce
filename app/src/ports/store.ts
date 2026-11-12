// Where jobs, field values and history are kept. Every method takes the company first, and a
// company can never see or change another company's records.
import type { JobAction, JobStatus } from "../domain/workflow.ts";

export class CompanyRequiredError extends Error {}
export class InvalidInputError extends Error {}
export class JobNotFoundError extends Error {}
export class InvalidTransitionError extends Error {
  status: JobStatus;
  allowedActions: JobAction[];
  constructor(message: string, status: JobStatus, allowedActions: JobAction[]) {
    super(message);
    this.status = status;
    this.allowedActions = allowedActions;
  }
}

export type Clock = () => string;

export interface Job {
  id: string;
  companyId: string;
  messageId: string;
  subject: string;
  status: JobStatus;
  createdAt: string;
  updatedAt: string;
}

export interface HistoryEntry {
  /** 1, 2, 3 ... for each job. Never reused, never changed. */
  seq: number;
  at: string;
  actor: string;
  from: JobStatus | null;
  to: JobStatus;
  action: string;
  note: string;
}

export type FieldSource = "derived" | "correction";

export interface FieldValue {
  name: string;
  value: string;
  source: FieldSource;
  at: string;
}

export interface Store {
  /** One job per (company, messageId). A repeat returns the existing job with created: false. */
  createJob(companyId: string, input: { messageId: string; subject?: string }): Promise<{ job: Job; created: boolean }>;
  /** Null when the job does not exist or belongs to another company. */
  getJob(companyId: string, jobId: string): Promise<Job | null>;
  /** This company's jobs, newest first. */
  listJobs(companyId: string, filter?: { status?: JobStatus }): Promise<Job[]>;
  /** A move made by the pipeline. Throws InvalidTransitionError when it is not allowed. */
  advance(companyId: string, jobId: string, to: JobStatus): Promise<Job>;
  /** A move made by a person. Throws InvalidTransitionError and changes nothing when not allowed. */
  applyAction(companyId: string, jobId: string, action: JobAction, actor: string, note?: string): Promise<Job>;
  /** Every change to the job, in order. */
  history(companyId: string, jobId: string): Promise<HistoryEntry[]>;
  /** Adds a value. Nothing is ever overwritten. */
  addFieldValue(companyId: string, jobId: string, value: { name: string; value: string; source: FieldSource }): Promise<void>;
  /** The value in effect for each field: the latest correction, else the latest derived value. */
  fieldValues(companyId: string, jobId: string): Promise<FieldValue[]>;
  /** Every value ever added, in the order added. */
  allFieldValues(companyId: string, jobId: string): Promise<FieldValue[]>;
}
