import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { storeContract } from "../contract/store.contract.ts";
import { createSqliteStore } from "../../src/adapters/sqlite/store.ts";
import { fakeClock } from "../helpers.ts";

// The same suite the in-memory store passes.
storeContract("sqlite (in memory)", async (clock) => {
  const handle = createSqliteStore(":memory:", clock);
  return { store: handle.store, cleanup: async () => handle.close() };
});

describe("sqlite store on disk", () => {
  function tempFile(): { path: string; remove: () => void } {
    const dir = mkdtempSync(join(tmpdir(), "smpldoc-"));
    return { path: join(dir, "smpldoc.db"), remove: () => rmSync(dir, { recursive: true, force: true }) };
  }

  it("keeps jobs, history and values after the file is closed and reopened", async () => {
    const file = tempFile();
    try {
      const first = createSqliteStore(file.path, fakeClock());
      const { job } = await first.store.createJob("co", { messageId: "<m@x>", subject: "Hello" });
      await first.store.advance("co", job.id, "processing");
      await first.store.addFieldValue("co", job.id, { name: "total", value: "9", source: "derived" });
      first.close();

      const second = createSqliteStore(file.path, fakeClock());
      assert.equal((await second.store.getJob("co", job.id))?.status, "processing");
      assert.equal((await second.store.history("co", job.id)).length, 2);
      assert.deepEqual((await second.store.fieldValues("co", job.id)).map((v) => v.value), ["9"]);
      // ids keep counting from where they left off, they are never reused
      const next = await second.store.createJob("co", { messageId: "<m2@x>" });
      assert.notEqual(next.job.id, job.id);
      second.close();
    } finally {
      file.remove();
    }
  });

  it("stops a history row being changed or removed once written (append only)", () => {
    const handle = createSqliteStore(":memory:", fakeClock());
    handle.db.exec("INSERT INTO job (id, company_id, message_id, subject, status, created_at, updated_at) VALUES ('j','c','m','','received','t','t')");
    handle.db.exec("INSERT INTO history (job_id, seq, at, actor, from_status, to_status, action, note) VALUES ('j',1,'t','a',NULL,'received','create','')");
    assert.throws(() => handle.db.exec("UPDATE history SET note='x'"), /append-only/);
    assert.throws(() => handle.db.exec("DELETE FROM history"), /append-only/);
    handle.close();
  });

  it("does not let a quote in company, message id or subject break out of the query", async () => {
    const handle = createSqliteStore(":memory:", fakeClock());
    const evil = "x'); DROP TABLE job; --";
    const { job } = await handle.store.createJob(evil, { messageId: evil, subject: evil });
    assert.equal((await handle.store.getJob(evil, job.id))?.subject, evil);
    assert.equal((await handle.store.listJobs(evil)).length, 1);
    handle.close();
  });
});
