import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { parseMessage } from "../../src/domain/mime.ts";
import { verdictFromHeaders } from "../../src/domain/verdict.ts";
import { bytes } from "../helpers.ts";

const verdict = (headers: string[]) => verdictFromHeaders(parseMessage(bytes(headers.join("\n") + "\n\nbody")).headers);

describe("verdictFromHeaders (Amazon SES scan results)", () => {
  const ok = ["X-SES-Spam-Verdict: PASS", "X-SES-Virus-Verdict: PASS", "X-SES-DMARC-Verdict: PASS"];
  it("passes when spam, virus and DMARC all pass", () => assert.equal(verdict(ok), "pass"));
  it("fails when any check fails", () => {
    assert.equal(verdict(["X-SES-Spam-Verdict: FAIL", "X-SES-Virus-Verdict: PASS", "X-SES-DMARC-Verdict: PASS"]), "fail");
    assert.equal(verdict(["X-SES-Spam-Verdict: PASS", "X-SES-Virus-Verdict: FAIL", "X-SES-DMARC-Verdict: PASS"]), "fail");
    assert.equal(verdict(["X-SES-Spam-Verdict: PASS", "X-SES-Virus-Verdict: PASS", "X-SES-DMARC-Verdict: FAIL"]), "fail");
  });
  it("is unknown when a check is missing, grey or disabled", () => {
    assert.equal(verdict(["X-SES-Spam-Verdict: PASS", "X-SES-Virus-Verdict: PASS"]), "unknown");
    assert.equal(verdict(["X-SES-Spam-Verdict: GRAY", "X-SES-Virus-Verdict: PASS", "X-SES-DMARC-Verdict: PASS"]), "unknown");
    assert.equal(verdict(["X-SES-Spam-Verdict: DISABLED", "X-SES-Virus-Verdict: PASS", "X-SES-DMARC-Verdict: PASS"]), "unknown");
    assert.equal(verdict([]), "unknown");
  });
  it("is unknown, never pass, when a verdict header appears twice (a sender may forge one)", () => {
    assert.equal(verdict([...ok, "X-SES-Spam-Verdict: PASS"]), "unknown");
  });
  it("never reads an ordinary 'Authentication-Results: dmarc=pass' header as proof", () => {
    assert.equal(verdict(["Authentication-Results: x; dmarc=pass"]), "unknown");
  });
});
