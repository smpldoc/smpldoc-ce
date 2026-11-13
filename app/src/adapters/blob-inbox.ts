// MailIn over a BlobStore folder: a bucket that Amazon SES writes raw mail into, or a local
// folder for trials. New mail is under inbox/. Acknowledged mail moves to done/, set-aside mail
// to rejected/ with a .reason file beside it. Nothing here opens the mail beyond reading it.
import type { BlobStore } from "../ports/blob.ts";
import type { InboundMail, MailIn, SenderVerdict } from "../ports/mail-in.ts";
import { parseMessage } from "../domain/mime.ts";
import { verdictFromHeaders } from "../domain/verdict.ts";

export const DEFAULT_MAX_BYTES = 40 * 1024 * 1024;
const INBOX = "inbox/";
// SES writes this marker object when a receipt rule is first set up. It is not mail.
const NOT_MAIL = new Set(["AMAZON_SES_SETUP_NOTIFICATION"]);

export interface BlobInboxOptions {
  /** Decides the sender verdict. Defaults to reading the scan results SES adds to the message. */
  verdictOf?: (key: string, raw: Uint8Array) => Promise<SenderVerdict>;
  maxBytes?: number;
  now?: () => string;
}

export function createBlobInbox(blob: BlobStore, options: BlobInboxOptions = {}): MailIn {
  const maxBytes = options.maxBytes ?? DEFAULT_MAX_BYTES;
  const now = options.now ?? (() => new Date().toISOString());
  const verdictOf = options.verdictOf ?? (async (_key, raw) => verdictFromHeaders(parseMessage(raw).headers));
  const name = (key: string) => key.slice(INBOX.length);

  async function setAside(key: string, reason: string): Promise<void> {
    await blob.put(`rejected/${name(key)}.reason`, new TextEncoder().encode(reason));
    await blob.move(key, `rejected/${name(key)}`);
  }

  return {
    async poll(max) {
      if (!Number.isInteger(max) || max < 1) throw new RangeError("max must be a whole number of at least 1");
      const found: InboundMail[] = [];
      for (const key of await blob.list(INBOX)) {
        if (found.length >= max) break;
        if (NOT_MAIL.has(name(key))) continue;
        const raw = await blob.get(key);
        if (raw === null) continue;
        if (raw.length > maxBytes) {
          await setAside(key, `message is larger than ${maxBytes} bytes`);
          continue;
        }
        found.push({ id: name(key), raw, receivedAt: now(), verdict: await verdictOf(key, raw) });
      }
      return found;
    },
    async ack(id) {
      if ((await blob.get(`${INBOX}${id}`)) !== null) await blob.move(`${INBOX}${id}`, `done/${id}`);
    },
    async reject(id, reason) {
      if ((await blob.get(`${INBOX}${id}`)) !== null) await setAside(`${INBOX}${id}`, reason);
    },
  };
}
