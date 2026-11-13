import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createPipeline } from "../../src/app/pipeline.ts";
import { createMemoryBlob } from "../../src/adapters/memory/blob.ts";
import { createMemoryMailIn } from "../../src/adapters/memory/mail-in.ts";
import { createMemoryExtractor } from "../../src/adapters/memory/extractor.ts";
import { createMemoryStore } from "../../src/adapters/memory/store.ts";
import type { Extractor } from "../../src/ports/extractor.ts";
import { fakeClock, bytes } from "../helpers.ts";

const CO = "acme";
const mail = (id: string, body = "invoice_number: 1042\ntotal: 99.50") =>
  bytes(`From: a@x.test\r\nSubject: Invoice ${id}\r\nMessage-ID: <${id}@x.test>\r\nContent-Type: text/plain\r\n\r\n${body}`);

function setup(extractor: Extractor = createMemoryExtractor()) {
  const mailIn = createMemoryMailIn();
  const store = createMemoryStore(fakeClock());
  const blob = createMemoryBlob();
  const sleeps: number[] = [];
  const pipeline = createPipeline({
    mailIn, store, blob, extractor, companyId: CO, fields: ["invoice_number", "total"],
    sleep: async (ms) => void sleeps.push(ms), retries: 3,
  });
  return { mailIn, store, blob, pipeline, sleeps };
}

describe("pipeline", () => {
  it("turns a passing email into a ready job with extracted values, and acknowledges it", async () => {
    const { mailIn, store, blob, pipeline } = setup();
    await mailIn.deliver(mail("m1"), "pass");
    const result = await pipeline.runOnce();
    assert.deepEqual(result, { processed: 1, ready: 1, held: 0, failed: 0, skipped: 0 });
    const [job] = await store.listJobs(CO);
    assert.equal(job.status, "ready");
    assert.equal(job.subject, "Invoice m1");
    assert.deepEqual((await store.fieldValues(CO, job.id)).map((v) => [v.name, v.value]), [["invoice_number", "1042"], ["total", "99.50"]]);
    assert.deepEqual((await store.history(CO, job.id)).map((h) => h.to), ["received", "processing", "ready"]);
    assert.deepEqual(await mailIn.poll(5), []);
    assert.equal((await blob.list(`mail/${CO}/`)).length, 1);
    assert.equal((await blob.list(`documents/${CO}/${job.id}/`)).length, 1);
  });

  it("holds mail whose sender did not pass, without reading it", async () => {
    let calls = 0;
    const { mailIn, store, pipeline } = setup({ extract: async () => (calls++, { fields: [] }) });
    await mailIn.deliver(mail("m1"), "unknown");
    await mailIn.deliver(mail("m2"), "fail");
    const result = await pipeline.runOnce();
    assert.equal(result.held, 2);
    assert.equal(calls, 0);
    assert.deepEqual((await store.listJobs(CO)).map((j) => j.status), ["held", "held"]);
    assert.deepEqual(await mailIn.poll(5), []);
  });

  it("creates one job for the same email delivered twice", async () => {
    const { mailIn, store, pipeline } = setup();
    await mailIn.deliver(mail("m1"), "pass");
    await mailIn.deliver(mail("m1"), "pass");
    const result = await pipeline.runOnce();
    assert.equal((await store.listJobs(CO)).length, 1);
    assert.equal(result.skipped, 1);
    assert.deepEqual(await mailIn.poll(5), []);
  });

  it("retries a failing extractor with growing waits, then succeeds", async () => {
    let calls = 0;
    const real = createMemoryExtractor();
    const { mailIn, store, pipeline, sleeps } = setup({ extract: async (r) => (++calls < 3 ? Promise.reject(new Error("down")) : real.extract(r)) });
    await mailIn.deliver(mail("m1"), "pass");
    assert.equal((await pipeline.runOnce()).ready, 1);
    assert.equal(calls, 3);
    assert.equal(sleeps.length, 2);
    assert.ok(sleeps[1] > sleeps[0]);
    assert.equal((await store.listJobs(CO))[0].status, "ready");
  });

  it("marks the job failed after the last retry, and does not loop on the same mail forever", async () => {
    const { mailIn, store, pipeline } = setup({ extract: async () => Promise.reject(new Error("down")) });
    await mailIn.deliver(mail("m1"), "pass");
    assert.equal((await pipeline.runOnce()).failed, 1);
    const [job] = await store.listJobs(CO);
    assert.equal(job.status, "failed");
    assert.match((await store.history(CO, job.id)).at(-1)!.note, /down/);
    assert.deepEqual(await mailIn.poll(5), []);
  });

  it("is ready with no values when a document type is unsupported, not failed", async () => {
    const { mailIn, store, pipeline } = setup();
    const pdf = bytes("Message-ID: <p@x>\r\nContent-Type: application/pdf\r\n\r\n%PDF-");
    await mailIn.deliver(pdf, "pass");
    assert.equal((await pipeline.runOnce()).ready, 1);
    const [job] = await store.listJobs(CO);
    assert.deepEqual(await store.fieldValues(CO, job.id), []);
  });

  it("resumes a job left in processing by a crash without adding values twice", async () => {
    const { mailIn, store, pipeline } = setup();
    await mailIn.deliver(mail("m1"), "pass");
    const { job } = await store.createJob(CO, { messageId: "<m1@x.test>", subject: "Invoice m1" });
    await store.advance(CO, job.id, "processing");
    await store.addFieldValue(CO, job.id, { name: "total", value: "99.50", source: "derived" });
    await pipeline.runOnce();
    assert.equal((await store.getJob(CO, job.id))?.status, "ready");
    assert.equal((await store.allFieldValues(CO, job.id)).filter((v) => v.name === "total").length, 1);
  });

  it("rejects mail it cannot make a job from, and carries on with the rest", async () => {
    const { mailIn, store, pipeline } = setup();
    await mailIn.deliver(bytes("junk with no message id"), "pass");
    await mailIn.deliver(mail("m2"), "pass");
    const result = await pipeline.runOnce();
    assert.equal(result.ready, 1);
    assert.equal((await mailIn.rejected()).length, 1);
    assert.equal((await store.listJobs(CO)).length, 1);
  });

  it("only ever writes to the configured company", async () => {
    const { mailIn, store, pipeline } = setup();
    await mailIn.deliver(mail("m1"), "pass");
    await pipeline.runOnce();
    assert.equal((await store.listJobs("someone-else")).length, 0);
  });
});
