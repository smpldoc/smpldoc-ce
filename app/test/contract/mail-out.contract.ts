// One test suite that every MailOut adapter must pass.
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import type { MailOut, OutboundMail } from "../../src/ports/mail-out.ts";
import { InvalidMailError } from "../../src/ports/mail-out.ts";
import { bytes } from "../helpers.ts";

export interface MailOutHarness {
  mailOut: MailOut;
  /** Every message the adapter actually handed to its sender. */
  sent(): Promise<OutboundMail[]>;
}

const good: OutboundMail = { to: ["ap@example.com"], subject: "Invoice 1042", text: "Forwarded." };

export function mailOutContract(name: string, make: () => Promise<MailOutHarness>): void {
  describe(`MailOut contract: ${name}`, () => {
    it("sends a valid message once and returns an id", async () => {
      const { mailOut, sent } = await make();
      const { id } = await mailOut.send(good);
      assert.ok(id.length > 0);
      assert.deepEqual(await sent(), [good]);
    });

    it("gives every send its own id", async () => {
      const { mailOut } = await make();
      const a = await mailOut.send(good);
      const b = await mailOut.send(good);
      assert.notEqual(a.id, b.id);
    });

    it("sends attachments with plain file names", async () => {
      const { mailOut, sent } = await make();
      const mail = { ...good, attachments: [{ filename: "invoice.pdf", contentType: "application/pdf", data: bytes("%PDF") }] };
      await mailOut.send(mail);
      assert.deepEqual(await sent(), [mail]);
    });

    const bad: Record<string, OutboundMail> = {
      "no recipient": { ...good, to: [] },
      "too many recipients": { ...good, to: Array.from({ length: 51 }, (_, i) => `u${i}@example.com`) },
      "a recipient with no @": { ...good, to: ["nobody"] },
      "a recipient with a space": { ...good, to: ["a b@example.com"] },
      "a recipient with a display name": { ...good, to: ["Bob <bob@example.com>"] },
      "two recipients in one entry": { ...good, to: ["a@example.com,b@example.com"] },
      "a recipient with a line break": { ...good, to: ["a@example.com\r\nBcc: x@example.com"] },
      "a subject with a line break (header injection)": { ...good, subject: "Hi\r\nBcc: attacker@example.com" },
      "a subject with a null byte": { ...good, subject: "Hi\u0000" },
      "a subject that is too long": { ...good, subject: "s".repeat(999) },
      "an attachment name with a path": {
        ...good, attachments: [{ filename: "../../etc/passwd", contentType: "text/plain", data: bytes("x") }],
      },
      "an attachment name with a line break": {
        ...good, attachments: [{ filename: "a\r\nb.pdf", contentType: "application/pdf", data: bytes("x") }],
      },
      "an attachment type with a line break": {
        ...good, attachments: [{ filename: "a.pdf", contentType: "application/pdf\r\nX: y", data: bytes("x") }],
      },
    };
    for (const [label, mail] of Object.entries(bad)) {
      it(`refuses ${label}, and sends nothing`, async () => {
        const { mailOut, sent } = await make();
        await assert.rejects(mailOut.send(mail), InvalidMailError);
        assert.deepEqual(await sent(), []);
      });
    }
  });
}
