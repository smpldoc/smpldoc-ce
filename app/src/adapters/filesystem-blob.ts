// BlobStore on a local folder, for trials. Keys can never leave the folder: they are checked as
// text, and then again against the real path, so a symbolic link cannot lead outside either.
import { lstat, mkdir, readFile, readdir, realpath, rename, unlink, writeFile } from "node:fs/promises";
import { randomBytes } from "node:crypto";
import { join, sep } from "node:path";
import type { BlobStore } from "../ports/blob.ts";
import { NotFoundError } from "../ports/blob.ts";
import { InvalidKeyError, assertValidKey, assertValidPrefix } from "../ports/keys.ts";

const WORK_DIR = ".tmp";

function isMissing(error: unknown): boolean {
  const code = (error as NodeJS.ErrnoException)?.code;
  return code === "ENOENT" || code === "ENOTDIR" || code === "EISDIR";
}

export function createFilesystemBlob(root: string): BlobStore {
  let realRootPromise: Promise<string> | undefined;
  const realRoot = (): Promise<string> => (realRootPromise ??= mkdir(root, { recursive: true }).then(() => realpath(root)));

  function checkKey(key: string): void {
    assertValidKey(key);
    if (key === WORK_DIR || key.startsWith(`${WORK_DIR}/`)) throw new InvalidKeyError("key uses a reserved name");
  }

  async function inside(path: string): Promise<boolean> {
    const base = await realRoot();
    return path === base || path.startsWith(base + sep);
  }

  // The real location of the key's parent folder, created if needed, proven to be inside the root.
  async function parentFor(key: string, create: boolean): Promise<string | null> {
    const base = await realRoot();
    const parent = join(base, ...key.split("/").slice(0, -1));
    if (create) await mkdir(parent, { recursive: true });
    let real: string;
    try {
      real = await realpath(parent);
    } catch (error) {
      if (isMissing(error)) return null;
      throw error;
    }
    if (!(await inside(real))) throw new InvalidKeyError("key leads outside the store");
    return real;
  }

  async function fileFor(key: string, create: boolean): Promise<string | null> {
    checkKey(key);
    const parent = await parentFor(key, create);
    if (parent === null) return null;
    const file = join(parent, key.split("/").at(-1)!);
    try {
      if ((await lstat(file)).isSymbolicLink()) throw new InvalidKeyError("key is a link");
    } catch (error) {
      if (!isMissing(error)) throw error;
    }
    return file;
  }

  async function walk(directory: string, relative: string, out: string[]): Promise<void> {
    let entries;
    try {
      entries = await readdir(directory, { withFileTypes: true });
    } catch (error) {
      if (isMissing(error)) return;
      throw error;
    }
    for (const entry of entries) {
      const key = relative === "" ? entry.name : `${relative}/${entry.name}`;
      if (relative === "" && entry.name === WORK_DIR) continue;
      if (entry.isDirectory()) await walk(join(directory, entry.name), key, out);
      else if (entry.isFile()) out.push(key);
    }
  }

  return {
    async put(key, data) {
      const file = await fileFor(key, true);
      const work = join(await realRoot(), WORK_DIR);
      await mkdir(work, { recursive: true });
      const temporary = join(work, randomBytes(12).toString("hex"));
      await writeFile(temporary, data, { flag: "wx", mode: 0o600 });
      await rename(temporary, file!);
    },
    async get(key) {
      const file = await fileFor(key, false);
      if (file === null) return null;
      try {
        return new Uint8Array(await readFile(file));
      } catch (error) {
        if (isMissing(error)) return null;
        throw error;
      }
    },
    async list(prefix) {
      assertValidPrefix(prefix);
      const base = await realRoot();
      const start = prefix === "" ? base : join(base, ...prefix.slice(0, -1).split("/"));
      let real: string;
      try {
        real = await realpath(start);
      } catch (error) {
        if (isMissing(error)) return [];
        throw error;
      }
      if (!(await inside(real))) return [];
      const keys: string[] = [];
      await walk(real, prefix === "" ? "" : prefix.slice(0, -1), keys);
      return keys.filter((key) => key.startsWith(prefix)).sort();
    },
    async delete(key) {
      const file = await fileFor(key, false);
      if (file === null) return;
      try {
        await unlink(file);
      } catch (error) {
        if (!isMissing(error) && (error as NodeJS.ErrnoException).code !== "EPERM") throw error;
      }
    },
    async move(from, to) {
      const source = await fileFor(from, false);
      const target = await fileFor(to, true);
      try {
        if (source === null) throw new NotFoundError(`${from} does not exist`);
        await rename(source, target!);
      } catch (error) {
        if (error instanceof NotFoundError) throw error;
        if (isMissing(error)) throw new NotFoundError(`${from} does not exist`);
        throw error;
      }
    },
  };
}
