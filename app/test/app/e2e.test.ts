// The whole thing, for real: SQLite on disk, a folder as the bucket, an HTTP port, mail dropped
// into the inbox. This is the same wiring the container runs.
import { describe, it, after, before } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { startApp } from "../../src/adapters/main.ts";
import type { RunningApp } from "../../src/adapters/main.ts";

const TOKEN = "test-token-123456";
const auth = { authorization: "Basic " + btoa(`admin:${TOKEN}`) };
const eml = (id: string, extra = "") =>
  `From: a@x.test\r\nSubject: Invoice ${id}\r\nMessage-ID: <${id}@x.test>\r\n${extra}Content-Type: text/plain\r\n\r\ninvoice_number: ${id}\r\ntotal: 12.00\r\n`;

describe("end to end", () => {
  let dir: string;
  let app: RunningApp;
  const base = () => `http://127.0.0.1:${app.port}`;

  before(async () => {
    dir = mkdtempSync(join(tmpdir(), "smpldoc-e2e-"));
    mkdirSync(join(dir, "blob", "inbox"), { recursive: true });
    app = await startApp({ SMPLDOC_ADMIN_TOKEN: TOKEN, SMPLDOC_DATA_DIR: dir, SMPLDOC_PORT: "0", SMPLDOC_INBOX_TRUST: "all", SMPLDOC_POLL_SECONDS: "1" });
  });
  after(async () => {
    await app.stop();
    rmSync(dir, { recursive: true, force: true });
  });

  it("answers /health and keeps the portal behind the password", async () => {
    assert.equal((await fetch(`${base()}/health`)).status, 200);
    assert.equal((await fetch(`${base()}/api/jobs`)).status, 401);
  });

  it("turns a dropped email into a ready job with values, and moves the file to done/", async () => {
    writeFileSync(join(dir, "blob", "inbox", "msg-1"), eml("1042"));
    await app.pipeline.runOnce();
    const list = (await (await fetch(`${base()}/api/jobs`, { headers: auth })).json()) as { jobs: Array<{ id: string; status: string }> };
    assert.equal(list.jobs.length, 1);
    assert.equal(list.jobs[0].status, "ready");
    const detail = (await (await fetch(`${base()}/api/jobs/${list.jobs[0].id}`, { headers: auth })).json()) as { fields: Array<{ name: string; value: string }> };
    assert.deepEqual(detail.fields.map((f) => [f.name, f.value]), [["invoice_number", "1042"], ["total", "12.00"]]);
    assert.ok(existsSync(join(dir, "blob", "done", "msg-1")));
    assert.ok(!existsSync(join(dir, "blob", "inbox", "msg-1")));
  });

  it("lets a person close the job through the API", async () => {
    const list = (await (await fetch(`${base()}/api/jobs`, { headers: auth })).json()) as { jobs: Array<{ id: string }> };
    const res = await fetch(`${base()}/api/jobs/${list.jobs[0].id}/actions`, {
      method: "POST",
      headers: { ...auth, "content-type": "application/json" },
      body: JSON.stringify({ action: "close", note: "paid" }),
    });
    assert.equal(res.status, 200);
    assert.equal(((await res.json()) as { job: { status: string } }).job.status, "closed");
  });

  it("keeps working data after a restart", async () => {
    await app.stop();
    app = await startApp({ SMPLDOC_ADMIN_TOKEN: TOKEN, SMPLDOC_DATA_DIR: dir, SMPLDOC_PORT: "0", SMPLDOC_INBOX_TRUST: "all", SMPLDOC_POLL_SECONDS: "1" });
    const list = (await (await fetch(`${base()}/api/jobs`, { headers: auth })).json()) as { jobs: Array<{ status: string }> };
    assert.deepEqual(list.jobs.map((j) => j.status), ["closed"]);
  });

  it("runs the poll loop by itself", async () => {
    writeFileSync(join(dir, "blob", "inbox", "msg-2"), eml("2001"));
    const deadline = Date.now() + 8000;
    let count = 0;
    while (Date.now() < deadline && count < 2) {
      await new Promise((r) => setTimeout(r, 200));
      count = ((await (await fetch(`${base()}/api/jobs`, { headers: auth })).json()) as { jobs: unknown[] }).jobs.length;
    }
    assert.equal(count, 2);
  });

  it("holds mail whose sender is unverified when trust is not 'all'", async () => {
    const strict = mkdtempSync(join(tmpdir(), "smpldoc-strict-"));
    mkdirSync(join(strict, "blob", "inbox"), { recursive: true });
    const other = await startApp({ SMPLDOC_ADMIN_TOKEN: TOKEN, SMPLDOC_DATA_DIR: strict, SMPLDOC_PORT: "0", SMPLDOC_POLL_SECONDS: "60" });
    try {
      writeFileSync(join(strict, "blob", "inbox", "forged"), eml("666", "X-SES-Spam-Verdict: PASS\r\nX-SES-Virus-Verdict: PASS\r\nX-SES-DMARC-Verdict: PASS\r\nX-SES-Spam-Verdict: PASS\r\n"));
      await other.pipeline.runOnce();
      const list = (await (await fetch(`http://127.0.0.1:${other.port}/api/jobs`, { headers: auth })).json()) as { jobs: Array<{ status: string }> };
      assert.deepEqual(list.jobs.map((j) => j.status), ["held"]);
    } finally {
      await other.stop();
      rmSync(strict, { recursive: true, force: true });
    }
  });
});
