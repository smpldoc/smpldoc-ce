// In-memory MailOut. Records what would have been sent. It sends nothing.
import type { MailOut, OutboundMail } from "../../ports/mail-out.ts";
import { assertValidOutbound } from "../../ports/mail-out.ts";

export interface MemoryMailOut extends MailOut {
  sent(): Promise<OutboundMail[]>;
}

export function createMemoryMailOut(): MemoryMailOut {
  const log: OutboundMail[] = [];
  return {
    async send(mail) {
      assertValidOutbound(mail);
      log.push(structuredClone(mail));
      return { id: `sent-${log.length}` };
    },
    async sent() {
      return structuredClone(log);
    },
  };
}
