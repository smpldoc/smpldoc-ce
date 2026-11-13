import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { ConfigError, parseConfig } from "../../src/app/config.ts";

const token = "a-long-enough-secret";

describe("parseConfig", () => {
  it("has safe defaults: loopback only, one company, text fields", () => {
    const c = parseConfig({ SMPLDOC_ADMIN_TOKEN: token });
    assert.deepEqual([c.host, c.port, c.companyId, c.dataDir, c.inboxTrust], ["127.0.0.1", 3787, "default", "/data", "ses"]);
    assert.ok(c.fields.length > 0);
  });

  it("reads every setting from the environment", () => {
    const c = parseConfig({
      SMPLDOC_ADMIN_TOKEN: token, SMPLDOC_HOST: "0.0.0.0", SMPLDOC_PORT: "8080", SMPLDOC_COMPANY: "acme",
      SMPLDOC_DATA_DIR: "/var/smpldoc", SMPLDOC_FIELDS: "po_number, total ,", SMPLDOC_INBOX_TRUST: "all", SMPLDOC_POLL_SECONDS: "5",
    });
    assert.deepEqual([c.host, c.port, c.companyId, c.dataDir, c.inboxTrust, c.pollMs], ["0.0.0.0", 8080, "acme", "/var/smpldoc", "all", 5000]);
    assert.deepEqual(c.fields, ["po_number", "total"]);
  });

  it("accepts port 0, meaning any free port (used by tests)", () => {
    assert.equal(parseConfig({ SMPLDOC_ADMIN_TOKEN: token, SMPLDOC_PORT: "0" }).port, 0);
  });

  it("refuses to start without an admin token of a sensible length", () => {
    assert.throws(() => parseConfig({}), ConfigError);
    assert.throws(() => parseConfig({ SMPLDOC_ADMIN_TOKEN: "short" }), /at least 12/);
  });

  it("refuses bad ports, bad company ids and unknown trust modes", () => {
    for (const bad of [{ SMPLDOC_PORT: "-1" }, { SMPLDOC_PORT: "70000" }, { SMPLDOC_PORT: "abc" }, { SMPLDOC_COMPANY: "a/b" }, { SMPLDOC_COMPANY: "" }, { SMPLDOC_INBOX_TRUST: "yes" }, { SMPLDOC_FIELDS: "Bad Field" }]) {
      assert.throws(() => parseConfig({ SMPLDOC_ADMIN_TOKEN: token, ...bad }), ConfigError, JSON.stringify(bad));
    }
  });
});
