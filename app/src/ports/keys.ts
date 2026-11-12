// Key rules shared by every Blob adapter, so a bad key is refused the same way everywhere.
// A key is a "/"-separated path inside the store. It can never point outside it.

export class InvalidKeyError extends Error {}

const MAX_KEY_LENGTH = 1024;
const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f]/;

function assertSegments(path: string, label: string): void {
  if (path.length > MAX_KEY_LENGTH) throw new InvalidKeyError(`${label} is too long`);
  if (CONTROL_CHARACTERS.test(path)) throw new InvalidKeyError(`${label} contains a control character`);
  if (path.includes("\\")) throw new InvalidKeyError(`${label} contains a backslash`);
  if (path.startsWith("/")) throw new InvalidKeyError(`${label} must be relative`);
  for (const segment of path.split("/")) {
    if (segment === "" || segment === "." || segment === "..") {
      throw new InvalidKeyError(`${label} contains an empty, "." or ".." segment`);
    }
  }
}

export function assertValidKey(key: string): void {
  if (typeof key !== "string" || key.length === 0) throw new InvalidKeyError("key is empty");
  assertSegments(key, "key");
}

// A prefix is "" (everything) or a key-like path ending in "/".
export function assertValidPrefix(prefix: string): void {
  if (typeof prefix !== "string") throw new InvalidKeyError("prefix is not a string");
  if (prefix === "") return;
  if (!prefix.endsWith("/")) throw new InvalidKeyError("prefix must end with /");
  assertSegments(prefix.slice(0, -1), "prefix");
}
