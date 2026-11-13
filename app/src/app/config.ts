// Settings come from environment variables and are checked once at start-up, so a typo stops the
// container at once with a clear message instead of failing later. Pure: it reads a plain object.

export class ConfigError extends Error {}

export interface Config {
  host: string;
  port: number;
  adminToken: string;
  companyId: string;
  dataDir: string;
  fields: string[];
  /** "ses": trust the scan results SES adds. "all": trust every message dropped in the inbox (local trials only). */
  inboxTrust: "ses" | "all";
  pollMs: number;
}

type Env = Record<string, string | undefined>;

function whole(env: Env, name: string, fallback: number, min: number, max: number): number {
  const raw = env[name];
  if (raw === undefined || raw === "") return fallback;
  const n = Number(raw);
  if (!Number.isInteger(n) || n < min || n > max) throw new ConfigError(`${name} must be a whole number from ${min} to ${max}`);
  return n;
}

export function parseConfig(env: Env): Config {
  const adminToken = env.SMPLDOC_ADMIN_TOKEN ?? "";
  if (adminToken === "") throw new ConfigError("SMPLDOC_ADMIN_TOKEN is required: it is the portal password");
  if (adminToken.length < 12) throw new ConfigError("SMPLDOC_ADMIN_TOKEN must be at least 12 characters");

  const companyId = env.SMPLDOC_COMPANY ?? "default";
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(companyId)) throw new ConfigError("SMPLDOC_COMPANY must be 1 to 64 letters, digits, - or _");

  const fields = (env.SMPLDOC_FIELDS ?? "invoice_number,total,due_date")
    .split(",")
    .map((f) => f.trim())
    .filter(Boolean);
  if (fields.length === 0 || fields.some((f) => !/^[a-z][a-z0-9_]{0,63}$/.test(f))) {
    throw new ConfigError("SMPLDOC_FIELDS must be comma separated names in lower case letters, digits and _");
  }

  const inboxTrust = env.SMPLDOC_INBOX_TRUST ?? "ses";
  if (inboxTrust !== "ses" && inboxTrust !== "all") throw new ConfigError('SMPLDOC_INBOX_TRUST must be "ses" or "all"');

  return {
    host: env.SMPLDOC_HOST || "127.0.0.1",
    port: whole(env, "SMPLDOC_PORT", 3787, 0, 65535),
    adminToken,
    companyId,
    dataDir: env.SMPLDOC_DATA_DIR || "/data",
    fields,
    inboxTrust,
    pollMs: whole(env, "SMPLDOC_POLL_SECONDS", 10, 1, 3600) * 1000,
  };
}
