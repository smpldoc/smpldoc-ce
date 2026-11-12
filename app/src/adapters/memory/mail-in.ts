// In-memory MailIn. `deliver` puts mail where it would normally arrive.
import type { InboundMail, MailIn, SenderVerdict } from "../../ports/mail-in.ts";

export interface MemoryMailIn extends MailIn {
  deliver(raw: Uint8Array, verdict?: SenderVerdict): Promise<void>;
  rejected(): Promise<Array<{ id: string; reason: string }>>;
}

export function createMemoryMailIn(now: () => string = () => new Date().toISOString()): MemoryMailIn {
  const pending = new Map<string, InboundMail>();
  const setAside: Array<{ id: string; reason: string }> = [];
  let counter = 0;
  return {
    async deliver(raw, verdict) {
      const id = `mail-${++counter}`;
      pending.set(id, { id, raw: Uint8Array.from(raw), receivedAt: now(), verdict: verdict ?? "unknown" });
    },
    async rejected() {
      return setAside.map((entry) => ({ ...entry }));
    },
    async poll(max) {
      if (!Number.isInteger(max) || max < 1) throw new RangeError("max must be a whole number of at least 1");
      return [...pending.values()].slice(0, max).map((mail) => ({ ...mail, raw: Uint8Array.from(mail.raw) }));
    },
    async ack(id) {
      pending.delete(id);
    },
    async reject(id, reason) {
      if (pending.delete(id)) setAside.push({ id, reason });
    },
  };
}
