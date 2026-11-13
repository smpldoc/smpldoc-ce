// Serves the portal over HTTP with Node's own server. It only moves bytes: parsing a request into
// the portal's shape, a size limit on the body, and writing the response back.
import { createServer } from "node:http";
import type { IncomingMessage } from "node:http";
import type { PortalRequest, PortalResponse } from "../app/portal.ts";

const MAX_BODY = 64 * 1024;

export interface HttpServer {
  port: number;
  close(): Promise<void>;
}

function readBody(req: IncomingMessage): Promise<string | null> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let size = 0;
    req.on("data", (chunk: Buffer) => {
      size += chunk.length;
      if (size > MAX_BODY) {
        resolve(null);
        req.destroy();
      } else chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

export async function serve(
  handler: (req: PortalRequest) => Promise<PortalResponse>,
  options: { host: string; port: number; log?: (message: string, detail?: unknown) => void },
): Promise<HttpServer> {
  const server = createServer(async (req, res) => {
    try {
      const body = await readBody(req);
      if (body === null) {
        res.writeHead(413, { "content-type": "text/plain" }).end("Request too large");
        return;
      }
      const headers: PortalRequest["headers"] = {};
      for (const [name, value] of Object.entries(req.headers)) headers[name] = Array.isArray(value) ? value[0] : value;
      const out = await handler({ method: req.method ?? "GET", path: req.url ?? "/", headers, body });
      res.writeHead(out.status, out.headers).end(out.body);
    } catch (error) {
      options.log?.("request failed", error);
      if (!res.headersSent) res.writeHead(500, { "content-type": "text/plain" });
      res.end("Something went wrong");
    }
  });
  server.headersTimeout = 10_000;
  server.requestTimeout = 15_000;
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(options.port, options.host, resolve);
  });
  const address = server.address();
  const port = typeof address === "object" && address ? address.port : options.port;
  return {
    port,
    close: () =>
      new Promise<void>((resolve) => {
        server.close(() => resolve());
        server.closeAllConnections();
      }),
  };
}
