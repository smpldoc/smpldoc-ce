// The portal: a small web page and JSON API over the Store, as a plain request-to-response
// function so it can be tested without a network. The server adapter feeds it real requests.
//
// Security: everything except /health needs the admin password (HTTP Basic). With no password
// configured nothing can log in. Page text is escaped, the policy header forbids scripts, and a
// form posted from another site is refused.
import { JOB_ACTIONS, allowedActions, isJobAction } from "../domain/workflow.ts";
import type { Job, Store } from "../ports/store.ts";
import { InvalidInputError, InvalidTransitionError, JobNotFoundError } from "../ports/store.ts";

export interface PortalRequest {
  method: string;
  /** Path and query, exactly as sent. */
  path: string;
  /** Header names in lower case. */
  headers: Record<string, string | undefined>;
  body: string;
}

export interface PortalResponse {
  status: number;
  headers: Record<string, string>;
  body: string;
}

export interface PortalDeps {
  store: Store;
  companyId: string;
  /** The admin password. Null means nobody can log in. */
  token: string | null;
}

const SECURITY_HEADERS = {
  "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
  "x-content-type-options": "nosniff",
  "referrer-policy": "no-referrer",
  "cache-control": "no-store",
};

const escapeHtml = (text: string): string =>
  text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

function sameText(a: string, b: string): boolean {
  const x = new TextEncoder().encode(a);
  const y = new TextEncoder().encode(b);
  let diff = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i] ?? 0) ^ (y[i] ?? 0);
  return diff === 0;
}

function login(header: string | undefined, token: string | null): string | null {
  if (token === null || token === "" || !header?.startsWith("Basic ")) return null;
  let decoded: string;
  try {
    decoded = new TextDecoder().decode(Uint8Array.from(atob(header.slice(6)), (c) => c.charCodeAt(0)));
  } catch {
    return null;
  }
  const colon = decoded.indexOf(":");
  if (colon < 0) return null;
  return sameText(decoded.slice(colon + 1), token) ? decoded.slice(0, colon).slice(0, 100) || "admin" : null;
}

const respond = (status: number, body: string, type: string, extra: Record<string, string> = {}): PortalResponse => ({
  status,
  headers: { "content-type": type, ...SECURITY_HEADERS, ...extra },
  body,
});
const json = (status: number, value: unknown) => respond(status, JSON.stringify(value), "application/json; charset=utf-8");
const page = (status: number, title: string, inner: string) =>
  respond(
    status,
    `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(title)}</title>` +
      `<style>body{font:16px/1.5 system-ui,sans-serif;margin:2rem auto;max-width:56rem;padding:0 1rem}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:.4rem .6rem;border-bottom:1px solid #8884}</style>` +
      `<h1><a href="/">smpldoc</a></h1>${inner}</html>`,
    "text/html; charset=utf-8",
  );

function crossSite(req: PortalRequest): boolean {
  const site = req.headers["sec-fetch-site"];
  if (site && site !== "same-origin" && site !== "none") return true;
  const origin = req.headers.origin;
  if (!origin) return false;
  try {
    return new URL(origin).host !== req.headers.host;
  } catch {
    return true;
  }
}

function jobRow(job: Job): string {
  return `<tr><td><a href="/jobs/${encodeURIComponent(job.id)}">${escapeHtml(job.id)}</a></td><td>${escapeHtml(job.subject || "(no subject)")}</td><td>${escapeHtml(job.status)}</td><td>${escapeHtml(job.createdAt)}</td></tr>`;
}

