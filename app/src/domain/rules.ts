// Input limits and value rules shared by every Store, so they all refuse the same things.
// Pure functions only: this file imports nothing. Each check returns a message, or null when fine.

export const MAX_MESSAGE_ID = 998;
export const MAX_SUBJECT = 1000;
export const MAX_NOTE = 500;
export const MAX_FIELD_NAME = 200;
export const MAX_FIELD_VALUE = 100_000;

export function checkCompany(companyId: unknown): string | null {
  return typeof companyId !== "string" || companyId.trim() === "" ? "a company is required" : null;
}

export function checkNewJob(messageId: unknown, subject: string): string | null {
  if (typeof messageId !== "string" || messageId === "" || messageId.length > MAX_MESSAGE_ID) return "messageId must be 1 to 998 characters";
  if (subject.length > MAX_SUBJECT) return "subject is too long";
  return null;
}

export function checkActor(actor: unknown): string | null {
  return typeof actor !== "string" || actor.trim() === "" ? "actor is required" : null;
}

export function checkNote(note: string): string | null {
  return note.length > MAX_NOTE ? "note is too long" : null;
}

export function checkFieldValue(value: { name: unknown; value: unknown; source: unknown }): string | null {
  if (typeof value.name !== "string" || value.name === "" || value.name.length > MAX_FIELD_NAME) return "field name must be 1 to 200 characters";
  if (typeof value.value !== "string" || value.value.length > MAX_FIELD_VALUE) return "field value is too large";
  if (value.source !== "derived" && value.source !== "correction") return "source must be derived or correction";
  return null;
}

/** The value in effect for each field: the latest correction, else the latest derived value. Input is in the order added. */
export function resolveFieldValues<T extends { name: string; source: string }>(values: readonly T[]): T[] {
  const names = [...new Set(values.map((v) => v.name))];
  return names.map((name) => {
    const own = values.filter((v) => v.name === name);
    const corrections = own.filter((v) => v.source === "correction");
    return (corrections.length ? corrections : own).at(-1)!;
  });
}
