import { blobContract } from "../contract/blob.contract.ts";
import { mailInContract } from "../contract/mail-in.contract.ts";
import { mailOutContract } from "../contract/mail-out.contract.ts";
import { extractorContract } from "../contract/extractor.contract.ts";
import { storeContract } from "../contract/store.contract.ts";
import { createMemoryBlob } from "../../src/adapters/memory/blob.ts";
import { createMemoryMailIn } from "../../src/adapters/memory/mail-in.ts";
import { createMemoryMailOut } from "../../src/adapters/memory/mail-out.ts";
import { createMemoryExtractor } from "../../src/adapters/memory/extractor.ts";
import { createMemoryStore } from "../../src/adapters/memory/store.ts";
import { bytes } from "../helpers.ts";

blobContract("memory", async () => ({ blob: createMemoryBlob() }));

mailInContract("memory", async () => {
  const memory = createMemoryMailIn();
  return { mailIn: memory, deliver: memory.deliver, rejected: memory.rejected };
});

mailOutContract("memory", async () => {
  const memory = createMemoryMailOut();
  return { mailOut: memory, sent: memory.sent };
});

extractorContract("memory text", async () => ({
  extractor: createMemoryExtractor(),
  supported: { contentType: "text/plain", data: bytes("invoice_number: 1042\ntotal: 99.50\n"), holds: { invoice_number: "1042", total: "99.50" } },
  unsupportedContentType: "application/pdf",
}));

storeContract("memory", async (clock) => ({ store: createMemoryStore(clock) }));
