// Where original documents, incoming mail and backups are kept (a bucket, or a folder for trials).

export class NotFoundError extends Error {}

export interface BlobStore {
  /** Writes the bytes, replacing any existing value. Throws InvalidKeyError for a bad key. */
  put(key: string, data: Uint8Array): Promise<void>;
  /** Returns a copy of the bytes, or null when the key does not exist. */
  get(key: string): Promise<Uint8Array | null>;
  /** Keys that start with the prefix, sorted. The prefix is "" or ends with "/". */
  list(prefix: string): Promise<string[]>;
  /** Removes the key. A missing key is not an error. */
  delete(key: string): Promise<void>;
  /** Renames a key, replacing the target. Throws NotFoundError when `from` does not exist. */
  move(from: string, to: string): Promise<void>;
}
