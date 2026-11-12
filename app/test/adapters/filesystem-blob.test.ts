import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm, symlink, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { blobContract } from "../contract/blob.contract.ts";
import { createFilesystemBlob } from "../../src/adapters/filesystem-blob.ts";
import { InvalidKeyError } from "../../src/ports/keys.ts";
import { bytes, text } from "../helpers.ts";

async function temporaryRoot(): Promise<{ root: string; cleanup: () => Promise<void> }> {
  const root = await mkdtemp(join(tmpdir(), "smpldoc-blob-"));
  return { root, cleanup: () => rm(root, { recursive: true, force: true }) };
}

blobContract("filesystem", async () => {
  const { root, cleanup } = await temporaryRoot();
  return { blob: createFilesystemBlob(root), cleanup };
});

describe("filesystem blob safety", () => {
  it("never reads or writes through a symbolic link that leaves the folder", async () => {
    const { root, cleanup } = await temporaryRoot();
    const outside = await temporaryRoot();
    try {
      await writeFile(join(outside.root, "secret.txt"), "top secret");
      await symlink(outside.root, join(root, "escape"));
      const blob = createFilesystemBlob(root);
      await assert.rejects(blob.get("escape/secret.txt"), InvalidKeyError);
      await assert.rejects(blob.put("escape/new.txt", bytes("x")), InvalidKeyError);
      await assert.rejects(blob.delete("escape/secret.txt"), InvalidKeyError);
      assert.deepEqual(await blob.list("escape/"), []);
    } finally {
      await cleanup();
      await outside.cleanup();
    }
  });

  it("keeps its own working folder out of reach of callers", async () => {
    const { root, cleanup } = await temporaryRoot();
    try {
      const blob = createFilesystemBlob(root);
      await assert.rejects(blob.put(".tmp/x", bytes("x")), InvalidKeyError);
      await blob.put("a", bytes("1"));
      assert.deepEqual(await blob.list(""), ["a"]);
    } finally {
      await cleanup();
    }
  });

  it("writes whole files, so a reader never sees half of one", async () => {
    const { root, cleanup } = await temporaryRoot();
    try {
      const blob = createFilesystemBlob(root);
      const big = new Uint8Array(2_000_000).fill(7);
      await Promise.all([blob.put("k", big), blob.put("k", big)]);
      assert.equal((await blob.get("k"))!.length, big.length);
    } finally {
      await cleanup();
    }
  });

  it("treats a folder name as a missing key", async () => {
    const { root, cleanup } = await temporaryRoot();
    try {
      await mkdir(join(root, "folder"));
      const blob = createFilesystemBlob(root);
      assert.equal(text(await blob.get("folder")), null);
      await blob.delete("folder");
    } finally {
      await cleanup();
    }
  });
});
