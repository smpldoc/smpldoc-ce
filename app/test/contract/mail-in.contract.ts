// One test suite that every MailIn adapter must pass.
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import type { MailIn, SenderVerdict } from "../../src/ports/mail-in.ts";
import { SENDER_VERDICTS } from "../../src/ports/mail-in.ts";
import { bytes } from "../helpers.ts";

/** The adapter plus a way to put mail where it would normally arrive. */
export interface MailInHarness {
  mailIn: MailIn;
  /** Puts a message at the source. A source that gives no sender check passes no verdict. */
  deliver(raw: Uint8Array, verdict?: SenderVerdict): Promise<void>;
  /** Messages that were set aside, with the reason given. */
  rejected(): Promise<Array<{ id: string; reason: string }>>;
}

export function mailInContract(name: string, make: () => Promise<MailInHarness>): void {
  describe(`MailIn contract: ${name}`, () => {
    it("returns nothing when no mail has arrived", async () => {
      const { mailIn } = await make();
      assert.deepEqual(await mailIn.poll(10), []);
    });

    it("returns each message exactly as received", async () => {
      const { mailIn, deliver } = await make();
      const raw = Uint8Array.from([0, 255, 13, 10, 80, 75]);
      await deliver(raw, "pass");
      const [mail, ...rest] = await mailIn.poll(10);
      assert.equal(rest.length, 0);
      assert.deepEqual(mail.raw, raw);
      assert.ok(mail.id.length > 0);
      assert.ok(!Number.isNaN(Date.parse(mail.receivedAt)));
    });

    it("reports the sender verdict, and unknown when the source gave none", async () => {
      const { mailIn, deliver } = await make();
      await deliver(bytes("a"), "pass");
      await deliver(bytes("b"), "fail");
      await deliver(bytes("c"));
      const mails = await mailIn.poll(10);
      const verdicts = new Map(mails.map((m) => [new TextDecoder().decode(m.raw), m.verdict]));
      assert.deepEqual([verdicts.get("a"), verdicts.get("b"), verdicts.get("c")], ["pass", "fail", "unknown"]);
      for (const mail of mails) assert.ok(SENDER_VERDICTS.includes(mail.verdict));
    });

    it("gives every message its own id", async () => {
      const { mailIn, deliver } = await make();
      await deliver(bytes("same"));
      await deliver(bytes("same"));
      const ids = (await mailIn.poll(10)).map((m) => m.id);
      assert.equal(ids.length, 2);
      assert.equal(new Set(ids).size, 2);
    });

    it("returns an unacknowledged message again, so a crash loses nothing", async () => {
      const { mailIn, deliver } = await make();
      await deliver(bytes("a"));
      const first = await mailIn.poll(10);
      const second = await mailIn.poll(10);
      assert.deepEqual(second.map((m) => m.id), first.map((m) => m.id));
    });

    it("never returns an acknowledged message again, and a second ack is not an error", async () => {
      const { mailIn, deliver } = await make();
      await deliver(bytes("a"));
      const [mail] = await mailIn.poll(10);
      await mailIn.ack(mail.id);
      await mailIn.ack(mail.id);
      assert.deepEqual(await mailIn.poll(10), []);
    });

    it("sets a rejected message aside with its reason", async () => {
      const { mailIn, deliver, rejected } = await make();
      await deliver(bytes("bad"));
      const [mail] = await mailIn.poll(10);
      await mailIn.reject(mail.id, "could not be parsed");
      assert.deepEqual(await mailIn.poll(10), []);
      assert.deepEqual(await rejected(), [{ id: mail.id, reason: "could not be parsed" }]);
    });

    it("a rejected message does not block the next one", async () => {
      const { mailIn, deliver } = await make();
      await deliver(bytes("bad"));
      await deliver(bytes("good"));
      const [bad] = await mailIn.poll(1);
      await mailIn.reject(bad.id, "bad");
      const [good] = await mailIn.poll(1);
      assert.equal(new TextDecoder().decode(good.raw), "good");
    });

    it("respects the limit, oldest first", async () => {
      const { mailIn, deliver } = await make();
      for (const name of ["one", "two", "three"]) await deliver(bytes(name));
      const firstTwo = await mailIn.poll(2);
      assert.deepEqual(firstTwo.map((m) => new TextDecoder().decode(m.raw)), ["one", "two"]);
      for (const mail of firstTwo) await mailIn.ack(mail.id);
      const rest = await mailIn.poll(2);
      assert.deepEqual(rest.map((m) => new TextDecoder().decode(m.raw)), ["three"]);
    });

    it("refuses a limit below 1", async () => {
      const { mailIn } = await make();
      await assert.rejects(mailIn.poll(0), RangeError);
      await assert.rejects(mailIn.poll(-1), RangeError);
    });
  });
}
