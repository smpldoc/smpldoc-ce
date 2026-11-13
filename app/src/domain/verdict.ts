// Turns the scan results Amazon SES adds to a message into one sender verdict.
// "pass" needs spam, virus and DMARC all to pass. Any failure is "fail". Everything else,
// including a missing, grey or disabled check, is "unknown", and unknown mail is held.
//
// A sender controls the headers inside their own message, so a verdict header that appears
// more than once is never trusted: SES adds one copy and a forger would add another.
// Pure: it imports nothing.

export type Verdict = "pass" | "fail" | "unknown";

const CHECKS = ["x-ses-spam-verdict", "x-ses-virus-verdict", "x-ses-dmarc-verdict"] as const;

export function verdictFromHeaders(headers: Record<string, string[]>): Verdict {
  const values: string[] = [];
  for (const name of CHECKS) {
    const found = headers[name];
    if (!found || found.length !== 1) return "unknown";
    values.push(found[0].trim().toUpperCase());
  }
  if (values.includes("FAIL")) return "fail";
  return values.every((v) => v === "PASS") ? "pass" : "unknown";
}