export function createPortal(deps: PortalDeps): (req: PortalRequest) => Promise<PortalResponse> {
  const { store, companyId } = deps;

  return async function handle(req) {
    const url = new URL(req.path, "http://portal.invalid");
    const path = req.path.split("?")[0];
    if (path === "/health") return req.method === "GET" ? json(200, { ok: true }) : json(405, { error: "method not allowed" });

    const actor = login(req.headers.authorization, deps.token);
    if (actor === null) return respond(401, "Sign in with the admin password.", "text/plain; charset=utf-8", { "www-authenticate": 'Basic realm="smpldoc", charset="UTF-8"' });

    try {
      if (req.method === "GET" && path === "/") {
        const jobs = await store.listJobs(companyId, url.searchParams.get("status") ? { status: url.searchParams.get("status") as Job["status"] } : undefined);
        const rows = jobs.map(jobRow).join("");
        return page(200, "Jobs", `<h2>Jobs</h2><table><tr><th>Job</th><th>Subject</th><th>Status</th><th>Received</th></tr>${rows || '<tr><td colspan="4">No jobs yet.</td></tr>'}</table>`);
      }
      if (req.method === "GET" && path === "/api/jobs") return json(200, { jobs: await store.listJobs(companyId) });

      const jobMatch = /^\/(?:api\/)?jobs\/([A-Za-z0-9_-]+)$/.exec(path);
      if (req.method === "GET" && jobMatch) {
        const job = await store.getJob(companyId, jobMatch[1]);
        if (!job) return path.startsWith("/api/") ? json(404, { error: "not found" }) : page(404, "Not found", "<p>No such job.</p>");
        const fields = await store.fieldValues(companyId, job.id);
        const history = await store.history(companyId, job.id);
        const actions = allowedActions(job.status);
        if (path.startsWith("/api/")) return json(200, { job, fields, history, allowedActions: actions });
        const buttons = actions.map((a) => `<button name="action" value="${escapeHtml(a)}">${escapeHtml(a.replace(/_/g, " "))}</button>`).join(" ");
        return page(
          200,
          `Job ${job.id}`,
          `<h2>${escapeHtml(job.subject || "(no subject)")}</h2><p>${escapeHtml(job.id)} · <strong>${escapeHtml(job.status)}</strong></p>` +
            `<h3>Values</h3><table>${fields.map((f) => `<tr><td>${escapeHtml(f.name)}</td><td>${escapeHtml(f.value)}</td><td>${escapeHtml(f.source)}</td></tr>`).join("") || "<tr><td>None found.</td></tr>"}</table>` +
            `<h3>Actions</h3><form method="post" action="/jobs/${encodeURIComponent(job.id)}/actions"><input name="note" maxlength="500" placeholder="Note (optional)"> ${buttons}</form>` +
            `<h3>History</h3><table>${history.map((h) => `<tr><td>${h.seq}</td><td>${escapeHtml(h.at)}</td><td>${escapeHtml(h.actor)}</td><td>${escapeHtml(`${h.from ?? "-"} → ${h.to}`)}</td><td>${escapeHtml(h.note)}</td></tr>`).join("")}</table>`,
        );
      }

      const actionMatch = /^\/(?:api\/)?jobs\/([A-Za-z0-9_-]+)\/actions$/.exec(path);
      if (req.method === "POST" && actionMatch) {
        if (crossSite(req)) return json(403, { error: "cross-site request refused" });
        const isApi = path.startsWith("/api/");
        let action: unknown;
        let note = "";
        if ((req.headers["content-type"] ?? "").startsWith("application/json")) {
          try {
            const parsed = JSON.parse(req.body) as { action?: unknown; note?: unknown };
            action = parsed.action;
            note = typeof parsed.note === "string" ? parsed.note : "";
          } catch {
            return json(400, { error: "invalid JSON" });
          }
        } else {
          const form = new URLSearchParams(req.body);
          action = form.get("action");
          note = form.get("note") ?? "";
        }
        if (!isJobAction(action)) return json(400, { error: `action must be one of ${JOB_ACTIONS.join(", ")}` });
        const job = await store.applyAction(companyId, actionMatch[1], action, actor, note);
        return isApi ? json(200, { job }) : respond(303, "", "text/plain; charset=utf-8", { location: `/jobs/${encodeURIComponent(job.id)}` });
      }
      if (path === "/" || path === "/api/jobs" || jobMatch || actionMatch) return json(405, { error: "method not allowed" });
      return page(404, "Not found", "<p>No such page.</p>");
    } catch (error) {
      if (error instanceof JobNotFoundError) return json(404, { error: "not found" });
      if (error instanceof InvalidTransitionError) return json(409, { error: error.message, status: error.status, allowedActions: error.allowedActions });
      if (error instanceof InvalidInputError) return json(400, { error: error.message });
      throw error;
    }
  };
}
