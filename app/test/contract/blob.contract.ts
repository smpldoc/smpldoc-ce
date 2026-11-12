// One test suite that every BlobStore adapter must pass.
import { describe, it, afterEach } from "node:test";
import assert from "node:assert/strict";
import type { BlobStore } from "../../src/ports/blob.ts";
import { NotFoundError } from "../../src/ports/blob.ts";
import { InvalidKeyError } from "../../src/ports/keys.ts";
import { bytes, text } from "../helpers.ts";

export interface BlobHarness {
  blob: BlobStore;
  cleanup?: () => Promise<void>;
}

export function blobContract(name: string, make: () => Promise<BlobHarness>): void {
  describe(`BlobStore contract: ${name}`, () => {
    const cleanups: Array<() => Promise<void>> = [];
    async function fresh(): Promise<BlobStore> {
      const harness = await make();
      if (harness.cleanup) cleanups.push(harness.cleanup);
      return harness.blob;
    }
    afterEach(async () => {
      while (cleanups.length) await cleanups.pop()!();
    });

    it("returns what was stored, byte for byte", async () => {
      const blob = await fresh();
      const data = Uint8Array.from([0, 1, 2, 253, 254, 255]);
      await blob.put("docs/a.bin", data);
      assert.deepEqual(await blob.get("docs/a.bin"), data);
    });

    it("returns null for a key that does not exist", async () => {
      assert.equal(await (await fresh()).get("docs/missing"), null);
    });

    it("replaces the value when a key is written again", async () => {
      const blob = await fresh();
      await blob.put("k", bytes("one"));
      await blob.put("k", bytes("two"));
      assert.equal(text(await blob.get("k")), "two");
    });

    it("hands out copies, so changing a result never changes the store", async () => {
      const blob = await fresh();
      const input = bytes("abc");
      await blob.put("k", input);
      input[0] = 0;
      const first = await blob.get("k");
      first![0] = 0;
      assert.equal(text(await blob.get("k")), "abc");
    });

    it("lists keys under a prefix, sorted", async () => {
      const blob = await fresh();
      for (const key of ["inbox/b", "inbox/a", "processed/c", "inbox/sub/d"]) await blob.put(key, bytes("x"));
      assert.deepEqual(await blob.list("inbox/"), ["inbox/a", "inbox/b", "inbox/sub/d"]);
      assert.deepEqual(await blob.list("processed/"), ["processed/c"]);
      assert.deepEqual(await blob.list("nothing/"), []);
      assert.equal((await blob.list("")).length, 4);
    });

    it("does not treat a similar name as the same folder", async () => {
      const blob = await fresh();
      await blob.put("inbox-old/a", bytes("x"));
      assert.deepEqual(await blob.list("inbox/"), []);
    });

    it("deletes a key, and deleting a missing key is not an error", async () => {
      const blob = await fresh();
      await blob.put("k", bytes("x"));
      await blob.delete("k");
      await blob.delete("k");
      assert.equal(await blob.get("k"), null);
    });

    it("moves a key, replacing the target", async () => {
      const blob = await fresh();
      await blob.put("inbox/m", bytes("mail"));
      await blob.put("processed/m", bytes("old"));
      await blob.move("inbox/m", "processed/m");
      assert.equal(await blob.get("inbox/m"), null);
      assert.equal(text(await blob.get("processed/m")), "mail");
    });

    it("refuses to move a key that does not exist", async () => {
      await assert.rejects((await fresh()).move("nope", "elsewhere"), NotFoundError);
    });

    const badKeys: Record<string, string> = {
      empty: "",
      absolute: "/etc/passwd",
      "parent segment": "../outside",
      "parent in the middle": "a/../b",
      "current segment": "./a",
      "empty segment": "a//b",
      "trailing slash": "a/",
      backslash: "a\\b",
      "null byte": "a\u0000b",
      "line break": "a\nb",
      "too long": "k".repeat(1025),
    };
    for (const [label, key] of Object.entries(badKeys)) {
      it(`refuses a key that is ${label}`, async () => {
        const blob = await fresh();
        await assert.rejects(blob.put(key, bytes("x")), InvalidKeyError);
        await assert.rejects(blob.get(key), InvalidKeyError);
        await assert.rejects(blob.delete(key), InvalidKeyError);
        await assert.rejects(blob.move(key, "ok"), InvalidKeyError);
        await assert.rejects(blob.move("ok", key), InvalidKeyError);
      });
    }

    it("refuses a prefix that does not end in a slash or climbs out", async () => {
      const blob = await fresh();
      await assert.rejects(blob.list("inbox"), InvalidKeyError);
      await assert.rejects(blob.list("../"), InvalidKeyError);
      await assert.rejects(blob.list("/"), InvalidKeyError);
    });
  });
}
