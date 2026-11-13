import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createPortal } from "../../src/app/portal.ts";
import type { PortalRequest } from "../../src/app/portal.ts";
import { createMemoryStore } from "../../src/adapters/memory/store.ts";
import { fakeClock } from "../helpers.ts";

const CO = "acme";
const basic = (password: string) => "Basic " + btoa(`admin:${password}`);

async function setup(token: string | null = "s3cret") {
  const store = createMemoryStore(fakeClock());
  const { job } = await store.createJob(CO, { messageId: "<m1@x>", subject: "<script>alert(1)</script>" });
  await store.advance(CO, job.id, "processing");
  await store.addFieldValue(CO, job.id, { name: "total", value: "99.50", source: "derived" });
  await store.advance(CO, job.id, "ready");
  const portal = createPortal({ store, companyId: CO, token });
  const get = (path: string, headers: PortalRequest["headers"] = { authorization: basic("s3cret") }) => portal({ method: "GET", path, headers, body: "" });
  const post = (path: string, body: string, headers: PortalRequest["headers"] = {}) =>
    portal({ method: "POST", path, headers: { authorization: basic("s3cret"), host: "localhost:3787", "content-type": "application/x-www-form-urlencoded", ...headers }, body });
  return { store, job, portal, get, post };
}

describe("portal", () => {
  it("answers /health without a login, and says nothing else", async () => {
    const { get } = await setup();
    const res = await get("/health", {});
    assert.equal(res.status, 200);
    assert.deepEqual(JSON.parse(res.body), { ok: true });
  });

  it("asks for a login on every other page, and refuses a wrong password", async () => {
    const { get } = await setup();
    for (const path of ["/", "/api/jobs"]) {
      const none = await get(path, {});
      assert.equal(none.status, 401);
      assert.match(none.headers["www-authenticate"] ?? "", /^Basic/);
      assert.equal((await get(path, { authorization: basic("wrong") })).status, 401);
    }
  });

  it("lists jobs and shows hostile text as text", async () => {
    const { get } = await setup();
    const res = await get("/");
    assert.equal(res.status, 200);
    assert.ok(!res.body.includes("<script>alert(1)</script>"));
    assert.ok(res.body.includes("&lt;script&gt;alert(1)&lt;/script&gt;"));
    assert.match(res.headers["content-security-policy"] ?? "", /default-src 'none'/);
    assert.equal(res.headers["x-content-type-options"], "nosniff");
  });

  it("shows a job's values, history and the actions allowed now", async () => {
    const { get, job } = await setup();
    const res = await get(`/jobs/${job.id}`);
    assert.equal(res.status, 200);
    assert.ok(res.body.includes("99.50"));
    assert.ok(res.body.includes("processing"));
    assert.ok(res.body.includes('value="close"'));
    assert.ok(!res.body.includes('value="reopen"'));
  });

  it("applies an action from the form, then redirects back to the job", async () => {
    const { post, store, job } = await setup();
    const res = await post(`/jobs/${job.id}/actions`, "action=close&note=done");
    assert.equal(res.status, 303);
    assert.equal(res.headers.location, `/jobs/${job.id}`);
    assert.equal((await store.getJob(CO, job.id))?.status, "closed");
    assert.equal((await store.history(CO, job.id)).at(-1)?.actor, "admin");
  });

  it("refuses a move that is not allowed, and changes nothing", async () => {
    const { post, store, job } = await setup();
    const res = await post(`/jobs/${job.id}/actions`, "action=reopen");
    assert.equal(res.status, 409);
    assert.equal((await store.getJob(CO, job.id))?.status, "ready");
    assert.equal((await post(`/jobs/${job.id}/actions`, "action=explode")).status, 400);
  });

  it("refuses a form posted from another site", async () => {
    const { post, store, job } = await setup();
    const res = await post(`/jobs/${job.id}/actions`, "action=close", { origin: "https://evil.test" });
    assert.equal(res.status, 403);
    assert.equal((await store.getJob(CO, job.id))?.status, "ready");
    const sameSite = await post(`/jobs/${job.id}/actions`, "action=close", { origin: "http://localhost:3787" });
    assert.equal(sameSite.status, 303);
  });

  it("serves the same data as JSON for scripts", async () => {
    const { get, job } = await setup();
    const list = JSON.parse((await get("/api/jobs")).body);
    assert.equal(list.jobs.length, 1);
    const one = JSON.parse((await get(`/api/jobs/${job.id}`)).body);
    assert.equal(one.job.id, job.id);
    assert.equal(one.fields[0].name, "total");
    assert.ok(one.allowedActions.includes("close"));
  });

  it("returns 404 for an unknown job or page and 405 for the wrong method", async () => {
    const { get, portal } = await setup();
    assert.equal((await get("/jobs/nope")).status, 404);
    assert.equal((await get("/nothing")).status, 404);
    const res = await portal({ method: "DELETE", path: "/", headers: { authorization: basic("s3cret") }, body: "" });
    assert.equal(res.status, 405);
  });

  it("with no token configured it refuses everything except /health (fail closed)", async () => {
    const { get } = await setup(null);
    assert.equal((await get("/", { authorization: basic("") })).status, 401);
    assert.equal((await get("/health", {})).status, 200);
  });

  it("does not let a path trick reach another handler", async () => {
    const { get } = await setup();
    assert.equal((await get("/jobs/../health", {})).status, 401);
    assert.equal((await get("//api/jobs")).status, 404);
  });
});
