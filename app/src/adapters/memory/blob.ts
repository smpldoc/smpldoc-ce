// In-memory BlobStore. For tests, and for the first runner tests. Nothing is saved to disk.
import type { BlobStore } from "../../ports/blob.ts";
import { NotFoundError } from "../../ports/blob.ts";
import { assertValidKey, assertValidPrefix } from "../../ports/keys.ts";

export function createMemoryBlob(): BlobStore {
  const objects = new Map<string, Uint8Array>();
  return {
    async put(key, data) {
      assertValidKey(key);
      objects.set(key, Uint8Array.from(data));
    },
    async get(key) {
      assertValidKey(key);
      const found = objects.get(key);
      return found ? Uint8Array.from(found) : null;
    },
    async list(prefix) {
      assertValidPrefix(prefix);
      return [...objects.keys()].filter((key) => key.startsWith(prefix)).sort();
    },
    async delete(key) {
      assertValidKey(key);
      objects.delete(key);
    },
    async move(from, to) {
      assertValidKey(from);
      assertValidKey(to);
      const found = objects.get(from);
      if (!found) throw new NotFoundError(`${from} does not exist`);
      objects.delete(from);
      objects.set(to, found);
    },
  };
}
