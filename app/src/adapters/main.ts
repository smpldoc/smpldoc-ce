// The one place that wires real adapters to the pipeline and the portal. Everything else takes
// its collaborators as arguments, so this is the only file that knows what runs in production.
import { join } from "node:path";
import { createPipeline } from "../app/pipeline.ts";
import { createPortal } from "../app/portal.ts";
import { parseConfig } from "../app/config.ts";
import { createBlobInbox } from "./blob-inbox.ts";
import { createFilesystemBlob } from "./filesystem-blob.ts";
import { serve } from "./http-server.ts";
import { createMemoryExtractor } from "./memory/extractor.ts";
import { createSqliteStore } from "./sqlite/store.ts";

export interface RunningApp {
  port: number;
  pipeline: ReturnType<typeof createPipeline>;
  stop(): Promise<void>;
}

const log = (message: string, detail?: unknown) =>
  console.log(JSON.stringify({ at: new Date().toISOString(), message, ...(detail instanceof Error ? { error: detail.message } : {}) }));

export async function startApp(env: Record<string, string | undefined>): Promise<RunningApp> {
  const config = parseConfig(env);
  const blob = createFilesystemBlob(join(config.dataDir, "blob"));
  const { store, close } = createSqliteStore(join(config.dataDir, "smpldoc.db"), () => new Date().toISOString());
  const mailIn = createBlobInbox(blob, config.inboxTrust === "all" ? { verdictOf: async () => "pass" } : {});
  // Reads plain-text documents only. A real AI service is a separate Extractor adapter, chosen by the operator.
  const extractor = createMemoryExtractor();
  const pipeline = createPipeline({
    mailIn, store, blob, extractor, companyId: config.companyId, fields: config.fields,
    onError: (error, mail) => log(`mail ${mail.id} will be retried`, error),
  });
  const http = await serve(createPortal({ store, companyId: config.companyId, token: config.adminToken }), { host: config.host, port: config.port, log });

  let stopping = false;
  const loop = pipeline.runUntil(() => stopping, config.pollMs).catch((error) => log("pipeline loop stopped", error));
  log("started", undefined);

  return {
    port: http.port,
    pipeline,
    async stop() {
      stopping = true;
      await http.close();
      await loop;
      close();
    },
  };
}
