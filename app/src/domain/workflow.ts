// Job statuses and the moves allowed between them.
// Pure rules only: this file imports nothing, so it can run anywhere.

export const JOB_STATUSES = ["received", "processing", "ready", "held", "failed", "closed"] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];

export const JOB_ACTIONS = ["send_to_review", "reprocess", "hold", "close", "reopen"] as const;
export type JobAction = (typeof JOB_ACTIONS)[number];

// What a person may do from each status, and where it leads.
const PERSON_MOVES: Record<JobStatus, Partial<Record<JobAction, JobStatus>>> = {
  received: { send_to_review: "ready", hold: "held", close: "closed" },
  processing: { reprocess: "processing", close: "closed" },
  ready: { reprocess: "processing", hold: "held", close: "closed" },
  held: { send_to_review: "ready", reprocess: "processing", close: "closed" },
  failed: { send_to_review: "ready", reprocess: "processing", hold: "held", close: "closed" },
  closed: { reprocess: "processing", reopen: "ready" },
};

// What the pipeline may do on its own.
const PIPELINE_MOVES: Record<JobStatus, JobStatus[]> = {
  received: ["processing", "held", "failed"],
  processing: ["ready", "failed"],
  ready: [],
  held: [],
  failed: [],
  closed: [],
};

export function allowedActions(status: JobStatus): JobAction[] {
  return Object.keys(PERSON_MOVES[status]) as JobAction[];
}

export function statusAfterAction(status: JobStatus, action: JobAction): JobStatus | null {
  return PERSON_MOVES[status][action] ?? null;
}

export function canAdvance(from: JobStatus, to: JobStatus): boolean {
  return PIPELINE_MOVES[from].includes(to);
}

export function isJobStatus(value: unknown): value is JobStatus {
  return typeof value === "string" && (JOB_STATUSES as readonly string[]).includes(value);
}

export function isJobAction(value: unknown): value is JobAction {
  return typeof value === "string" && (JOB_ACTIONS as readonly string[]).includes(value);
}
