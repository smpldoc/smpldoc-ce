// One test suite that every Store adapter must pass.
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import type { Clock, Store } from "../../src/ports/store.ts";
import { CompanyRequiredError, InvalidInputError, InvalidTransitionError, JobNotFoundError } from "../../src/ports/store.ts";
import { fakeClock } from "../helpers.ts";

export interface StoreHarness {
  store: Store;
  cleanup?: () => Promise<void>;
}

const A = "company-a";
const B = "company-b";

export function storeContract(name: string, make: (clock: Clock) => Promise<StoreHarness>): void {
  describe(`Store contract: ${name}`, () => {
    async function fresh(): Promise<Store> {
      return (await make(fakeClock())).store;
    }

    describe("pipeline notes", () => {
      it("records the note given when the pipeline moves a job, and refuses an oversized one", async () => {
        const store = await fresh();
        const { job } = await store.createJob(A, { messageId: "<n1@x>" });
        await store.advance(A, job.id, "processing");
        await store.advance(A, job.id, "failed", "extractor down");
        assert.equal((await store.history(A, job.id)).at(-1)?.note, "extractor down");
        const other = await store.createJob(A, { messageId: "<n2@x>" });
        await assert.rejects(store.advance(A, other.job.id, "processing", "n".repeat(501)), InvalidInputError);
        assert.equal((await store.getJob(A, other.job.id))?.status, "received");
      });
    });

    describe("creating jobs", () => {
      it("starts a job as received, with one history entry", async () => {
        const store = await fresh();
        const { job, created } = await store.createJob(A, { messageId: "<m1@x>", subject: "Invoice" });
        assert.equal(created, true);
        assert.equal(job.status, "received");
        assert.equal(job.companyId, A);
        assert.equal(job.subject, "Invoice");
        const history = await store.history(A, job.id);
        assert.equal(history.length, 1);
        assert.deepEqual([history[0].seq, history[0].from, history[0].to, history[0].action], [1, null, "received", "create"]);
      });

      it("returns the same job for the same message id, and adds no history", async () => {
        const store = await fresh();
        const first = await store.createJob(A, { messageId: "<m1@x>" });
        const second = await store.createJob(A, { messageId: "<m1@x>" });
        assert.equal(second.created, false);
        assert.equal(second.job.id, first.job.id);
        assert.equal((await store.history(A, first.job.id)).length, 1);
      });

      it("keeps the same message id in two companies as two separate jobs", async () => {
        const store = await fresh();
        const a = await store.createJob(A, { messageId: "<m1@x>" });
        const b = await store.createJob(B, { messageId: "<m1@x>" });
        assert.notEqual(a.job.id, b.job.id);
        assert.equal(b.created, true);
      });

      it("refuses an empty or oversized message id or subject or note", async () => {
        const store = await fresh();
        await assert.rejects(store.createJob(A, { messageId: "" }), InvalidInputError);
        await assert.rejects(store.createJob(A, { messageId: "m".repeat(999) }), InvalidInputError);
        await assert.rejects(store.createJob(A, { messageId: "<ok@x>", subject: "s".repeat(1001) }), InvalidInputError);
      });

      it("gives every job its own id", async () => {
        const store = await fresh();
        const a = await store.createJob(A, { messageId: "1" });
        const b = await store.createJob(A, { messageId: "2" });
        assert.ok(a.job.id.length > 0);
        assert.notEqual(a.job.id, b.job.id);
      });
    });

    describe("company scoping", () => {
      it("refuses every call that has no company", async () => {
        const store = await fresh();
        for (const company of ["", "   "]) {
          await assert.rejects(store.createJob(company, { messageId: "m" }), CompanyRequiredError);
          await assert.rejects(store.getJob(company, "j"), CompanyRequiredError);
          await assert.rejects(store.listJobs(company), CompanyRequiredError);
          await assert.rejects(store.advance(company, "j", "processing"), CompanyRequiredError);
          await assert.rejects(store.applyAction(company, "j", "close", "me"), CompanyRequiredError);
          await assert.rejects(store.history(company, "j"), CompanyRequiredError);
          await assert.rejects(store.addFieldValue(company, "j", { name: "n", value: "v", source: "derived" }), CompanyRequiredError);
          await assert.rejects(store.fieldValues(company, "j"), CompanyRequiredError);
          await assert.rejects(store.allFieldValues(company, "j"), CompanyRequiredError);
        }
      });

      it("hides a job from every other company, and treats it exactly like a missing job", async () => {
        const store = await fresh();
        const { job } = await store.createJob(A, { messageId: "m" });
        assert.equal(await store.getJob(B, job.id), null);
        assert.deepEqual(await store.listJobs(B), []);
        await assert.rejects(store.advance(B, job.id, "processing"), JobNotFoundError);
        await assert.rejects(store.applyAction(B, job.id, "close", "me"), JobNotFoundError);
        await assert.rejects(store.history(B, job.id), JobNotFoundError);
        await assert.rejects(store.addFieldValue(B, job.id, { name: "n", value: "v", source: "derived" }), JobNotFoundError);
        await assert.rejects(store.fieldValues(B, job.id), JobNotFoundError);
        await assert.rejects(store.allFieldValues(B, job.id), JobNotFoundError);
        await assert.rejects(store.advance(A, "no-such-job", "processing"), JobNotFoundError);
        assert.equal((await store.getJob(A, job.id))?.status, "received");
      });
    });

    describe("listing", () => {
      it("lists this company's jobs, newest first, and can filter by status", async () => {
        const store = await fresh();
        const first = (await store.createJob(A, { messageId: "1" })).job;
        const second = (await store.createJob(A, { messageId: "2" })).job;
        await store.createJob(B, { messageId: "3" });
        await store.advance(A, first.id, "processing");
        assert.deepEqual((await store.listJobs(A)).map((j) => j.id), [second.id, first.id]);
        assert.deepEqual((await store.listJobs(A, { status: "processing" })).map((j) => j.id), [first.id]);
        assert.deepEqual(await store.listJobs(A, { status: "closed" }), []);
      });
    });

    describe("moving jobs", () => {
      it("lets the pipeline move a job forward and records each move", async () => {
        const store = await fresh();
        const { job } = await store.createJob(A, { messageId: "m" });
        await store.advance(A, job.id, "processing");
        const ready = await store.advance(A, job.id, "ready");
        assert.equal(ready.status, "ready");
        const history = await store.history(A, job.id);
        assert.deepEqual(history.map((h) => [h.seq, h.from, h.to]), [[1, null, "received"], [2, "received", "processing"], [3, "processing", "ready"]]);
      });

      it("refuses a pipeline move that is not allowed, and changes nothing", async () => {
        const store = await fresh();
        const { job } = await store.createJob(A, { messageId: "m" });
        await assert.rejects(store.advance(A, job.id, "ready"), InvalidTransitionError);
        assert.equal((await store.getJob(A, job.id))?.status, "received");
        assert.equal((await store.history(A, job.id)).length, 1);
      });

      it("applies a person's action with who did it and their note", async () => {
        const store = await fresh();
        const { job } = await store.createJob(A, { messageId: "m" });
        const closed = await store.applyAction(A, job.id, "close", "ben", "Paid, filed");
        assert.equal(closed.status, "closed");
        const last = (await store.history(A, job.id)).at(-1)!;
        assert.deepEqual([last.actor, last.action, last.note, last.from, last.to], ["ben", "close", "Paid, filed", "received", "closed"]);
      });

      it("refuses an action that is not allowed, says what is allowed, and changes nothing", async () => {
        const store = await fresh();
        const { job } = await store.createJob(A, { messageId: "m" });
        await store.applyAction(A, job.id, "close", "ben");
        await assert.rejects(store.applyAction(A, job.id, "close", "ben"), (error: unknown) => {
          assert.ok(error instanceof InvalidTransitionError);
          assert.equal(error.status, "closed");
          assert.deepEqual(error.allowedActions, ["reprocess", "reopen"]);
          return true;
        });
        assert.equal((await store.history(A, job.id)).length, 2);
      });

      it("can reopen a closed job", async () => {
        const store = await fresh();
        const { job } = await store.createJob(A, { messageId: "m" });
        await store.applyAction(A, job.id, "close", "ben");
        assert.equal((await store.applyAction(A, job.id, "reopen", "ben")).status, "ready");
      });

      it("refuses a note over 500 characters", async () => {
        const store = await fresh();
        const { job } = await store.createJob(A, { messageId: "m" });
        await assert.rejects(store.applyAction(A, job.id, "close", "ben", "n".repeat(501)), InvalidInputError);
        assert.equal((await store.getJob(A, job.id))?.status, "received");
      });

      it("refuses an actor that is empty", async () => {
        const store = await fresh();
        const { job } = await store.createJob(A, { messageId: "m" });
        await assert.rejects(store.applyAction(A, job.id, "close", ""), InvalidInputError);
      });

      it("keeps the created time and moves the updated time", async () => {
        const store = await fresh();
        const { job } = await store.createJob(A, { messageId: "m" });
        const moved = await store.advance(A, job.id, "processing");
        assert.equal(moved.createdAt, job.createdAt);
        assert.ok(Date.parse(moved.updatedAt) > Date.parse(job.updatedAt));
      });
    });

    describe("history", () => {
      it("is returned as a copy, so changing it never changes the store", async () => {
        const store = await fresh();
        const { job } = await store.createJob(A, { messageId: "m" });
        const history = await store.history(A, job.id);
        history.pop();
        assert.equal((await store.history(A, job.id)).length, 1);
      });
    });

    describe("field values", () => {
      async function jobWith(store: Store): Promise<string> {
        return (await store.createJob(A, { messageId: "m" })).job.id;
      }

      it("uses a derived value until someone corrects it", async () => {
        const store = await fresh();
        const id = await jobWith(store);
        await store.addFieldValue(A, id, { name: "total", value: "100", source: "derived" });
        assert.equal((await store.fieldValues(A, id))[0].value, "100");
        await store.addFieldValue(A, id, { name: "total", value: "120", source: "correction" });
        assert.equal((await store.fieldValues(A, id))[0].value, "120");
      });

      it("keeps a correction when a later run derives a new value", async () => {
        const store = await fresh();
        const id = await jobWith(store);
        await store.addFieldValue(A, id, { name: "total", value: "120", source: "correction" });
        await store.addFieldValue(A, id, { name: "total", value: "999", source: "derived" });
        const [effective] = await store.fieldValues(A, id);
        assert.deepEqual([effective.value, effective.source], ["120", "correction"]);
      });

      it("uses the latest value of the same source", async () => {
        const store = await fresh();
        const id = await jobWith(store);
        await store.addFieldValue(A, id, { name: "total", value: "1", source: "derived" });
        await store.addFieldValue(A, id, { name: "total", value: "2", source: "derived" });
        assert.equal((await store.fieldValues(A, id))[0].value, "2");
      });

      it("returns one value per field, and never overwrites the log", async () => {
        const store = await fresh();
        const id = await jobWith(store);
        await store.addFieldValue(A, id, { name: "total", value: "1", source: "derived" });
        await store.addFieldValue(A, id, { name: "number", value: "7", source: "derived" });
        await store.addFieldValue(A, id, { name: "total", value: "2", source: "correction" });
        assert.deepEqual((await store.fieldValues(A, id)).map((f) => f.name).sort(), ["number", "total"]);
        assert.deepEqual((await store.allFieldValues(A, id)).map((f) => [f.name, f.value, f.source]), [
          ["total", "1", "derived"], ["number", "7", "derived"], ["total", "2", "correction"],
        ]);
      });

      it("refuses an empty field name, an unknown source and an oversized value", async () => {
        const store = await fresh();
        const id = await jobWith(store);
        await assert.rejects(store.addFieldValue(A, id, { name: "", value: "v", source: "derived" }), InvalidInputError);
        await assert.rejects(store.addFieldValue(A, id, { name: "n", value: "v", source: "guess" as never }), InvalidInputError);
        await assert.rejects(store.addFieldValue(A, id, { name: "n", value: "v".repeat(100_001), source: "derived" }), InvalidInputError);
        assert.deepEqual(await store.allFieldValues(A, id), []);
      });
    });
  });
}
