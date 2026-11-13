// The job pipeline: poll mail, make a job, hold or read it, store the values, move it on.
// It only talks to ports and the domain, so it runs the same on a laptop and in a cloud.
//
// Delivery is at least once, so every step is safe to repeat: the same email makes one job, a job
// left half done by a crash is finished on the next poll, and values are never added twice.
import { parseMessage } from "../domain/mime.ts";
import type { MessagePart } from "../domain/mime.ts";
import type { BlobStore } from "../ports/blob.ts";
import type { ExtractedField, Extractor } from "../ports/extractor.ts";
import { UnsupportedDocumentError } from "../ports/extractor.ts";
import type { InboundMail, MailIn } from "../ports/mail-in.ts";
import type { Job, Store } from "../ports/store.ts";

export interface PipelineDeps {
  mailIn: MailIn;
  store: Store;
  blob: BlobStore;
  extractor: Extractor;
  /** Every job belongs to this company. Several companies per install come later. */
  companyId: string;
  /** The field names to look for in each document. */
  fields: string[];
  /** Attempts per message before the job is marked failed. */
  retries?: number;
  sleep?: (ms: number) => Promise<void>;
  batch?: number;
  onError?: (error: unknown, mail: InboundMail) => void;
}

export interface RunResult {
  processed: number;
  ready: number;
  held: number;
  failed: number;
  skipped: number;
}

const BASE_DELAY_MS = 500;

function safeName(part: MessagePart, index: number): string {
  const base = (part.filename ?? `part-${index}`).replace(/[^A-Za-z0-9._-]/g, "_").replace(/^\.+/, "").slice(0, 80);
  return `${index}-${base || "part"}`;
}

export function createPipeline(deps: PipelineDeps) {
  const retries = Math.max(1, deps.retries ?? 3);
  const sleep = deps.sleep ?? ((ms) => new Promise<void>((resolve) => setTimeout(resolve, ms)));
  const batch = deps.batch ?? 20;
  const { store, blob, mailIn, companyId } = deps;

  async function extractAll(job: Job, parts: MessagePart[]): Promise<void> {
    const have = new Set((await store.allFieldValues(companyId, job.id)).filter((v) => v.source === "derived").map((v) => v.name));
    for (const [index, part] of parts.entries()) {
      await blob.put(`documents/${companyId}/${job.id}/${safeName(part, index)}`, part.data);
      let fields: ExtractedField[];
      try {
        fields = (await deps.extractor.extract({ documentId: `${job.id}/${index}`, contentType: part.contentType, data: part.data, fields: deps.fields })).fields;
      } catch (error) {
        if (error instanceof UnsupportedDocumentError) continue;
        throw error;
      }
      for (const field of fields) {
        if (have.has(field.name)) continue;
        have.add(field.name);
        await store.addFieldValue(companyId, job.id, { name: field.name, value: field.value, source: "derived" });
      }
    }
  }

  async function handle(mail: InboundMail, result: RunResult): Promise<void> {
    const message = parseMessage(mail.raw);
    if (!message.messageId) {
      await mailIn.reject(mail.id, "no Message-ID header");
      return;
    }
    const { job, created } = await store.createJob(companyId, { messageId: message.messageId, subject: message.subject.slice(0, 1000) });
    result.processed++;
    if (!created && job.status !== "received" && job.status !== "processing") {
      result.skipped++;
      await mailIn.ack(mail.id);
      return;
    }
    await blob.put(`mail/${companyId}/${job.id}.eml`, mail.raw);
    if (mail.verdict !== "pass") {
      if (job.status === "received") await store.advance(companyId, job.id, "held", `sender verdict: ${mail.verdict}`);
      result.held++;
      await mailIn.ack(mail.id);
      return;
    }
    if (job.status === "received") await store.advance(companyId, job.id, "processing");
    let lastError: unknown;
    for (let attempt = 1; attempt <= retries; attempt++) {
      try {
        await extractAll(job, message.parts);
        await store.advance(companyId, job.id, "ready");
        result.ready++;
        await mailIn.ack(mail.id);
        return;
      } catch (error) {
        lastError = error;
        if (attempt < retries) await sleep(BASE_DELAY_MS * 2 ** (attempt - 1));
      }
    }
    const reason = lastError instanceof Error ? lastError.message : String(lastError);
    await store.advance(companyId, job.id, "failed", reason.slice(0, 500));
    result.failed++;
    await mailIn.ack(mail.id);
  }

  return {
    /** One pass over the waiting mail. A message that hits an unexpected error stays unacknowledged and is tried again next pass. */
    async runOnce(): Promise<RunResult> {
      const result: RunResult = { processed: 0, ready: 0, held: 0, failed: 0, skipped: 0 };
      for (const mail of await mailIn.poll(batch)) {
        try {
          await handle(mail, result);
        } catch (error) {
          deps.onError?.(error, mail);
        }
      }
      return result;
    },
    /** Polls until `stopped()` is true, waiting `idleMs` between passes that found nothing. */
    async runUntil(stopped: () => boolean, idleMs: number): Promise<void> {
      while (!stopped()) {
        const { processed } = await this.runOnce();
        if (processed === 0 && !stopped()) await sleep(idleMs);
      }
    },
  };
}
