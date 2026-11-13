import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { mailInContract } from "../contract/mail-in.contract.ts";
import { createBlobInbox } from "../../src/adapters/blob-inbox.ts";
import { createMemoryBlob } from "../../src/adapters/memory/blob.ts";
import { bytes } from "../helpers.ts";

// The test source records the verdict next to the message. Real sources read it from the message.
function harness() {
  const blob = createMemoryBlob();
  let n = 0;
  const verdicts = new Map<string, "pass" | "fail" | "unknown">();
  const mailIn = createBlobInbox(blob, {
    verdictOf: async (key) => verdicts.get(key) ?? "unknown",
    now: () => "2026-01-01T00:00:00.000Z",
  });
  return {
    blob,
    mailIn,
    async deliver(raw: Uint8Array, verdict?: "pass" | "fail" | "unknown") {
      const key = `inbox/m${String(++n).padStart(4, "0")}`;
      await blob.put(key, raw);
      if (verdict) verdicts.set(key, verdict);
    },
    async rejected() {
      const out: Array<{ id: string; reason: string }> = [];
      for (const key of await blob.list("rejected/")) {
        if (key.endsWith(".reason")) out.push({ id: key.slice("rejected/".length, -".reason".length), reason: new TextDecoder().decode((await blob.get(key))!) });
      }
      return out;
    },
  };
}

mailInContract("blob inbox", async () => harness());

describe("blob inbox", () => {
  it("moves acknowledged mail to done/ and keeps it", async () => {
    const h = harness();
    await h.deliver(bytes("a"));
    const [mail] = await h.mailIn.poll(5);
    await h.mailIn.ack(mail.id);
    assert.deepEqual(await h.blob.list("inbox/"), []);
    assert.equal((await h.blob.list("done/")).length, 1);
  });

  it("ignores keys that are not mail, such as the S3 setup notification", async () => {
    const h = harness();
    await h.blob.put("inbox/AMAZON_SES_SETUP_NOTIFICATION", bytes("setup"));
    assert.deepEqual(await h.mailIn.poll(5), []);
  });

  it("skips a message over the size limit instead of loading it", async () => {
    const blob = createMemoryBlob();
    const mailIn = createBlobInbox(blob, { verdictOf: async () => "pass", maxBytes: 10 });
    await blob.put("inbox/big", bytes("x".repeat(11)));
    await blob.put("inbox/small", bytes("ok"));
    assert.deepEqual((await mailIn.poll(5)).map((m) => m.id), ["small"]);
    assert.equal((await blob.list("rejected/")).filter((k) => k.endsWith(".reason")).length, 1);
  });
});
